"""Command line: run the service, watch the deck, check the setup, write a config."""

import argparse
import logging
import os
import signal
import shutil
import sys
import threading

from . import __version__, actions, config, daemon, midi, obs

EXAMPLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.example.toml")


def cmd_listen(cfg, stop):
    """Print every button and knob event (to learn the numbers your deck sends)."""
    port = midi.find_port(cfg["device"]["match"])
    if port is None:
        print("deck not found; is it plugged in? (big-misterdeck --check)", file=sys.stderr)
        return 1
    print(f"listening on MIDI port {port}; press buttons and turn knobs (Ctrl+C to stop)")
    stream = midi.open_stream(port)
    try:
        for raw in iter(stream.stdout.readline, b""):
            if stop.is_set():
                break
            event = midi.parse_event(raw.decode("utf-8", errors="replace"))
            if event is None:
                continue
            if event.kind == midi.CONTROL:
                knob = cfg["knobs"].get(event.number, {}).get("action", "not mapped")
                print(f"knob    {event.number:3d}  value {event.value:3d}  "
                      f"-> {actions.knob_percent(event.value):3d}%  ({knob})")
            elif event.kind == midi.NOTE_ON:
                button = cfg["buttons"].get(event.number, {}).get("action", "not mapped")
                print(f"button  {event.number:3d}  pressed            ({button})")
    except KeyboardInterrupt:
        pass
    finally:
        stream.terminate()
        stream.wait(timeout=2)
        stream.stdout.close()
    return 0


def cmd_check(cfg):
    ok = True
    for tool, why in (("aseqdump", "reads the deck (alsa-utils)"), ("pactl", "volume (or wpctl)"),
                      ("playerctl", "media buttons")):
        found = shutil.which(tool)
        if tool == "pactl" and not found and shutil.which("wpctl"):
            found = shutil.which("wpctl") + " (fallback)"
        print(f"{'OK ' if found else '!! '} {tool:10s} {found or 'missing'} - {why}")
        ok &= bool(found) or tool == "playerctl"
    port = midi.find_port(cfg["device"]["match"]) if shutil.which("aseqdump") else None
    print(f"{'OK ' if port else '!! '} deck       {('MIDI port ' + port) if port else 'not found'}")
    print(f"OK  config     {config.path() if os.path.exists(config.path()) else 'built-in defaults'}: "
          f"{len(cfg['knobs'])} knobs, {len(cfg['buttons'])} buttons")
    ok &= check_obs(cfg)
    return 0 if ok and port else 1


def check_obs(cfg, client=None):
    """Only when a knob uses OBS: is OBS reachable, and does every source exist?"""
    sources = sorted({knob["source"] for knob in cfg["knobs"].values() if knob["action"] == "obs_volume"})
    if not sources:
        return True
    client = client or obs.Client(retry=0)
    try:
        host, port, _ = client.endpoint()
    except ValueError as error:
        print(f"!!  obs        {error}")
        return False
    if not client.connected():
        print(f"!!  obs        not reachable on {host}:{port} - open OBS and turn on "
              "Tools > WebSocket Server Settings > Enable")
        return False
    print(f"OK  obs        {host}:{port}")
    ok = True
    for source in sources:
        found = client.request("GetInputVolume", {"inputName": source}) is not None
        missing = "" if found else " not found (obs-cmd input list)"
        print(f"{'OK ' if found else '!! '} obs source {source!r}{missing}")
        ok &= found
    client.close()
    return ok


def main(argv=None):
    parser = argparse.ArgumentParser(prog="big-misterdeck",
                                     description="MisteRdeck volume knobs and media buttons for Linux")
    parser.add_argument("--listen", action="store_true", help="show the deck's events (learn its numbers)")
    parser.add_argument("--check", action="store_true", help="check tools, deck and configuration")
    parser.add_argument("--write-config", action="store_true",
                        help=f"write the commented example to {config.path()} (keeps an existing file)")
    parser.add_argument("--config", help="configuration file (default: %(default)s)", default=None)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(message)s")

    if args.write_config:
        target = args.config or config.path()
        if os.path.exists(target):
            print(f"{target} already exists; not overwritten", file=sys.stderr)
            return 1
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copyfile(EXAMPLE, target)
        print(target)
        return 0
    try:
        cfg = config.load(args.config)
    except config.ConfigError as error:
        print(f"configuration error:\n{error}", file=sys.stderr)
        return 2
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    if args.check:
        return cmd_check(cfg)
    if args.listen:
        return cmd_listen(cfg, stop)
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    return daemon.run(cfg, stop=stop)


if __name__ == "__main__":
    sys.exit(main())
