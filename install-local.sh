#!/usr/bin/env bash
# Install HyprFind for daily use: system packages, venv, command on PATH,
# app launcher entry.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$ROOT/.venv"
BIN="$VENV/bin/hyprfind"
LOCAL_BIN="${HOME}/.local/bin"
DESKTOP_DIR="${HOME}/.local/share/applications"

INSTALL_DEPS=1
INSTALL_NETWORK=1
INSTALL_DEV=0
ASSUME_YES=0

usage() {
    cat <<'USAGE'
Usage: ./install-local.sh [options]

Installs HyprFind: system dependencies, a virtualenv, the `hyprfind`
command on your PATH, and an app launcher entry.

Options:
  --no-deps      Skip system package installation entirely
  --minimal      Skip the optional network-share packages (gvfs)
  --dev          Also install test dependencies (pytest)
  -y, --yes      Do not prompt for confirmation (pacman --noconfirm)
  -h, --help     Show this help

Re-running is safe; already-installed packages are left alone.
USAGE
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-deps) INSTALL_DEPS=0 ;;
        --minimal) INSTALL_NETWORK=0 ;;
        --dev) INSTALL_DEV=1 ;;
        -y|--yes) ASSUME_YES=1 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

echo "==> HyprFind local install"
echo "    Project: $ROOT"

# ---------------------------------------------------------------- system deps
#
# Packages HyprFind needs at runtime. PyQt6 deliberately is not here: the venv
# is isolated from system site-packages, so Qt comes from the pip wheel.
#
#   glib2          gio, for network shares
#   udisks2        udisksctl, to mount and eject USB drives without root
#   xdg-user-dirs  xdg-user-dir, to locate Documents/Downloads/etc.
#   xdg-utils      xdg-open, to open files in their default application
#   util-linux     lsblk, to discover attached drives
#   breeze-icons   an icon theme; a bare Hyprland session provides none
REQUIRED_PKGS=(python python-pip glib2 udisks2 xdg-user-dirs xdg-utils util-linux breeze-icons)

# Needed only for Connect to Server. Without a backend, gio reports the
# confusing "volume doesn't implement mount".
NETWORK_PKGS=(gvfs gvfs-smb gvfs-nfs)

# Binaries to verify afterwards, as "binary:package".
REQUIRED_BINS=(gio:glib2 udisksctl:udisks2 xdg-user-dir:xdg-user-dirs lsblk:util-linux)

install_pacman_packages() {
    local wanted=("$@")
    local missing=()
    local pkg
    for pkg in "${wanted[@]}"; do
        if ! pacman -Qq "$pkg" >/dev/null 2>&1; then
            missing+=("$pkg")
        fi
    done

    if [[ ${#missing[@]} -eq 0 ]]; then
        echo "    all present"
        return 0
    fi

    echo "    missing: ${missing[*]}"
    local -a pacman_cmd=(pacman -S --needed)
    [[ $ASSUME_YES -eq 1 ]] && pacman_cmd+=(--noconfirm)
    if [[ $EUID -ne 0 ]]; then
        if ! command -v sudo >/dev/null 2>&1; then
            echo "    WARNING: sudo not found; install manually:" >&2
            echo "      pacman -S --needed ${missing[*]}" >&2
            return 1
        fi
        pacman_cmd=(sudo "${pacman_cmd[@]}")
    fi
    "${pacman_cmd[@]}" "${missing[@]}"
}

if [[ $INSTALL_DEPS -eq 1 ]]; then
    if command -v pacman >/dev/null 2>&1; then
        echo "==> System packages"
        install_pacman_packages "${REQUIRED_PKGS[@]}" || true
        if [[ $INSTALL_NETWORK -eq 1 ]]; then
            echo "==> Network share packages (skip with --minimal)"
            install_pacman_packages "${NETWORK_PKGS[@]}" || true
        fi
    else
        echo "==> Not an Arch-based system; skipping package installation."
        echo "    Install the equivalents of these yourself:"
        echo "      ${REQUIRED_PKGS[*]}"
        [[ $INSTALL_NETWORK -eq 1 ]] && echo "      ${NETWORK_PKGS[*]}"
    fi
else
    echo "==> Skipping system packages (--no-deps)"
fi

if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 not found. On CachyOS/Arch run:" >&2
    echo "  sudo pacman -S python python-pip" >&2
    exit 1
fi

# ---------------------------------------------------------------------- python

if [[ ! -d "$VENV" ]]; then
    echo "==> Creating virtualenv"
    python3 -m venv "$VENV"
fi

echo "==> Installing package into venv"
"$VENV/bin/pip" install -q --upgrade pip
if [[ $INSTALL_DEV -eq 1 ]]; then
    "$VENV/bin/pip" install -q -e "$ROOT[dev]"
else
    "$VENV/bin/pip" install -q -e "$ROOT"
fi

# ------------------------------------------------------------------ launchers

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

# ---------------------------------------------------------------- verification

echo "==> Checking runtime tools"
WARNED=0
for entry in "${REQUIRED_BINS[@]}"; do
    bin="${entry%%:*}"
    pkg="${entry##*:}"
    if ! command -v "$bin" >/dev/null 2>&1; then
        echo "    MISSING $bin — install $pkg (some features will be disabled)"
        WARNED=1
    fi
done

# gio needs a backend per protocol, not just the binary.
if [[ $INSTALL_NETWORK -eq 1 ]] && ! ls /usr/lib/gvfs /usr/libexec/gvfs >/dev/null 2>&1; then
    echo "    MISSING gvfs backends — Connect to Server will not work"
    WARNED=1
fi
[[ $WARNED -eq 0 ]] && echo "    all present"

echo ""
echo "Done. You can:"
echo "  • Open your app menu and search for HyprFind"
echo "  • Or run: hyprfind"
echo ""
echo "This is an editable install, so future code changes need only a relaunch."
if [[ ":${PATH}:" != *":${LOCAL_BIN}:"* ]]; then
    echo ""
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
