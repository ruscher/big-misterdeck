"""MIDI input through the ALSA sequencer (``aseqdump`` from alsa-utils).

The sequencer is used instead of opening ``/dev/snd/midiC*D0`` so the deck stays
shared: OBS, a DAW or ``aseqdump`` in a terminal still receive its events while
Big MisteRdeck runs. It also needs no Python MIDI library.
"""

import re
import subprocess
from dataclasses import dataclass

NOTE_ON, NOTE_OFF, CONTROL = "note_on", "note_off", "control"

# " 36:0   Note on                 0, note 4, velocity 127"
# " 36:0   Control change          0, controller 16, value 1"
_EVENT = re.compile(
    r"^\s*\d+:\d+\s+(?P<kind>Note on|Note off|Control change)\s+(?P<channel>\d+),\s+"
    r"(?:note|controller)\s+(?P<number>\d+),\s+(?:velocity|value)\s+(?P<value>\d+)")
# "  36:0    Arduino Leonardo                 Arduino Leonardo MIDI 1"
_PORT = re.compile(r"^\s*(?P<port>\d+:\d+)\s+(?P<rest>.+?)\s*$")


@dataclass(frozen=True)
class Event:
    kind: str
    channel: int
    number: int
    value: int


def parse_event(line):
    """An :class:`Event` from one ``aseqdump`` line, or None (headers, other messages)."""
    match = _EVENT.match(line)
    if not match:
        return None
    kind = {"Note on": NOTE_ON, "Note off": NOTE_OFF, "Control change": CONTROL}[match["kind"]]
    value = int(match["value"])
    if kind == NOTE_ON and value == 0:          # running status: note on with velocity 0 is a release
        kind = NOTE_OFF
    return Event(kind, int(match["channel"]), int(match["number"]), value)


def parse_ports(text):
    """[(port, description)] from ``aseqdump -l``."""
    ports = []
    for line in text.splitlines()[1:]:
        match = _PORT.match(line)
        if match:
            ports.append((match["port"], " ".join(match["rest"].split())))
    return ports


def find_port(pattern, lister=None):
    """The first sequencer port whose names match ``pattern`` (case-insensitive), or None."""
    lister = lister or (lambda: subprocess.run(["aseqdump", "-l"], capture_output=True, text=True,
                                               timeout=5, check=False).stdout)
    regex = re.compile(pattern, re.IGNORECASE)
    for port, description in parse_ports(lister()):
        if regex.search(description):
            return port
    return None


def open_stream(port):
    """``aseqdump`` subscribed to ``port``; its stdout yields one event per line."""
    return subprocess.Popen(["aseqdump", "-p", port], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            bufsize=0)
