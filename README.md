# HyprFind

Finder-quality list-view file manager for Hyprland/Linux, built with PyQt6.

## Features

- Reliable directory refresh on **CIFS/SMB** mounts (polling) and local filesystems (inotify)
- Folder sizes on SMB: idle-priority background queue with persistent cache
- **Spacebar Quick Look** preview (arrow keys browse selection)
- Sidebar with favorites, Trash, and mounted volumes
- **Move to Trash** with undo; Shift+Delete for permanent delete
- Cut / Copy / Paste (cut items ghost until pasted), Duplicate, compress, Open With, Get Info
- Drag-and-drop: move, copy, alias; spring-loaded folders
- External volumes in the sidebar — USB drives appear when plugged in even with
  no auto-mount daemon, mount on click, and eject from the row
- **Tabs** (Ctrl+T) and side-by-side **panes** (Ctrl+Alt+T), list/icon/column views
- **Recursive search** (Ctrl+Shift+F) on a background thread, with a results
  view showing where each hit lives; supports `*` and `?` wildcards
- **Smart folders** — saved searches with a full editor, reorderable and rerunnable
- **Connect to Server** for SMB/SFTP/FTP/NFS/AFP, with credentials and a
  recent-servers list. Enter a bare SMB host and it lists the server's shares
  to pick from, greying out the ones already mounted
- **Group By** kind, date modified, size, or name, with headings in the list
- **Tags** written to `user.xdg.tags`, so Dolphin and Nautilus see them too;
  colour dots appear beside filenames
- Progress dialog with a working **Cancel** for large copies and moves
- Column widths, sort order, grouping, and window geometry persist across sessions
- Breadcrumb path bar, in-folder filter (Ctrl+F), Go menu + recents
- Dark theme suited to Hyprland

## Install (normal app — app menu + `hyprfind` command)

On CachyOS / Arch, once:

```bash
git clone https://github.com/shdwghst457/hyprfind.git
cd hyprfind
./install-local.sh
```

The script installs the system packages it needs (via `pacman`, asking for sudo
only when something is actually missing), builds a venv, puts `hyprfind` on
`~/.local/bin`, and registers **HyprFind** in your app launcher (wofi/rofi/etc.).
It finishes by checking that each runtime tool is really present and naming
anything that is not. Re-running it is safe.

| Flag | Effect |
|------|--------|
| `--no-deps` | Skip system packages entirely |
| `--minimal` | Skip the optional network-share packages (gvfs) |
| `--dev` | Also install test dependencies (pytest) |
| `-y`, `--yes` | Don't prompt (`pacman --noconfirm`) |

On a distro without `pacman` the script skips installation and prints the
package list for you to translate.

### What it installs, and why

| Package | Needed for |
|---------|-----------|
| `glib2` | the `gio` command, used for network shares. There is no package called `gio` |
| `udisks2` | `udisksctl`, to mount and eject USB drives without root |
| `util-linux` | `lsblk`, to discover attached drives |
| `xdg-user-dirs` | locating Documents / Downloads / etc. |
| `xdg-utils` | `xdg-open`, to open files in their default app |
| `breeze-icons` | an icon theme |
| `gvfs`, `gvfs-smb`, `gvfs-nfs` | **Connect to Server**; optional |

Only SMB and NFS have their own packages. The SFTP, FTP, FTPS and AFP backends
all ship inside base `gvfs`, so there is no `gvfs-sftp` or `gvfs-afp` to add.
WebDAV has no official Arch package at all, and HyprFind says so rather than
naming a package that does not exist.

Three of those matter more than they look:

- **`udisks2`** — a bare Hyprland session runs no auto-mount daemon, so
  HyprFind lists attached drives itself and mounts them when you click. Without
  udisks2 you can still browse drives that are already mounted, but clicking an
  unmounted one reports that udisksctl is missing.
- **`breeze-icons`** — Hyprland sets no desktop environment, so Qt finds no icon
  theme on its own and the sidebar and file list render without icons. HyprFind
  points Qt at the system theme directories and prefers `breeze-dark`, falling
  back to `Adwaita` then `hicolor`.
- **`gvfs` / `gvfs-smb`** — without a backend, `gio` refuses every mount with
  the unhelpful "volume doesn't implement mount". HyprFind detects this and
  names the missing package instead, but it still cannot mount anything until
  the backend is installed. After installing, log out and back in so the
  session picks up the gvfs daemon.

PyQt6 is deliberately not in that list: the venv is isolated from system
site-packages, so Qt comes from the pip wheel rather than `python-pyqt6`.

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

## Deploying changes

`install-local.sh` uses an **editable** install (`pip install -e`), so the
`hyprfind` command runs straight from this working tree. Editing the source is
all it takes — just relaunch the app.

Re-run `./install-local.sh` only when something outside the Python source
changes:

- a new dependency in `pyproject.toml`
- a change to the `[project.scripts]` entry point
- the `.desktop` launcher entry or the project's location on disk

### Updating another machine

On a machine that already has a clone (the hyprbook), pulling is the whole
deploy step — the editable install picks the new code up on next launch:

```bash
cd ~/hyprfind
git pull
```

On a machine that has never had it, follow the Install section above. Note that
`.venv/` is gitignored, so each machine builds its own via `install-local.sh`.

To check what is currently wired up:

```bash
readlink -f ~/.local/bin/hyprfind   # should point into ./.venv/bin
.venv/bin/python -c "import hyprfind; print(hyprfind.__file__)"
```

Run the tests with:

```bash
.venv/bin/python -m pytest -q
```

On a fresh clone, get the test dependencies with `./install-local.sh --dev`, or
directly:

```bash
.venv/bin/pip install -e ".[dev]"
```

## Keyboard shortcuts

| Key | Action |
|-----|--------|
| ↑/↓ | Move selection |
| → / ← | Expand / collapse folder |
| Return | Rename (extension stays unselected) |
| F2 | Rename |
| Alt+↓ or Ctrl+O | Open file or enter folder |
| Delete | Move to Trash |
| Shift+Delete | Delete permanently |
| Backspace | Go to parent directory |
| Space | Toggle Quick Look (←/→ browse) |
| Ctrl+Z / Ctrl+Shift+Z | Undo / Redo |
| Ctrl+C / Ctrl+X / Ctrl+V | Copy / Cut / Paste |
| Ctrl+D | Duplicate |
| Ctrl+F | Filter current folder |
| Ctrl+Shift+F | Recursive search |
| Esc | Leave search results (or close Quick Look) |
| Ctrl+Shift+N | New folder |
| Ctrl+Alt+N | New folder with selection |
| Ctrl+Shift+. | Show/hide hidden files |
| Ctrl+T | New tab |
| Ctrl+W | Close tab |
| Ctrl+Tab / Ctrl+Shift+Tab | Next / previous tab |
| Ctrl+Alt+T | New side-by-side pane |
| Ctrl+Alt+W | Close pane |
| Ctrl+L | Edit path (double-click breadcrumbs) |
| Ctrl+R / F5 | Force refresh |

## License

GPL-3.0-or-later
# hyprfind
# hyprfind
# hyprfind
# hyprfind
