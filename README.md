# HyprFind

Finder-quality list-view file manager for Hyprland/Linux, built with PyQt6.

## Features

- Reliable directory refresh on **CIFS/SMB** mounts (polling) and local filesystems (inotify)
- Folder sizes on SMB: idle-priority background queue with persistent cache
- **Spacebar Quick Look** preview (arrow keys browse selection)
- Sidebar with favorites, Trash, and mounted volumes
- **Move to Trash** with undo; Shift+Delete for permanent delete
- Cut / Copy / Paste, Duplicate, compress, Open With, Get Info
- Drag-and-drop: move, copy, alias; spring-loaded folders
- Multi-pane browsing (Ctrl+T), list/icon/column views
- Breadcrumb path bar, in-folder filter (Ctrl+F), Go menu + recents
- Dark theme suited to Hyprland

## Install (normal app — app menu + `hyprfind` command)

On CachyOS / Arch, once:

```bash
sudo pacman -S python python-pip python-pyqt6 gio xdg-user-dirs
git clone https://github.com/YOUR_USER/hyprfind.git
cd hyprfind
chmod +x install-local.sh
./install-local.sh
```

That script: installs into a venv, puts `hyprfind` on `~/.local/bin`, and registers **HyprFind** in your app launcher (wofi/rofi/etc.).

If a new terminal says `hyprfind: command not found`, add `~/.local/bin` to PATH once:

```fish
fish_add_path ~/.local/bin
```

Same steps on your hyprbook after `git clone`.

## Run (development)

```bash
./run-hyprfind.fish          # fish, no PATH setup needed
.venv/bin/python -m hyprfind # direct
```

## Keyboard shortcuts

| Key | Action |
|-----|--------|
| ↑/↓ | Move selection |
| → / ← | Expand / collapse folder |
| Enter | Open file or enter folder |
| F2 | Rename |
| Delete | Move to Trash |
| Shift+Delete | Delete permanently |
| Backspace | Go to parent directory |
| Space | Toggle Quick Look (←/→ browse) |
| Ctrl+Z / Ctrl+Shift+Z | Undo / Redo |
| Ctrl+C / Ctrl+X / Ctrl+V | Copy / Cut / Paste |
| Ctrl+D | Duplicate |
| Ctrl+F | Filter current folder |
| Ctrl+Shift+N | New folder |
| Ctrl+Alt+N | New folder with selection |
| Ctrl+Shift+. | Show/hide hidden files |
| Ctrl+T | New side-by-side pane |
| Ctrl+L | Edit path (double-click breadcrumbs) |
| Ctrl+R / F5 | Force refresh |

## License

GPL-3.0-or-later
# hyprfind
# hyprfind
# hyprfind
# hyprfind
