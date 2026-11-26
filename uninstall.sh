#!/bin/bash
# Remove o Big MisteRdeck do seu usuário. A configuração fica; --purge também a apaga.
set -euo pipefail
if command -v systemctl >/dev/null && systemctl --user show-environment >/dev/null 2>&1; then
    systemctl --user disable --now big-misterdeck.service 2>/dev/null || true
fi
rm -f "${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/big-misterdeck.service" "$HOME/.local/bin/big-misterdeck"
rm -rf "${XDG_DATA_HOME:-$HOME/.local/share}/big-misterdeck"
command -v systemctl >/dev/null && systemctl --user daemon-reload 2>/dev/null || true
if [ "${1:-}" = "--purge" ]; then
    rm -rf "${XDG_CONFIG_HOME:-$HOME/.config}/big-misterdeck"
fi
echo "Big MisteRdeck removido."
