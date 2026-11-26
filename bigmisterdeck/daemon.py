"""The running service: finds the deck, follows its events and applies them.

* Knob turns arrive as ~90 events per sweep; each knob applies only its latest
  value, at most ``rate_hz`` times per second, and never the same percent twice.
* Unplugging the deck (or a reset) ends the event stream; the service waits for
  the port to come back and resubscribes, without restarting.
"""

import logging
import os
import select
import threading
import time

from . import actions, config, midi

log = logging.getLogger("big-misterdeck")


class Deck:
    """Turns MIDI events into actions (no I/O of its own: testable without a device)."""

    def __init__(self, cfg, audio, clock=time.monotonic):
        self.cfg = cfg
        self.audio = audio
        self.clock = clock
        behaviour = cfg.get("behaviour", {})
        self.interval = 1.0 / int(behaviour.get("rate_hz", 25))
        self.max_volume = int(behaviour.get("max_volume", 100))
        self.invert = bool(behaviour.get("invert", False))
        self.pending = {}            # knob -> percent waiting for its turn
        self.applied = {}            # knob -> last percent applied
        self.last_at = {}            # knob -> when it was last applied

    def handle(self, event):
        if event.kind == midi.NOTE_ON:
            button = self.cfg["buttons"].get(event.number)
            if button:
                log.info("button %s: %s", event.number, actions.press(button, self.audio, self.cfg["behaviour"]))
        elif event.kind == midi.CONTROL and event.number in self.cfg["knobs"]:
            self.pending[event.number] = actions.knob_percent(event.value, self.max_volume, self.invert)
            self.flush()

    def flush(self):
        """Apply pending knob values whose interval has passed; returns seconds until the next is due."""
        now = self.clock()
        wait = None
        for number, percent in list(self.pending.items()):
            due = self.last_at.get(number, -1e9) + self.interval
            if now < due:
                wait = due - now if wait is None else min(wait, due - now)
                continue
            del self.pending[number]
            if self.applied.get(number) == percent:
                continue
            knob = self.cfg["knobs"][number]
            actions.turn(knob, percent, self.audio)
            self.applied[number], self.last_at[number] = percent, now
            log.debug("knob %s: %s %s%%", number, knob["action"], percent)
        return wait


def follow(stream, deck, stop):
    """Feed ``stream`` (aseqdump) lines to ``deck`` until it ends or ``stop`` is set.

    Reads the raw descriptor (os.read) and splits lines itself: a buffered
    readline() after select() would leave lines that arrived together in the
    buffer, unseen until the next event, and a knob would lag behind.
    """
    fd = stream.stdout.fileno()
    pending = b""
    while not stop.is_set():
        timeout = deck.flush()
        ready, _, _ = select.select([fd], [], [], 0.25 if timeout is None else min(0.25, timeout))
        if not ready:
            if stream.poll() is not None:
                break
            continue
        chunk = os.read(fd, 4096)
        if not chunk:
            break
        pending += chunk
        *lines, pending = pending.split(b"\n")
        for line in lines:
            event = midi.parse_event(line.decode("utf-8", errors="replace"))
            if event:
                deck.handle(event)
    deck.flush()


def run(cfg=None, audio=None, stop=None, find=midi.find_port, open_stream=midi.open_stream, retry=2.0):
    cfg = cfg or config.load()
    audio = audio or actions.Audio()
    stop = stop or threading.Event()
    deck = Deck(cfg, audio)
    waiting_logged = False
    while not stop.is_set():
        port = find(cfg["device"]["match"])
        if port is None:
            if not waiting_logged:
                log.info("waiting for the deck (pattern %r)", cfg["device"]["match"])
                waiting_logged = True
            stop.wait(retry)
            continue
        waiting_logged = False
        log.info("deck connected on MIDI port %s", port)
        stream = open_stream(port)
        try:
            follow(stream, deck, stop)
        finally:
            stream.terminate()
            try:
                stream.wait(timeout=2)
            except Exception:  # noqa: BLE001 - it must not outlive us
                stream.kill()
            if stream.stdout:
                stream.stdout.close()
        if not stop.is_set():
            log.info("deck disconnected")
            stop.wait(retry)
    return 0
