import json
import subprocess

import pytest

from bigmisterdeck import actions


class Runner:
    """Records argv; answers pactl queries like a real PipeWire with two streams."""

    def __init__(self, volume="Volume: front-left: 32768 /  50% / -18.06 dB"):
        self.calls, self.volume = [], volume

    def __call__(self, argv):
        self.calls.append(argv)
        out = ""
        if argv[:4] == ["pactl", "-f", "json", "list"]:
            out = json.dumps([
                {"index": 51, "properties": {"application.name": "Spotify", "application.process.binary": "spotify"}},
                {"index": 77, "properties": {"application.name": "Firefox", "media.name": "YouTube"}},
            ])
        elif argv[:2] == ["pactl", "get-sink-volume"]:
            out = self.volume
        return subprocess.CompletedProcess(argv, 0, stdout=out, stderr="")


def audio(runner, tools=("pactl", "wpctl", "playerctl")):
    return actions.Audio(run=runner, which=lambda t: f"/usr/bin/{t}" if t in tools else None, clock=lambda: 100.0)


@pytest.mark.parametrize("value, expected", [(0, 0), (1, 0), (2, 1), (64, 50), (127, 100)])
def test_knob_percent(value, expected):
    assert actions.knob_percent(value) == expected


def test_knob_percent_options():
    assert actions.knob_percent(127, max_volume=150) == 150
    assert actions.knob_percent(127, invert=True) == 0 and actions.knob_percent(1, invert=True) == 100


def test_volume_microphone_and_app_volume():
    run = Runner()
    a = audio(run)
    actions.turn({"action": "volume"}, 40, a)
    actions.turn({"action": "microphone"}, 70, a)
    actions.turn({"action": "app_volume", "apps": "spotify"}, 25, a)
    actions.turn({"action": "app_volume", "apps": "firefox|chrom"}, 60, a)
    sets = [c for c in run.calls if "list" not in c]
    assert sets == [["pactl", "set-sink-volume", "@DEFAULT_SINK@", "40%"],
                    ["pactl", "set-source-volume", "@DEFAULT_SOURCE@", "70%"],
                    ["pactl", "set-sink-input-volume", "51", "25%"],
                    ["pactl", "set-sink-input-volume", "77", "60%"]]
    assert sum(1 for c in run.calls if "list" in c) == 1          # stream list cached


def test_wpctl_fallback():
    run = Runner()
    a = audio(run, tools=("wpctl",))
    actions.turn({"action": "volume"}, 40, a)
    actions.press({"action": "mute"}, a, {})
    assert run.calls == [["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "0.40"],
                         ["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"]]


@pytest.mark.parametrize("action, argv", [
    ("play_pause", ["playerctl", "play-pause"]), ("next", ["playerctl", "next"]),
    ("previous", ["playerctl", "previous"]), ("mute", ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"]),
    ("mute_microphone", ["pactl", "set-source-mute", "@DEFAULT_SOURCE@", "toggle"]),
])
def test_buttons(action, argv):
    run = Runner()
    actions.press({"action": action}, audio(run), {})
    assert run.calls == [argv]


def test_volume_buttons_respect_the_ceiling():
    run = Runner(volume="Volume: front-left: 65536 /  98% / 0 dB")
    actions.press({"action": "volume_up"}, audio(run), {"step": 5, "max_volume": 100})
    assert run.calls[-1] == ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "100%"]


def test_command_button_runs_without_a_shell():
    started = []
    out = actions.press({"action": "command", "run": ["obs", "--startstreaming"]}, None, {}, spawn=started.append)
    assert started == [["obs", "--startstreaming"]] and out.startswith("command obs")


def test_missing_command_is_reported_not_raised():
    out = actions.press({"action": "command", "run": ["/nonexistent/program"]}, None, {})
    assert out.startswith("command failed")
