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

Tudo muda num arquivo de configuração.

## Instalar

```bash
git clone https://github.com/ruscher/big-misterdeck.git
cd big-misterdeck
./install.sh        # sem root: instala para o seu usuário e inicia com a sessão
```

Precisa de Python 3.11+, `alsa-utils` (`aseqdump`), `pactl` (PipeWire ou
PulseAudio) ou `wpctl`, e `playerctl` para os botões de mídia. O `install.sh`
diz o que falta e o comando para instalar na sua distribuição.

Para remover: `./uninstall.sh` (a configuração fica; `--purge` apaga tudo).

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

[buttons.6]                # botão 6: começar a transmitir no OBS
action = "command"
run = ["obs", "--startstreaming"]

[buttons.7]
action = "volume_up"
```

| Potenciômetros | Botões |
| --- | --- |
| `volume`, `microphone`, `app_volume` (com `apps`), `none` | `play_pause`, `next`, `previous`, `stop`, `mute`, `mute_microphone`, `volume_up`, `volume_down`, `command` (com `run`), `none` |

Comandos rodam sem shell (`run` é uma lista), então nada do que chega do deck vira
um comando inventado.

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

## Licença

GPL-3.0-or-later. O MisteRdeck (hardware e modelo 3D) é de MisteR_ofcl; este
projeto só cuida do lado do Linux.
