import pytest

from bigmisterdeck import config


def write(tmp_path, text):
    path = tmp_path / "config.toml"
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_defaults_without_a_file(tmp_path):
    cfg = config.load(str(tmp_path / "missing.toml"))
    assert cfg["knobs"][16]["action"] == "volume" and cfg["knobs"][18]["apps"] == "spotify"
    assert cfg["buttons"][1]["action"] == "play_pause" and 12 not in cfg["buttons"]


def test_user_entries_replace_one_control_each(tmp_path):
    cfg = config.load(write(tmp_path, """
[knobs.18]
action = "app_volume"
apps = "vlc|mpv"

[knobs.19]
action = "none"

[buttons.12]
action = "command"
run = ["obs", "--startstreaming"]

[behaviour]
max_volume = 120
"""))
    assert cfg["knobs"][18]["apps"] == "vlc|mpv"
    assert cfg["knobs"][19]["action"] == "none"
    assert cfg["knobs"][16]["action"] == "volume"             # untouched default stays
    assert cfg["buttons"][12]["run"] == ["obs", "--startstreaming"]
    assert cfg["behaviour"]["max_volume"] == 120 and cfg["behaviour"]["rate_hz"] == 25


def test_the_shipped_example_is_valid():
    import os
    example = os.path.join(os.path.dirname(config.__file__), "config.example.toml")
    cfg = config.load(example)
    assert cfg["knobs"] == config.load("/nonexistent")["knobs"]


@pytest.mark.parametrize("text, message", [
    ('[knobs.x]\naction = "volume"', "MIDI number"),
    ('[knobs.16]\naction = "explode"', "action must be"),
    ('[knobs.18]\naction = "app_volume"', "needs apps"),
    ('[knobs.18]\naction = "app_volume"\napps = "("', "valid pattern"),
    ('[buttons.6]\naction = "command"\nrun = "rm -rf /"', "run = ["),
    ('[behaviour]\nmax_volume = 400', "max_volume"),
    ("not toml [", "config.toml"),
])
def test_errors_are_explained(tmp_path, text, message):
    with pytest.raises(config.ConfigError, match=message.replace("[", r"\[").replace("(", r"\(")):
        config.load(write(tmp_path, text))


def test_the_commented_button_examples_are_valid_when_uncommented():
    import pathlib
    import tomllib
    text = (pathlib.Path(config.__file__).parent / "config.example.toml").read_text(encoding="utf-8")
    examples = text[text.index("# Exemplos para os botões"):].splitlines()[1:]
    user = tomllib.loads("\n".join(line[2:] if line.startswith("# ") else "" for line in examples))
    cfg = config.validate(config._merge(config.DEFAULTS, user))
    assert {6, 7, 8, 9, 12} <= set(cfg["buttons"])
