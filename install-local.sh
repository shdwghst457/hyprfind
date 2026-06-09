#!/usr/bin/env bash
# Install HyprFind for daily use: venv, command on PATH, app launcher entry.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$ROOT/.venv"
BIN="$VENV/bin/hyprfind"
LOCAL_BIN="${HOME}/.local/bin"
DESKTOP_DIR="${HOME}/.local/share/applications"

echo "==> HyprFind local install"
echo "    Project: $ROOT"

if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 not found. On CachyOS/Arch run:"
    echo "  sudo pacman -S python python-pip python-pyqt6"
    exit 1
fi

if [[ ! -d "$VENV" ]]; then
    echo "==> Creating virtualenv"
    python3 -m venv "$VENV"
fi

echo "==> Installing package into venv"
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q -e "$ROOT"

mkdir -p "$LOCAL_BIN"
ln -sf "$BIN" "$LOCAL_BIN/hyprfind"
echo "==> Linked command: $LOCAL_BIN/hyprfind"

mkdir -p "$DESKTOP_DIR"
DESKTOP_FILE="$DESKTOP_DIR/hyprfind.desktop"
cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Name=HyprFind
Comment=Finder-quality file manager for Hyprland
Exec=${BIN}
Icon=system-file-manager
Terminal=false
Type=Application
Categories=System;FileManager;
StartupWMClass=hyprfind
EOF
echo "==> App launcher entry: $DESKTOP_FILE"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
fi

echo ""
echo "Done. You can:"
echo "  • Open your app menu and search for HyprFind"
echo "  • Or run: hyprfind"
echo ""
if [[ ":${PATH}:" != *":${LOCAL_BIN}:"* ]]; then
    echo "NOTE: ~/.local/bin is not on your PATH yet."
    echo "Add this once, then open a new terminal:"
    echo ""
    echo "  fish:"
    echo "    fish_add_path ~/.local/bin"
    echo ""
    echo "  bash/zsh:"
    echo "    echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc"
    echo ""
fi
