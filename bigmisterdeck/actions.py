"""What knobs and buttons do: PipeWire/PulseAudio volume (``pactl``, ``wpctl`` as
fallback), MPRIS media (``playerctl``), OBS sources (:mod:`.obs`) and user commands.

Every external call goes through ``run`` (injectable for tests), with an argument
list (never a shell) and a timeout.
"""

import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time

from . import obs as obs_ws

log = logging.getLogger("big-misterdeck")
SINK, SOURCE = "@DEFAULT_SINK@", "@DEFAULT_SOURCE@"


def knob_percent(value, max_volume=100, invert=False):
    """MIDI 0-127 -> 0..max_volume %. The deck's lowest reading is 1, so 0-1 both mean silence."""
    value = max(0, min(127, int(value)))
    if invert:
        value = 128 - max(1, value)     # the deck's travel is 1..127: mirror it onto itself
    if value <= 1:
        return 0
    return round((value - 1) / 126 * max_volume)


class Audio:
    def __init__(self, run=None, which=shutil.which, clock=time.monotonic):
        self.run = run or (lambda argv: subprocess.run(argv, capture_output=True, text=True, timeout=3,
                                                       check=False))
        self.pactl = which("pactl")
        self.wpctl = which("wpctl")
        self.playerctl = which("playerctl")
        self.clock = clock
        self._streams = (0.0, [])

    # --- volume ---------------------------------------------------------------------
    def set_volume(self, percent, source=False):
        target = SOURCE if source else SINK
        if self.pactl:
            return self._ok(["pactl", "set-source-volume" if source else "set-sink-volume", target, f"{percent}%"])
        if self.wpctl:
            node = "@DEFAULT_AUDIO_SOURCE@" if source else "@DEFAULT_AUDIO_SINK@"
            return self._ok(["wpctl", "set-volume", node, f"{percent / 100:.2f}"])
        log.warning("neither pactl nor wpctl found: volume unchanged")
        return False

    def step_volume(self, delta, limit=100):
        if self.pactl:
            # pactl has no ceiling; read, clamp and set
            current = self.current_volume()
            if current is not None:
                return self.set_volume(max(0, min(limit, current + delta)))
            return self._ok(["pactl", "set-sink-volume", SINK, f"{delta:+d}%"])
        if self.wpctl:
            return self._ok(["wpctl", "set-volume", "-l", f"{limit / 100:.2f}", "@DEFAULT_AUDIO_SINK@",
                             f"{abs(delta)}%{'+' if delta > 0 else '-'}"])
        return False

    def current_volume(self):
        out = self.run(["pactl", "get-sink-volume", SINK])
        match = re.search(r"(\d+)%", getattr(out, "stdout", "") or "")
        return int(match.group(1)) if match else None

    def toggle_mute(self, source=False):
        if self.pactl:
            return self._ok(["pactl", "set-source-mute" if source else "set-sink-mute",
                             SOURCE if source else SINK, "toggle"])
        if self.wpctl:
            return self._ok(["wpctl", "set-mute", "@DEFAULT_AUDIO_SOURCE@" if source else "@DEFAULT_AUDIO_SINK@",
                             "toggle"])
        return False

    def streams(self, max_age=2.0):
        """Playback streams [(index, name)], cached for ``max_age`` s (a knob turn sends ~90 events)."""
        stamp, cached = self._streams
        if self.clock() - stamp < max_age:
            return cached
        found = []
        if self.pactl:
            out = self.run(["pactl", "-f", "json", "list", "sink-inputs"])
            try:
                for item in json.loads(getattr(out, "stdout", "") or "[]"):
                    props = item.get("properties", {})
                    name = " ".join(filter(None, (props.get("application.name"),
                                                  props.get("application.process.binary"),
                                                  props.get("media.name"))))
                    found.append((item["index"], name))
            except (ValueError, KeyError, TypeError):
                log.warning("could not read the playback streams from pactl")
        self._streams = (self.clock(), found)
        return found

    def set_app_volume(self, pattern, percent):
        """Volume of every playback stream whose application matches ``pattern``; how many were set."""
        regex = re.compile(pattern, re.IGNORECASE)
        count = 0
        for index, name in self.streams():
            if regex.search(name) and self._ok(["pactl", "set-sink-input-volume", str(index), f"{percent}%"]):
                count += 1
        return count

    # --- media -----------------------------------------------------------------------
    def media(self, command):
        if not self.playerctl:
            log.warning("playerctl not found: media buttons do nothing")
            return False
        return self._ok(["playerctl", command])

    def _ok(self, argv):
        try:
            result = self.run(argv)
        except (OSError, subprocess.SubprocessError) as error:
            log.warning("%s: %s", argv[0], error)
            return False
        code = getattr(result, "returncode", 0)
        if code:
            log.debug("%s exited with %s: %s", " ".join(argv), code, getattr(result, "stderr", ""))
        return code == 0


MEDIA = {"play_pause": "play-pause", "next": "next", "previous": "previous", "stop": "stop"}


def _spawn(argv):
    """Start a user command without blocking the deck and reap it when it ends (no zombies)."""
    if not shutil.which(argv[0]) and not os.path.isfile(argv[0]):
        raise OSError(f"{argv[0]}: not found")

    def wait():
        try:
            subprocess.run(argv, stdin=subprocess.DEVNULL, start_new_session=True, check=False)
        except OSError as error:
            log.warning("command %s: %s", argv, error)
    threading.Thread(target=wait, daemon=True).start()


def press(button, audio, behaviour, spawn=None, obs=None):
    """Run a button's action; returns a short description for the log."""
    action = button.get("action", "none")
    if action in obs_ws.BUTTONS:
        target = button.get("scene") or button.get("source")
        label = f"{action} {target!r}" if target else action
        if obs is None or not obs.press(action, button):
            return f"{label} failed"            # the OBS client has logged why
        return label
    if action in MEDIA:
        audio.media(MEDIA[action])
    elif action == "mute":
        audio.toggle_mute()
    elif action == "mute_microphone":
        audio.toggle_mute(source=True)
    elif action in ("volume_up", "volume_down"):
        step = int(behaviour.get("step", 5)) * (1 if action == "volume_up" else -1)
        audio.step_volume(step, int(behaviour.get("max_volume", 100)))
    elif action == "command":
        argv = list(button["run"])
        try:
            (spawn or _spawn)(argv)
        except OSError as error:
            log.warning("command %s: %s", argv, error)
            return f"command failed: {error}"
        return "command " + " ".join(argv)
    return action


def turn(knob, percent, audio, obs=None):
    action = knob.get("action", "none")
    if action == "volume":
        audio.set_volume(percent)
    elif action == "microphone":
        audio.set_volume(percent, source=True)
    elif action == "app_volume":
        audio.set_app_volume(knob["apps"], percent)
    elif action == "obs_volume" and obs is not None:
        obs.set_volume(knob["source"], percent)
    return action
