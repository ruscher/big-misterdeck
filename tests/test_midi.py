"""MIDI input: aseqdump lines recorded from a real MisteRdeck (tests/data)."""

import os

from bigmisterdeck import midi

DATA = os.path.join(os.path.dirname(__file__), "data", "misterdeck-aseqdump.txt")


def recorded():
    with open(DATA, encoding="utf-8") as fh:
        return [e for e in map(midi.parse_event, fh) if e]


def test_real_deck_all_twelve_buttons_and_four_knobs():
    events = recorded()
    pressed = {e.number for e in events if e.kind == midi.NOTE_ON}
    released = {e.number for e in events if e.kind == midi.NOTE_OFF}
    knobs = {e.number for e in events if e.kind == midi.CONTROL}
    assert pressed == released == set(range(1, 13))
    assert knobs == {16, 17, 18, 19}
    values = [e.value for e in events if e.kind == midi.CONTROL]
    assert min(values) == 1 and max(values) == 127


def test_lines_that_are_not_events():
    for line in ("Waiting for data. Press Ctrl+C to end.", "Source  Event                  Ch  Data", "",
                 " 36:0   Pitch bend              0, value 8191", " 36:0   Port subscribed  14:0 -> 36:0"):
        assert midi.parse_event(line) is None


def test_note_on_with_velocity_zero_is_a_release():
    event = midi.parse_event(" 36:0   Note on                 0, note 4, velocity 0")
    assert event == midi.Event(midi.NOTE_OFF, 0, 4, 0)


def test_port_discovery():
    listing = (" Port    Client name                      Port name\n"
               "  0:0    System                           Timer\n"
               " 14:0    Midi Through                     Midi Through Port-0\n"
               " 36:0    Arduino Leonardo                 Arduino Leonardo MIDI 1\n")
    assert midi.parse_ports(listing)[-1] == ("36:0", "Arduino Leonardo Arduino Leonardo MIDI 1")
    assert midi.find_port("MisteRdeck|arduino leonardo", lister=lambda: listing) == "36:0"
    assert midi.find_port("MisteRdeck", lister=lambda: listing) is None
