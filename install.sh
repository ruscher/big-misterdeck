#!/bin/bash
# Instala o Big MisteRdeck para o seu usuário (sem root):
#   ~/.local/share/big-misterdeck   programa
#   ~/.local/bin/big-misterdeck     comando
#   ~/.config/systemd/user          serviço que inicia com a sessão
set -euo pipefail
cd "$(dirname "$0")"

missing=()
for tool in python3 aseqdump; do command -v "$tool" >/dev/null || missing+=("$tool"); done
command -v pactl >/dev/null || command -v wpctl >/dev/null || missing+=("pactl ou wpctl")
if [ ${#missing[@]} -gt 0 ]; then
    echo "Faltam: ${missing[*]}" >&2
    echo "Arch/BigLinux/Manjaro: sudo pacman -S --needed python alsa-utils libpulse playerctl" >&2
    echo "Debian/Ubuntu:         sudo apt install python3 alsa-utils pulseaudio-utils playerctl" >&2
    echo "Fedora:                sudo dnf install python3 alsa-utils pulseaudio-utils playerctl" >&2
    exit 1
fi
python3 -c 'import tomllib' 2>/dev/null || { echo "Precisa do Python 3.11 ou mais novo." >&2; exit 1; }
command -v playerctl >/dev/null || echo "Aviso: sem playerctl os botões de mídia não fazem nada."

share="${XDG_DATA_HOME:-$HOME/.local/share}/big-misterdeck"
bin="$HOME/.local/bin"
units="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$share" "$bin" "$units"
rm -rf "$share/bigmisterdeck"
cp -r bigmisterdeck "$share/"
find "$share" -name __pycache__ -prune -exec rm -rf {} +
install -m 755 big-misterdeck "$bin/big-misterdeck"
install -m 644 data/big-misterdeck.service "$units/big-misterdeck.service"

"$bin/big-misterdeck" --check || true
if command -v systemctl >/dev/null && systemctl --user show-environment >/dev/null 2>&1; then
    systemctl --user daemon-reload
    systemctl --user enable big-misterdeck.service
    systemctl --user restart big-misterdeck.service
    echo "Serviço ativo: systemctl --user status big-misterdeck"
else
    echo "Sem systemd de usuário: rode \"big-misterdeck\" na sua sessão."
fi
echo "Configuração: big-misterdeck --write-config (cria ~/.config/big-misterdeck/config.toml)"
