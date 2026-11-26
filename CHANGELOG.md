# Changelog

## [0.3.0] — 2026-11-26

- Botões controlam o OBS direto, pela mesma conexão dos potenciômetros, sem
  obs-cmd e sem repetir a senha: `obs_scene` (`scene = "..."`), `obs_mute`
  (`source = "..."`), `obs_record`, `obs_record_pause`, `obs_stream`,
  `obs_virtual_camera` e `obs_replay_save`.
- Um botão do OBS tenta conectar na hora em que é apertado, mesmo logo depois de
  o OBS abrir.
- `--check` confere também o nome de cada cena.

## [0.2.0] — 2026-11-26

- Potenciômetros podem regular o volume de uma fonte de áudio do OBS Studio
  (`action = "obs_volume"`, `source = "..."`), pelo WebSocket que já vem no OBS 28+,
  na mesma escala do controle do mixer. Uma conexão só, sem programas extras; com o
  OBS fechado, o resto do deck continua funcionando e ele reconecta sozinho.
- `--check` confere a conexão com o OBS e o nome de cada fonte.
- Exemplos de botões para o OBS com o `obs-cmd`; o exemplo `obs --startstreaming`
  saiu, porque abria um segundo OBS em vez de comandar o que estava aberto.

## [0.1.0] — 2026-11-26

Primeira versão.

- 4 potenciômetros: volume geral, microfone e volume por programa (Spotify, navegador…).
- 12 botões: tocar/pausar, anterior, próxima, mudo, mudo do microfone, volume ±
  e comandos próprios.
- Lê o MIDI pelo sequenciador do ALSA: o OBS e outros programas continuam
  recebendo o deck ao mesmo tempo.
- Volta sozinho quando o deck é desconectado e ligado de novo.
- Serviço de usuário do systemd; instalação sem root.
