"""Configuration: ``~/.config/big-misterdeck/config.toml`` over the built-in defaults.

Knobs are keyed by MIDI controller number, buttons by note number (the
MisteRdeck sends notes 1-12 and controllers 16-19). Run
``big-misterdeck --listen`` to see the numbers your deck sends.
"""

import copy
import os
import re
import tomllib

KNOB_ACTIONS = {"volume", "microphone", "app_volume", "none"}
BUTTON_ACTIONS = {"play_pause", "next", "previous", "stop", "mute", "mute_microphone", "volume_up",
                  "volume_down", "command", "none"}

DEFAULTS = {
    "device": {"match": "MisteRdeck|Arduino Leonardo|Arduino Micro|Pro Micro"},
    "knobs": {
        "16": {"action": "volume"},
        "17": {"action": "microphone"},
        "18": {"action": "app_volume", "apps": "spotify"},
        "19": {"action": "app_volume", "apps": "firefox|chrom|brave|vivaldi|opera"},
    },
    "buttons": {
        "1": {"action": "play_pause"},
        "2": {"action": "previous"},
        "3": {"action": "next"},
        "4": {"action": "mute"},
        "5": {"action": "mute_microphone"},
    },
    "behaviour": {
        "max_volume": 100,      # percent reached at the knob's end (up to 150)
        "step": 5,              # percent for volume_up / volume_down buttons
        "rate_hz": 25,          # at most this many volume changes per second per knob
        "invert": False,        # knobs wired backwards
    },
}


class ConfigError(ValueError):
    pass


def path():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "big-misterdeck", "config.toml")


def _merge(base, extra):
    out = copy.deepcopy(base)
    for key, value in extra.items():
        if key in ("knobs", "buttons") and isinstance(value, dict):
            # per control: an entry replaces that knob/button only (action = "none" turns a default off)
            out[key] = {**out.get(key, {}), **{str(k): copy.deepcopy(v) for k, v in value.items()}}
        elif isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def validate(cfg):
    """Raise :class:`ConfigError` with every problem; return the config with int keys."""
    problems = []
    knobs, buttons = {}, {}
    for section, actions, target in (("knobs", KNOB_ACTIONS, knobs), ("buttons", BUTTON_ACTIONS, buttons)):
        for key, entry in (cfg.get(section) or {}).items():
            try:
                number = int(key)
            except (TypeError, ValueError):
                problems.append(f"[{section}] \"{key}\": the key must be a MIDI number")
                continue
            if not isinstance(entry, dict) or entry.get("action") not in actions:
                problems.append(f"[{section}.\"{key}\"] action must be one of: {', '.join(sorted(actions))}")
                continue
            if entry["action"] == "app_volume":
                try:
                    re.compile(str(entry.get("apps", "")))
                except re.error as error:
                    problems.append(f"[{section}.\"{key}\"] apps is not a valid pattern: {error}")
                if not entry.get("apps"):
                    problems.append(f"[{section}.\"{key}\"] app_volume needs apps = \"name|other\"")
            if entry["action"] == "command" and not (isinstance(entry.get("run"), list) and entry["run"]
                                                     and all(isinstance(a, str) for a in entry["run"])):
                problems.append(f"[{section}.\"{key}\"] command needs run = [\"program\", \"arg\", ...]")
            target[number] = dict(entry)
    behaviour = cfg.get("behaviour") or {}
    if not 1 <= int(behaviour.get("max_volume", 100)) <= 150:
        problems.append("[behaviour] max_volume must be 1-150")
    if not 1 <= int(behaviour.get("rate_hz", 25)) <= 100:
        problems.append("[behaviour] rate_hz must be 1-100")
    if not 1 <= int(behaviour.get("step", 5)) <= 50:
        problems.append("[behaviour] step must be 1-50")
    try:
        re.compile(cfg["device"]["match"])
    except (KeyError, TypeError, re.error) as error:
        problems.append(f"[device] match is not a valid pattern: {error}")
    if problems:
        raise ConfigError("\n".join(problems))
    out = dict(cfg)
    out["knobs"], out["buttons"] = knobs, buttons
    return out


def load(file=None):
    """Defaults merged with the user's file (absent file = defaults)."""
    file = file or path()
    cfg = DEFAULTS
    if os.path.exists(file):
        with open(file, "rb") as handle:
            try:
                user = tomllib.load(handle)
            except tomllib.TOMLDecodeError as error:
                raise ConfigError(f"{file}: {error}") from error
        cfg = _merge(DEFAULTS, user)
    return validate(cfg)
