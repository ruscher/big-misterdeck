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

**OBS Studio**: a knob can set the volume of an OBS audio source over obs-websocket
(OBS 28+; turn on *Tools → WebSocket Server Settings*), on the same scale as the
mixer slider. For an OBS on this computer the port and password come from OBS's own
settings; `OBS_WEBSOCKET_URL=obsws://host:4455/password` overrides them:

```toml
[knobs.18]
action = "obs_volume"
source = "Mic/Aux"
```

Buttons can drive OBS with [obs-cmd](https://github.com/grigio/obs-cmd). Unlike the
knobs, obs-cmd does not read OBS's settings (without `OBS_WEBSOCKET_URL` it tries the
password `secret`), so give the service the address and password — run
`systemctl --user edit big-misterdeck`, add the lines below, then
`systemctl --user restart big-misterdeck`:

```ini
[Service]
Environment=OBS_WEBSOCKET_URL=obsws://localhost:4455/YOUR_PASSWORD
```

```toml
[buttons.6]
action = "command"
run = ["obs-cmd", "scene", "switch", "Camera"]
```

The service's variable does not reach your terminal: `export` it there too before
running `obs-cmd` or `big-misterdeck --check` against a remote OBS.

Needs Python 3.11+, alsa-utils (`aseqdump`), `pactl` or `wpctl`, and `playerctl`.
The deck is read through the ALSA sequencer, so OBS or a DAW keep receiving it at
the same time. A knob sweep (~90 events) is applied at most 25 times per second
without losing the final position, and an unplugged deck is picked up again when it
comes back.

License: GPL-3.0-or-later. The MisteRdeck hardware and 3D model are by MisteR_ofcl.
