# Big MisteRdeck

Turns the **[MisteRdeck](https://www.printables.com/model/134529-misterdeck)** (a
DIY Pro Micro stream deck with 12 buttons and 4 knobs) into **volume knobs and
media buttons on Linux**, without Windows or Deej.

🇧🇷 [Leia em português](README.md)

Defaults: knob 1 master volume, knob 2 microphone, knob 3 Spotify, knob 4 web
browser; buttons 1–5 play/pause, previous, next, mute, mute microphone; buttons
6–12 free for volume ± or your own commands.

```bash
git clone https://github.com/ruscher/big-misterdeck.git
cd big-misterdeck && ./install.sh          # per user, no root
big-misterdeck --check                     # tools, deck, configuration
big-misterdeck --listen                    # what each control sends
big-misterdeck --write-config              # commented ~/.config/big-misterdeck/config.toml
```

Needs Python 3.11+, alsa-utils (`aseqdump`), `pactl` or `wpctl`, and `playerctl`.
The deck is read through the ALSA sequencer, so OBS or a DAW keep receiving it at
the same time. A knob sweep (~90 events) is applied at most 25 times per second
without losing the final position, and an unplugged deck is picked up again when it
comes back.

License: GPL-3.0-or-later. The MisteRdeck hardware and 3D model are by MisteR_ofcl.
