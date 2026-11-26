# Big MisteRdeck

Transforma o **[MisteRdeck](https://www.printables.com/model/134529-misterdeck)**
(stream deck caseiro com Pro Micro, 12 botões e 4 potenciômetros) em **controle de
volume e botões de mídia no Linux**, sem Windows e sem Deej.

🇬🇧 [Read in English](README.en.md)

| Controle | Padrão |
| --- | --- |
| Potenciômetro 1 | volume geral |
| Potenciômetro 2 | microfone |
| Potenciômetro 3 | volume do Spotify |
| Potenciômetro 4 | volume do navegador (Firefox, Chrome, Brave…) |
| Botões 1–5 | tocar/pausar · anterior · próxima · mudo · mudo do microfone |
| Botões 6–12 | livres: volume ±, ou qualquer comando seu |

Tudo muda num arquivo de configuração, inclusive levar potenciômetros e botões para o
**OBS Studio**: volume das fontes de áudio, troca de cena, gravar e transmitir (veja
[OBS Studio](#obs-studio)).

## Instalar

**Como pacote** (Arch, BigLinux, Manjaro), pelo PKGBUILD em `pkgbuild/`:

```bash
git clone https://github.com/ruscher/big-misterdeck.git
cd big-misterdeck/pkgbuild
makepkg -si
systemctl --user enable --now big-misterdeck     # inicia com a sua sessão
```

**Só para o seu usuário**, sem root e em qualquer distribuição:

```bash
git clone https://github.com/ruscher/big-misterdeck.git
cd big-misterdeck
./install.sh        # instala em ~/.local e inicia com a sessão
```

Precisa de Python 3.11+, `alsa-utils` (`aseqdump`), `pactl` (PipeWire ou
PulseAudio) ou `wpctl`, e `playerctl` para os botões de mídia. O `install.sh`
diz o que falta e o comando para instalar na sua distribuição.

Para remover: `sudo pacman -R big-misterdeck` (pacote) ou `./uninstall.sh` (a
configuração fica; `--purge` apaga tudo). Se os dois estiverem instalados, vale a
cópia do `install.sh`, em `~/.local`.

## Usar

| Para… | Comando |
| --- | --- |
| conferir se está tudo certo | `big-misterdeck --check` |
| ver o que cada botão e potenciômetro manda | `big-misterdeck --listen` |
| criar o arquivo de configuração comentado | `big-misterdeck --write-config` |
| aplicar a configuração depois de editar | `systemctl --user restart big-misterdeck` |
| ver o que o serviço está fazendo | `journalctl --user -u big-misterdeck -f` |

## Configurar

`~/.config/big-misterdeck/config.toml`. Só o que você escreve muda; o resto fica
no padrão.

```toml
[knobs.18]                 # potenciômetro 3: Spotify -> VLC e mpv
action = "app_volume"
apps = "vlc|mpv"

[buttons.6]                # botão 6: abrir o site do BigLinux
action = "command"
run = ["xdg-open", "https://www.biglinux.com.br"]

[buttons.7]
action = "volume_up"
```

| Potenciômetros | Botões |
| --- | --- |
| `volume`, `microphone`, `app_volume` (com `apps`), `obs_volume` (com `source`), `none` | `play_pause`, `next`, `previous`, `stop`, `mute`, `mute_microphone`, `volume_up`, `volume_down`, `command` (com `run`), `none` |

Comandos rodam sem shell (`run` é uma lista), então nada do que chega do deck vira
um comando inventado.

## OBS Studio

Primeiro ligue o servidor do OBS: *Ferramentas → Configurações do servidor
WebSocket → Ativar servidor WebSocket*.

**Potenciômetros** regulam o volume de uma fonte de áudio do OBS, na mesma escala do
controle deslizante do mixer (o potenciômetro e o controle na tela ficam na mesma
posição):

```toml
[knobs.18]
action = "obs_volume"
source = "Mic/Aux"           # o nome exato da fonte no mixer do OBS
```

O Big MisteRdeck pega a porta e a senha nas configurações do próprio OBS; para um OBS
em outro computador, defina `OBS_WEBSOCKET_URL=obsws://host:4455/senha` no serviço
(`systemctl --user edit big-misterdeck`). Com o OBS fechado, os outros controles
continuam funcionando e ele se conecta sozinho quando o OBS abrir.
`big-misterdeck --check` confere a conexão e o nome de cada fonte.

**Botões** controlam o OBS com o [obs-cmd](https://github.com/grigio/obs-cmd)
(no Arch/BigLinux/Manjaro: `yay -S obs-cmd`), que lê a mesma `OBS_WEBSOCKET_URL`:

```toml
[buttons.6]
action = "command"
run = ["obs-cmd", "recording", "toggle"]

[buttons.7]
action = "command"
run = ["obs-cmd", "scene", "switch", "Câmera"]
```

`obs-cmd scene list` e `obs-cmd input list` mostram os nomes das cenas e das fontes.

## Como funciona

- O deck aparece no Linux como um dispositivo **MIDI** ("Arduino Leonardo"): os
  botões mandam as notas 1–12 e os potenciômetros, os *controllers* 16–19.
- O Big MisteRdeck lê pelo **sequenciador do ALSA**, que é compartilhado: o OBS, um
  DAW ou o `aseqdump` continuam recebendo os mesmos eventos.
- Uma volta inteira de potenciômetro manda ~90 eventos. Cada potenciômetro aplica só
  o valor mais recente, no máximo 25 vezes por segundo, e a posição final nunca se
  perde.
- Se o deck for desconectado ou reiniciado, o serviço espera ele voltar e continua.

## Problemas

- **`--check` diz "deck not found"**: confira `lsusb`. Se o deck não aparece, troque
  o cabo (muitos cabos USB-C só carregam) e ligue direto numa porta do computador,
  sem hub.
- **Os potenciômetros vão ao contrário**: `invert = true` em `[behaviour]`.
- **O volume vai além de 100%**: `max_volume` em `[behaviour]` (padrão 100).
- **O potenciômetro do OBS não faz nada**: `journalctl --user -u big-misterdeck`
  diz o motivo (OBS fechado, servidor WebSocket desligado, senha errada ou fonte com
  outro nome). `big-misterdeck --check` testa tudo de uma vez.

## Licença

GPL-3.0-or-later. O MisteRdeck (hardware e modelo 3D) é de MisteR_ofcl; este
projeto só cuida do lado do Linux.
