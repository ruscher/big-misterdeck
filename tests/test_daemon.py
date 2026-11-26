"""The service loop: knob rate limiting, reconnection, a real pipe as the event source."""

import subprocess
import sys
import threading

from bigmisterdeck import config, daemon, midi


class FakeAudio:
    def __init__(self):
        self.calls = []

    def set_volume(self, percent, source=False):
        self.calls.append(("mic" if source else "vol", percent))

    def set_app_volume(self, pattern, percent):
        self.calls.append(("app", pattern, percent))

    def media(self, command):
        self.calls.append(("media", command))

    def toggle_mute(self, source=False):
        self.calls.append(("mute", source))


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def cc(number, value):
    return midi.Event(midi.CONTROL, 0, number, value)


def test_a_fast_knob_turn_is_rate_limited_and_ends_on_the_last_value():
    clock, audio = Clock(), FakeAudio()
    deck = daemon.Deck(config.load("/nonexistent"), audio, clock=clock)
    for value in range(1, 128):                 # one sweep, all within 20 ms
        deck.handle(cc(16, value))
        clock.now += 0.0002
    assert audio.calls == [("vol", 0)]           # first one applied at once, the rest waits
    clock.now += 0.05
    deck.flush()
    assert audio.calls == [("vol", 0), ("vol", 100)]   # and the final position is never lost


def test_same_percent_is_not_sent_twice_and_buttons_act_on_press_only():
    clock, audio = Clock(), FakeAudio()
    deck = daemon.Deck(config.load("/nonexistent"), audio, clock=clock)
    deck.handle(cc(17, 64))
    clock.now += 1
    deck.handle(cc(17, 64))
    deck.handle(midi.Event(midi.NOTE_ON, 0, 1, 127))
    deck.handle(midi.Event(midi.NOTE_OFF, 0, 1, 127))
    deck.handle(midi.Event(midi.NOTE_ON, 0, 12, 127))      # not mapped by default
    deck.handle(cc(99, 10))                                 # not mapped either
    assert audio.calls == [("mic", 50), ("media", "play-pause")]


def test_follow_reads_lines_that_arrive_together():
    """All events written at once must be handled (no line stuck in a buffer)."""
    audio = FakeAudio()
    deck = daemon.Deck(config.load("/nonexistent"), audio)
    script = ("import sys; sys.stdout.write("
              "' 36:0   Note on                 0, note 3, velocity 127\\n'"
              "' 36:0   Note on                 0, note 4, velocity 127\\n'"
              "' 36:0   Control change          0, controller 18, value 127\\n'); sys.stdout.flush()")
    stream = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, bufsize=0)
    try:
        daemon.follow(stream, deck, threading.Event())
    finally:
        stream.wait(timeout=5)
        stream.stdout.close()
    assert audio.calls == [("media", "next"), ("mute", False), ("app", "spotify", 100)]


def test_run_waits_for_the_deck_and_reconnects():
    audio, stop = FakeAudio(), threading.Event()
    ports = iter([None, "36:0", "36:0"])
    opened = []

    def find(pattern):
        try:
            return next(ports)
        except StopIteration:
            stop.set()
            return None

    def open_stream(port):
        opened.append(port)
        line = "' 36:0   Note on                 0, note 1, velocity 127\\n'"
        return subprocess.Popen([sys.executable, "-c", f"import sys; sys.stdout.write({line})"],
                                stdout=subprocess.PIPE, bufsize=0)

    assert daemon.run(config.load("/nonexistent"), audio, stop, find=find, open_stream=open_stream,
                      retry=0.01) == 0
    assert opened == ["36:0", "36:0"]                         # unplugged and plugged back
    assert audio.calls == [("media", "play-pause")] * 2
