# HyprFind — Manual Test Plan

Use this checklist before releases or after large changes. Mark each item **Pass**, **Fail**, or **Skip** (with a note).

**Setup:** Run from a clean install when possible (`./install-local.sh` or `pip install -e .`). Test on at least one **local** path (home) and one **network** path (SMB/GVFS) if available.

**Config locations:** `~/.config/hyprfind/` (settings, bookmarks, recents, smart folders, size cache).

---

## 1. Launch & shell

| # | Test | Steps | Expected | Result |
|---|------|-------|----------|--------|
| 1.1 | App launcher | Search “HyprFind” in wofi/rofi after `install-local.sh` | Opens window, no terminal | |
| 1.2 | CLI command | Run `hyprfind` from terminal | Same window; no traceback | |
| 1.3 | Module launch | Run `python -m hyprfind` from project dir | Same behavior | |
| 1.4 | fish helper | Run `./run-hyprfind.fish` | Launches without sourcing bash `activate` | |
| 1.5 | First paint | Open app on 1080p+ display | Dark theme, sidebar + list visible, no giant icons | |
| 1.6 | Window resize | Drag window corners | Layout reflows; list fills space; no frozen panes | |
| 1.7 | Restart persistence | Resize sidebar, quit, reopen | Sidebar width restored | |
| 1.8 | View mode persistence | Switch to Icon view, quit, reopen | Icon view restored | |

---

## 2. Sidebar & favorites

| # | Test | Steps | Expected | Result |
|---|------|-------|----------|--------|
| 2.1 | Click favorite | Click Home, Documents, Downloads | Main list navigates; path bar updates | |
| 2.2 | Click Trash (empty) | Empty trash, click Trash | Empty list + “No items in Trash”; breadcrumb shows `…/Trash/files` | |
| 2.3 | Click Trash (with items) | Move file to trash, open Trash | Only trashed items shown | |
| 2.4 | Trash pinned | Try to drag Trash row | Cannot drag; stays row 0 | |
| 2.5 | Reorder favorites | Drag Anime below Downloads | Order changes visually | |
| 2.6 | Order persists | Quit and reopen after 2.5 | Same order | |
| 2.7 | Add favorite | Context menu on folder → Add to Favorites | Appears in sidebar | |
| 2.8 | Remove favorite | Right-click custom favorite → Remove | Removed; built-ins (Home etc.) cannot be removed | |
| 2.9 | Sidebar context | Right-click favorite | Open, Open in New Pane, Remove (if custom) | |
| 2.10 | Trash context | Right-click Trash | Empty Trash (disabled when empty) | |
| 2.11 | Drop on favorite | Drag file onto sidebar folder | Move/copy per modifier; highlight on row | |
| 2.12 | Section collapse | Click ▾ Favorites, then ▾ Locations | Each section collapses/expands independently; arrow flips | |
| 2.13 | Sections hug content | Observe sidebar | No large gap between Favorites and Locations; blank space is below both | |
| 2.14 | Sidebar icons | Observe favorites | Every row has an icon (house, monitor, doc, download arrow, globe for shares) — no blanks | |
| 2.15 | Long names elide | Shrink sidebar to minimum | Names elide with `…`; **no horizontal scrollbar appears** | |
| 2.16 | Sidebar width | Drag splitter between sidebar and list | Favorites and volume names not clipped; width saved on quit | |

---

## 2b. Volumes, mounting & eject

Requires a USB drive. `udisks2` must be installed (`sudo pacman -S udisks2`).
Some checks need a drive that is **not** auto-mounted — the normal case on a bare
Hyprland session.

| # | Test | Steps | Expected | Result |
|---|------|-------|----------|--------|
| 2b.1 | No noise | Open app on a btrfs CachyOS install | Locations lists the boot disk **once** — no `/home`, `/var/log`, `/var/cache`, `/srv`, `/root` duplicates | |
| 2b.2 | No pseudo-volumes | Observe Locations | No `/boot`, no `/tmp`, no `/tmp/.mount_*` AppImage rows, no zram/swap | |
| 2b.3 | System disk name | Observe first row | Named after the machine (hostname), not "ATA INTEL SSDSC2BW24" | |
| 2b.4 | System not ejectable | Hover the boot disk row | **No** eject button; right-click has no Eject | |
| 2b.5 | USB appears (unmounted) | Plug in a USB drive, wait ≤4 s | Row appears in Locations, **dimmed**, without waiting for a mount | |
| 2b.6 | Unmounted tooltip | Hover the dimmed row | Tooltip reads "click to mount (/dev/sdX1)" | |
| 2b.7 | Click to mount | Click the dimmed row | Status bar shows "Mounting …", drive mounts, list navigates into it, row un-dims | |
| 2b.8 | Eject button appears | Observe the now-mounted row | Eject glyph (triangle over a bar) shows on the right | |
| 2b.9 | Eject hover feedback | Move the pointer over the eject glyph | Glyph brightens | |
| 2b.10 | Eject click | Click the eject glyph | Drive unmounts and powers down; status bar shows "Ejected <name>"; row goes dim or disappears | |
| 2b.11 | Eject does not navigate | Click the eject glyph | The click is consumed — the pane must **not** navigate into the volume | |
| 2b.12 | Unplug detection | Physically unplug the drive | Row disappears within ~4 s without user action | |
| 2b.13 | Busy eject | `cd` into the mount in a terminal, then eject | Friendly "Eject failed: target is busy" in the status bar; no crash, no hang | |
| 2b.14 | Missing udisks2 | Temporarily rename `udisksctl` | "udisksctl not installed (install udisks2)"; app stays responsive | |
| 2b.15 | Long volume name | Attach a drive with a long label | Name elides; eject glyph never overlaps the text | |
| 2b.16 | Network share icon | Observe SMB shares | Globe/remote icon, distinct from local drive icons | |
| 2b.17 | Share disconnect | Right-click an SMB share | Menu says **Disconnect** (not Eject); action unmounts it | |
| 2b.18 | autofs dedupe | Mount `/mnt/transport` so autofs triggers | Listed **once** (not twice, once per autofs + cifs entry) | |
| 2b.19 | Volume context menu | Right-click a mounted volume | Open, Open in New Pane, Add to Favorites, Eject, Refresh Devices | |
| 2b.20 | Manual refresh | Right-click → Refresh Devices | Volume list re-reads devices immediately | |
| 2b.21 | Drop onto volume | Drag a file onto a mounted volume row | Copies/moves per modifier, with row highlight | |
| 2b.22 | Idle cost | Leave the app open and watch `top` | Device polling every 4 s is not measurably visible | |
| 2b.23 | EFI partitions hidden | Plug in a bootable USB installer (EFI + data partitions) | Only the **data** partition is listed; the 200 MB EFI partition is not | |
| 2b.24 | Windows housekeeping hidden | On a dual-boot disk, observe Locations | No "EFI system partition", no "Recovery", no "Microsoft reserved" | |
| 2b.25 | Windows data offered | Same disk | The large NTFS data partition **is** listed and mounts on click | |
| 2b.26 | Unlabelled partitions named | Observe a partition with no filesystem label | Named by size ("500.00 GB Volume"), not by the parent disk's model | |
| 2b.27 | Sibling partitions distinct | Two unlabelled partitions on one disk | Different names, not two identical rows | |

---

## 3. Navigation & path bar

| # | Test | Steps | Expected | Result |
|---|------|-------|----------|--------|
| 3.1 | Back / Forward | Navigate deep, Back, Forward | History works; toolbar buttons enable/disable correctly | |
| 3.2 | Parent | Backspace or Alt+Up or Go → Enclosing Folder | Goes to parent | |
| 3.3 | Breadcrumb click | Click middle segment in path bar | Navigates to that folder | |
| 3.4 | Path edit | Ctrl+L or double-click path bar | Text field; Enter navigates | |
| 3.5 | Invalid path | Enter `/no/such/path` in path bar | Status message; stays on valid folder | |
| 3.6 | Go menu | Go → each default favorite | Navigates | |
| 3.7 | Recent folders | Visit several folders; Go → Recent Folders | Recently visited paths listed | |
| 3.8 | Connect to server | Go → Connect to Server (smb://…) | gio mount invoked; status message | |
| 3.9 | Enter on folder | Select folder, Enter | Enters folder (does not only expand inline) | |
| 3.10 | Enter on file | Select file, Enter | Opens with xdg-open | |
| 3.11 | Double-click | Double-click folder/file | Same as Enter | |
| 3.12 | Arrow expand | → on closed folder row | Expands inline (disclosure triangle) | |
| 3.13 | Arrow collapse | ← on expanded row | Collapses | |
| 3.14 | Type-ahead | Type first letters of a filename | Selection jumps to match | |

---

## 4. List view — columns & sorting

| # | Test | Steps | Expected | Result |
|---|------|-------|----------|--------|
| 4.1 | Initial proportions | Open `~` on wide window | Name widest; Date/Size/Kind readable; no huge empty Name band | |
| 4.2 | Drag divider | Drag between Name and Date Modified | **Name** column width changes (divider you grab moves) | |
| 4.3 | Drag metadata | Widen Size column | Name shrinks to fill; no dead gap at right edge | |
| 4.4 | Window resize | Widen window after manual column sizes | Name grows; metadata columns keep user widths | |
| 4.5 | Double-click divider | Double-click header divider on Size | Column fits widest visible item | |
| 4.6 | Sort Name | Click Name header | Ascending; click again → descending; indicator shown | |
| 4.7 | Sort Date/Size/Kind | Click each header | Sort works; folders stay grouped first | |
| 4.8 | Reorder columns | Drag Kind header left of Size | Column order changes | |
| 4.9 | Date formatting | Narrow Date column by dragging | Date text shortens (Today / M/d / etc.) | |
| 4.10 | Folder sizes | Open folder with subfolders | Sizes show Calculating… then values or — on error | |
| 4.11 | Selection row | Click row | Full row highlighted | |
| 4.12 | Multi-select | Ctrl+click, Shift+click | Multiple rows selected | |
| 4.13 | Select all | Ctrl+A | All items in current folder | |

---

## 5. View modes (List / Icon / Column)

| # | Test | Steps | Expected | Result |
|---|------|-------|----------|--------|
| 5.1 | List view | View → as List | Tree list with columns | |
| 5.2 | Icon view | View → as Icons | Grid of icons; reasonable size | |
| 5.3 | Column view | View → as Columns | Miller columns; click navigates | |
| 5.4 | Switch while deep | In nested folder, switch views | Same folder content in new mode | |
| 5.5 | Icon size pref | Preferences → Icon size → OK | Icon view updates | |
| 5.6 | Filter in icon view | Ctrl+F filter text | Icon view filters too | |
| 5.7 | DnD in icon view | Drag file in icon view | Drop works (if implemented for mode) | |

---

## 6. Filter & hidden files

| # | Test | Steps | Expected | Result |
|---|------|-------|----------|--------|
| 6.1 | Filter bar | Type in toolbar Filter | List narrows to name match | |
| 6.2 | Clear filter | Clear filter field | Full list returns | |
| 6.3 | Ctrl+F | Ctrl+F | Focus filter field | |
| 6.4 | Show hidden | Ctrl+Shift+. or View menu | Dotfiles appear | |
| 6.5 | Hide hidden | Toggle off | Dotfiles hidden | |
| 6.6 | Hidden persistence | Enable hidden, quit, reopen | Still shown (if pref saved) | |
| 6.7 | Smart folder menu | Go → Smart Folders (if any in JSON) | Sets filter bar text | |

---

## 7. Quick Look (preview)

| # | Test | Steps | Expected | Result |
|---|------|-------|----------|--------|
| 7.1 | Toggle | Space on image | Overlay opens | |
| 7.2 | Toggle off | Space again on same file | Overlay closes | |
| 7.3 | Esc | Esc while preview open | Closes | |
| 7.4 | Browse preview | ←/→ with multiple files selected | Cycles preview | |
| 7.5 | Image | png/jpg | Scaled image | |
| 7.6 | Text | .txt / .py | Read-only text | |
| 7.7 | PDF | .pdf | Renders if QtPdf installed; else metadata + note | |
| 7.8 | Unknown | Binary file | Metadata panel | |
| 7.9 | Click outside | Click main window | Preview closes (event filter) | |

---

## 8. File operations — keyboard & menu

| # | Test | Steps | Expected | Result |
|---|------|-------|----------|--------|
| 8.1 | New folder | Ctrl+Shift+N | “untitled folder” created; rename if Finder-like | |
| 8.2 | New folder w/ selection | Ctrl+Alt+N with files selected | New folder containing items | |
| 8.3 | Rename | F2 on one selection | Inline rename | |
| 8.4 | Move to Trash | Delete key | Item in Trash; undo available | |
| 8.5 | Permanent delete | Shift+Delete (not in Trash) | Confirm if enabled; file gone | |
| 8.6 | Cut / Copy / Paste | Ctrl+X, Ctrl+C, Ctrl+V | File moved/copied | |
| 8.7 | Duplicate | Ctrl+D | “name copy” created | |
| 8.8 | Undo / Redo | Ctrl+Z / Ctrl+Shift+Z after trash/move/mkdir | Reverses last supported op | |
| 8.9 | Copy path | Context → Copy Path | Path on clipboard | |

---

## 9. Context menu

| # | Test | Steps | Expected | Result |
|---|------|-------|----------|--------|
| 9.1 | File menu | Right-click file | Open, Open With, Get Info, Duplicate, Copy Path, Add to Favorites, Rename, Move to Trash, Compress | |
| 9.2 | Folder menu | Right-click folder | Same + New Folder with Selection | |
| 9.3 | Open With | Open With → pick app | App launches with file | |
| 9.4 | Get Info | Get Info | Dialog with kind, size, dates, permissions, path | |
| 9.5 | Compress | Compress N Items | .zip created in current folder | |
| 9.6 | Trash menu | Right-click in Trash view | Put Back, Delete Immediately, Empty Trash | |
| 9.7 | Empty background | Right-click empty list area | New Folder | |

---

## 10. Drag and drop

| # | Test | Steps | Expected | Result |
|---|------|-------|----------|--------|
| 10.1 | Move within folder | Drag file to empty area same folder | No-op or sensible behavior | |
| 10.2 | Move to folder | Drag onto folder row | Moves; highlight on target | |
| 10.3 | Copy (modifier) | Ctrl while dropping across volumes | Copy, not move | |
| 10.4 | Force move | Shift while dropping cross-volume | Move | |
| 10.5 | Alias | Ctrl+Shift drop | Symlink created | |
| 10.6 | Spring-loaded | Hover over closed folder ~1s while dragging | Folder expands; can drop deeper | |
| 10.7 | Drop on sidebar | Drag to sidebar favorite | Transfers to that path | |
| 10.8 | Between panes | Two panes (Ctrl+Alt+T); drag file to other pane | Transfer works | |
| 10.9 | Conflict | Drop onto existing name | Conflict dialog: replace / keep both / skip | |
| 10.10 | Cancel drag | Esc during drag | No partial transfer; no crash | |

---

## 11. Trash & undo

| # | Test | Steps | Expected | Result |
|---|------|-------|----------|--------|
| 11.1 | Move to trash | Delete file | In `~/.local/share/Trash/files` + `.trashinfo` | |
| 11.2 | Put Back | Trash → Put Back | Restored to original path | |
| 11.3 | Undo trash | Ctrl+Z after delete | Restored | |
| 11.4 | Empty Trash | File → Empty Trash (with items) | Confirm; trash cleared | |
| 11.5 | Empty when empty | Empty Trash with empty bin | “Already empty” status | |
| 11.6 | Delete immediately | Trash → Delete Immediately | Permanent delete + confirm | |
| 11.7 | Trash toolbar | In Trash view | 🗑 toolbar button visible | |
| 11.8 | Breadcrumb vs list | Open empty Trash after visiting Home | List empty; **not** home contents | |

---

## 12. Multi-pane

| # | Test | Steps | Expected | Result |
|---|------|-------|----------|--------|
| 12.1 | New pane | Ctrl+Alt+T or toolbar + | Second column beside first | |
| 12.2 | Independent paths | Navigate each pane differently | Each shows its own folder | |
| 12.3 | Active pane | Click in pane B | Path bar / status follow pane B | |
| 12.4 | Close pane | Ctrl+Alt+W | Pane closes; at least one remains | |
| 12.5 | Open in new pane | Sidebar → Open in New Pane | New pane at that path | |
| 12.7 | Pane close button | Two panes open | Header × closes that pane; hidden with one pane | |
| 12.6 | Equal split | Resize panes | Both usable | |

---

## 13. Refresh & network (SMB/GVFS)

| # | Test | Steps | Expected | Result |
|---|------|-------|----------|--------|
| 13.1 | Local watching | Open `~/Documents` | Status: “Watching” (inotify) | |
| 13.2 | SMB polling | Open SMB mount | Status: “Polling” or similar | |
| 13.3 | Auto refresh local | Create file in another terminal in watched folder | Appears without manual refresh | |
| 13.4 | Auto refresh SMB | Create file on share from another machine | Appears within ~2s | |
| 13.5 | Manual refresh | F5 / Ctrl+R / ↻ | Immediate reload | |
| 13.6 | Folder sizes SMB | Browse large SMB folder | Sizes eventually fill; status may show calculating | |
| 13.7 | Size cache | Revisit folder | Sizes load faster from cache | |

---

## 14. Status bar & preferences

| # | Test | Steps | Expected | Result |
|---|------|-------|----------|--------|
| 14.1 | Item count | Select items / navigate | “N items” or “N of M selected” | |
| 14.2 | Free space | Navigate to mounted volume | Free GB shown | |
| 14.3 | Preferences hidden | File → Preferences → show hidden default | Applies after OK | |
| 14.4 | Confirm delete pref | Toggle confirm permanent delete | Shift+Delete respects setting | |

---

## 15. Stress & failure points

| # | Test | Steps | Expected | Result |
|---|------|-------|----------|--------|
| 15.1 | Permission denied | Open `/root` or unreadable dir | Graceful message; no crash | |
| 15.2 | Removed folder | Delete folder while viewing it | Navigate fails gracefully or refresh shows empty | |
| 15.3 | Rename collision | Rename to existing name | Error or conflict handling | |
| 15.4 | Paste no clipboard | Paste with empty clipboard | No-op / status | |
| 15.5 | Many files | Folder with 1000+ entries | Scroll usable; sort/filter responsive | |
| 15.6 | Deep path | Navigate 10+ levels deep | Breadcrumbs + back work | |
| 15.7 | Symlink | Open symlink file/folder | Alias kind; open target sensible | |
| 15.8 | Rapid navigation | Spam click favorites | No stale listing; no crash | |
| 15.9 | Rapid Trash toggle | Home → Trash → Home → Trash (empty) | Correct contents each time | |
| 15.10 | Column resize spam | Drag dividers quickly | No desync or negative widths | |
| 15.11 | Spring-load spam | Drag across many folders quickly | No SIGSEGV (regression test) | |
| 15.12 | Two-pane + preview | Preview open; switch panes | No focus glitches | |

---

## 16. Automated tests (CI)

Run before release:

```bash
cd hyprfind
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest tests/ -q
```

| Suite | Covers |
|-------|--------|
| `test_mounts.py` | Mount detection, subvolume/bind dedupe, network classification |
| `test_volumes.py` | Block device discovery, unmounted USB, eject eligibility |
| `test_refresh_poll.py` | Poll diff logic |
| `test_trash.py` | Move to trash, restore, empty |
| `test_file_ops.py` | Copy/move/conflict naming |
| `test_folder_size.py` | Size calculator queue |
| `test_size_cache.py` | Persistent cache |
| `test_formatting.py` | Byte/date display |

---

## 17. Visual consistency

Aesthetic regressions are easy to miss, so check these deliberately.

| # | Test | Steps | Expected | Result |
|---|------|-------|----------|--------|
| 17.1 | Size units | Compare a folder row and a file row | Both use decimal units (`KB`/`MB`), never a mix of `KB` and `KiB` | |
| 17.2 | Date uniformity | Observe the Date Modified column | Every row uses the **same** format; no row shows `5/31/2…:49 AM` elided mid-string | |
| 17.3 | Date degrades | Narrow the Date column gradually | Text steps down (relative → date+time → date → `M/d`) and never elides | |
| 17.4 | Name never crushed | Open a second pane (Ctrl+Alt+T), then a third | Name column stays readable; metadata columns yield first | |
| 17.5 | Type not elided | Observe the Type column | "Plain text document" fits without `…` | |
| 17.6 | Header captions | Narrow a column past its caption | Caption elides on the right; never clipped mid-word | |
| 17.7 | File icons present | Observe the list | Folders, text files, and XDG folders (Music, Pictures, Videos) all show icons | |
| 17.8 | Breadcrumbs | Observe the path bar | Crumbs are plain text with a dim `›`; separators have **no** button chrome | |
| 17.9 | Current crumb | Observe the last crumb | Brighter and semibold vs the ancestors | |
| 17.10 | Single-pane header | Open with one pane | **No** pane header/close button; it appears only with 2+ panes | |
| 17.11 | Active pane | Open two panes, click each | Active pane header brightens with a thin accent underline | |
| 17.12 | Status separators | Observe the status bar | Readings separated by dim `·`; **no** stray dots beside empty readings | |
| 17.13 | Selection colour | Select rows, then click the sidebar | Selection is accent blue when focused, muted blue when not — stays legible | |
| 17.14 | Disclosure arrows | Observe folder rows | Triangles are dim grey, not bright white | |
| 17.15 | Scrollbars | Scroll a long folder | Thin rounded handle, no arrow buttons at the ends | |

---

## 18. Tabs

| # | Test | Steps | Expected | Pass |
|---|------|-------|----------|------|
| 18.1 | New tab | Ctrl+T | Second tab opens at the same folder; tab bar appears | |
| 18.2 | Tab bar hidden at one tab | Close down to one tab | Tab bar disappears entirely | |
| 18.3 | Independent paths | Navigate each tab elsewhere | Each tab keeps its own folder | |
| 18.4 | Independent history | Navigate in tab A, switch to B, press Back | Back applies to B's history, not A's | |
| 18.5 | Cycle tabs | Ctrl+Tab, Ctrl+Shift+Tab | Moves forward/backward, wrapping around | |
| 18.6 | Close tab | Ctrl+W with 2+ tabs | Only that tab closes; neighbour becomes current | |
| 18.7 | Last tab kept | Ctrl+W with one tab and one pane | Nothing closes (app stays usable) | |
| 18.8 | Reorder | Drag a tab sideways | Order changes and the correct tab stays selected | |
| 18.9 | Open in new tab | Right-click a folder → Open in New Tab | Opens there without leaving the current tab | |
| 18.10 | Sidebar new tab | Right-click a favourite → Open in New Tab | Same | |
| 18.11 | Tabs + panes | Ctrl+Alt+T for a pane, then Ctrl+T | Each pane has its own independent tab set | |
| 18.12 | Background refresh | Change a background tab's folder from a terminal | Its listing is up to date when you switch to it | |

---

## 19. Search

| # | Test | Steps | Expected | Pass |
|---|------|-------|----------|------|
| 19.1 | Search this folder | Type in Search, scope "This Folder", press Enter | Matches from the folder and all subfolders | |
| 19.2 | Search home | Scope "Home", press Enter | Matches from your whole home directory | |
| 19.3 | Where column | Observe results | Shows each hit's folder, relative to Home | |
| 19.4 | Case insensitive | Search `report` | Also matches `REPORT-2025.TXT` | |
| 19.5 | Wildcards | Search `*.md` | Only `.md` files; glob is anchored at both ends | |
| 19.6 | Live results | Search a large tree | Rows appear progressively, window stays responsive | |
| 19.7 | Hidden files | Toggle Show Hidden, search again | Dotfiles included only when hidden files are shown | |
| 19.8 | Open a result | Double-click a file result | Opens with the default app | |
| 19.9 | Open a folder result | Double-click a folder result | Navigates there, leaving search | |
| 19.10 | Reveal | Right-click a result → Show in Enclosing Folder | Navigates to the parent and selects the item | |
| 19.11 | Escape | Press Esc in results | Returns to the normal listing | |
| 19.12 | No results | Search gibberish | "No results for …", not an empty silent view | |
| 19.13 | Unreadable folders | Search a tree containing a `chmod 000` folder | Skipped silently; the search still completes | |
| 19.14 | Symlink loop | Search a tree with a symlink to an ancestor | Completes rather than hanging | |
| 19.15 | Ctrl+Shift+F | Press Ctrl+Shift+F | Focuses and selects the Search field | |
| 19.16 | Filter still works | Ctrl+F, type | Filters the current folder only — unchanged behaviour | |

---

## 20. Smart folders

| # | Test | Steps | Expected | Pass |
|---|------|-------|----------|------|
| 20.1 | Save current search | Run a search, Go → Smart Folders → Save Current Search | Prompts for a name, then appears in the menu | |
| 20.2 | Run one | Click a smart folder in the menu | Runs its search and shows results | |
| 20.3 | Editor add | Go → Smart Folders → Edit, press + | New row; name field focused | |
| 20.4 | Editor edit | Change name/query/scope | List entry and summary line update live | |
| 20.5 | Pinned folder | Set a pinned folder, save, run it | Searches that folder regardless of where you are | |
| 20.6 | Scope "folder being browsed" | Save with that scope, run from two folders | Searches whichever folder is current | |
| 20.7 | Reorder | Use ↑ / ↓ | Menu order matches after saving | |
| 20.8 | Delete | Select, press − , Save | Gone from the menu | |
| 20.9 | Cancel discards | Make edits, press Cancel, reopen | Edits are gone | |
| 20.10 | Empty query dropped | Add an entry with no query, Save | Not persisted (it would match everything) | |
| 20.11 | Old config still loads | Hand-write `{"name":…,"query":…}` only | Loads and defaults to searching Home | |

---

## 21. Transfer progress

| # | Test | Steps | Expected | Pass |
|---|------|-------|----------|------|
| 21.1 | Small copy, no dialog | Copy a few small files | Completes inline; no dialog flash | |
| 21.2 | Large copy dialog | Copy a multi-GB file to `/mnt/…` | Dialog with progress bar, filename, and bytes copied | |
| 21.3 | Many files | Copy 100+ small files | Dialog appears on count alone | |
| 21.4 | UI stays live | During a large SMB copy, move the window | Window repaints; not frozen | |
| 21.5 | Cancel | Press Cancel mid-copy | Stops promptly; status says "Transfer cancelled" | |
| 21.6 | Cancelled move keeps source | Cancel a large cross-device move | Source file still present | |
| 21.7 | Cancelled cut keeps clipboard | Cut, paste, cancel | Items still ghosted and still on the clipboard | |
| 21.8 | Conflict prompt first | Paste onto existing names | Conflict dialog appears *before* progress starts | |
| 21.9 | Folder structure | Copy a nested folder | Subfolders and files all arrive; timestamps preserved | |

---

## 22. Cut ghosting

| # | Test | Steps | Expected | Pass |
|---|------|-------|----------|------|
| 22.1 | Ghost on cut | Select and Ctrl+X | Rows dim (text and icon) | |
| 22.2 | Ghost in all views | Switch to icon and column view | Same items dimmed | |
| 22.3 | Ghost across panes | Show the same folder in two panes, cut in one | Dimmed in both | |
| 22.4 | Copy clears ghost | Ctrl+X then Ctrl+C | Dimming disappears | |
| 22.5 | Paste clears ghost | Ctrl+X then Ctrl+V | Dimming disappears after the move | |
| 22.6 | Esc-free cancel | Cut, then cut something else | Only the new selection is dimmed | |

---

## 23. Group By

| # | Test | Steps | Expected | Pass |
|---|------|-------|----------|------|
| 23.1 | Group by Kind | View → Group By → Kind | Headings appear; Folders group first | |
| 23.2 | Group by Date | Group By → Date Modified | Today, Yesterday, Previous 7 Days… in that order | |
| 23.3 | Group by Size | Group By → Size | Size bands ascending; folders in their own group | |
| 23.4 | Group by Name | Group By → Name | `0–9`, then A…Z, then Other | |
| 23.5 | Sort within groups | Group by Kind, click Size header | Groups stay contiguous; items sort inside them | |
| 23.6 | Descending sort | Click the same header twice | Group order unchanged; items reverse inside groups | |
| 23.7 | Row heights | Observe a heading row | Heading band sits above the row; columns line up | |
| 23.8 | Turn off | Group By → None | Headings vanish; normal row heights return | |
| 23.9 | Persists | Set grouping, quit, reopen | Same grouping, and the menu item is checked | |

---

## 24. Tags

| # | Test | Steps | Expected | Pass |
|---|------|-------|----------|------|
| 24.1 | Add a colour tag | Right-click → Tags → Red | Red dot appears beside the name | |
| 24.2 | Multiple tags | Add Red and Blue | Two dots, in the standard colour order | |
| 24.3 | Toggle off | Click Red again | Tag and dot removed | |
| 24.4 | Multi-selection | Select 3 files, Tags → Green | All three tagged; menu shows Green checked | |
| 24.5 | Mixed selection | Tag one of three, then open Tags | Tag is unchecked (not shared by all) | |
| 24.6 | Toggle across selection | With a shared tag, click it | Removed from all of them | |
| 24.7 | Custom tag | Tags → Add Tag… → `Taxes` | Applied; listed below the colours, with no dot | |
| 24.8 | Clear | Tags → Clear Tags | All tags removed | |
| 24.9 | Interop | Tag a file, open it in Dolphin | Dolphin shows the same tag | |
| 24.10 | Unsupported filesystem | Right-click a file on the FAT32 USB | Tags menu says it is unsupported, greyed out | |
| 24.11 | Survives rename | Tag a file, rename it | Tag still present | |
| 24.12 | Long tag lists | Add 6 colour tags | At most 4 dots drawn; name still readable | |

---

## 25. Connect to Server

| # | Test | Steps | Expected | Pass |
|---|------|-------|----------|------|
| 25.1 | Bare host/share | Go → Connect to Server, enter `nas/media` with SMB selected | Treated as `smb://nas/media` | |
| 25.2 | UNC path | Enter `\\nas\media` | Protocol flips to SMB, field shows `nas/media` | |
| 25.3 | Connect button gating | Empty field | Connect disabled until an address is typed | |
| 25.4 | Guest mode | Tick "Connect as guest" | Name/Domain/Password disabled | |
| 25.5 | Successful mount | Connect to a real share | Dialog closes, sidebar reloads, pane navigates into it | |
| 25.6 | Bad host | Enter a nonexistent host | Error shown in the dialog; dialog stays open | |
| 25.7 | Wrong password | Use bad credentials | "Permission denied"-style message, not a gio prompt dump | |
| 25.8 | UI stays live | Connect to an unreachable IP | Window responsive while it times out | |
| 25.9 | Recent servers | Reopen the dialog | Previous address listed as "share on host" | |
| 25.10 | Recent reuse | Double-click a recent entry | Connects immediately | |
| 25.11 | Recent remove | Select a recent, press Remove | Gone, and still gone after reopening | |
| 25.12 | Already mounted | Connect to an already-mounted share | Treated as success and navigates there | |
| 25.13 | Protocol menu | Open the Protocol dropdown | SMB, SFTP, FTP, FTPS, NFS, AFP, WebDAV (HTTPS/HTTP) | |
| 25.14 | Domain is SMB-only | Switch protocol to SFTP | Domain row disappears; reappears on SMB | |
| 25.15 | NFS has no credentials | Choose NFS | Whole Credentials box hidden; no dead gap left behind | |
| 25.16 | Pasting a URI | Paste `sftp://host/dir` into Server | Protocol switches to SFTP, scheme stripped from the field | |
| 25.17 | `ssh://` alias | Paste `ssh://host` | Protocol becomes SFTP (gio has no ssh backend) | |
| 25.18 | Bare input respects menu | Select NFS, type `box/export` | Builds `nfs://box/export`, not SMB | |
| 25.19 | Live address preview | Type an address | Hint reads "Will connect to &lt;uri&gt;" | |
| 25.20 | Missing backend warning | On a box without `gvfs-smb`, choose SMB | Hint names the missing package before you click Connect | |
| 25.21 | Missing backend on connect | Click Connect anyway | Error names the package — never "volume doesn't implement mount" | |
| 25.22 | Installed backend is detected | With `gvfs-smb` installed, choose SMB | Hint shows the address, *not* a missing-backend warning | |
| 25.23 | WebDAV honesty | Choose WebDAV | Says it is not packaged on Arch; no invented `gvfs-dav` | |
| 25.24 | No duplicate error | Trigger a missing-backend error | Message appears once, not in both the hint and the status line | |
| 25.25 | Per-protocol packages | Choose NFS without `gvfs-nfs` | Names `gvfs-nfs`; SFTP/AFP name plain `gvfs` | |

---

## 26. Persistence

| # | Test | Steps | Expected | Pass |
|---|------|-------|----------|------|
| 26.1 | Column widths | Drag Size and Type wider, quit, reopen | Same widths | |
| 26.2 | Name still flexes | After 26.1, resize the window | Name absorbs the change; metadata keeps its widths | |
| 26.3 | Sort order | Sort by Date descending, quit, reopen | Same column and direction, indicator included | |
| 26.4 | Window geometry | Resize/move the window, quit, reopen | Same size and position | |
| 26.5 | Off-screen safety | Save geometry, then change monitor layout | Window still lands on a visible screen | |
| 26.6 | Grouping | See 23.9 | | |
| 26.7 | Corrupt settings | Hand-corrupt `settings.json`, launch | Starts with defaults instead of crashing | |

---

## Known gaps (not expected to pass yet)

Use this section to avoid filing false bugs:

- **Encrypted / LUKS volumes** — listed only once unlocked; no passphrase prompt
- **LVM and RAID members** — hidden deliberately, no assembly UI
- **Optical media burning** — eject works, burning is not implemented
- **Per-volume free space in the sidebar** — only the current folder's volume is
  reported, in the status bar
- **Content search** — search matches filenames only, not what is inside files
- **Search result count cap** — stops at 10,000 hits and says so
- **Tag sidebar section** — tags can be set and are shown as dots, but you cannot
  yet click a tag in the sidebar to list everything carrying it
- **Tags on FAT/exFAT/SMB** — those filesystems reject extended attributes, so the
  Tags menu reports that it is unsupported rather than silently failing
- **Group By in icon and column views** — list view only
- **Per-tab view mode** — the view mode and grouping are global, not per tab
- **Tab drag between panes** — tabs reorder within a pane but cannot be dragged out
- **Guest SMB connections** — "Connect as guest" sends blank credentials, which
  works on shares that allow anonymous access and fails clearly on those that do not
- **Kerberos / saved keyring credentials** — passwords are passed to `gio` per
  connection and never stored
- **WebDAV** — Arch's gvfs 1.60 ships no `gvfsd-dav` and no package provides
  it, so the protocol is listed but reports itself unavailable. It works on
  distributions that do ship the backend
- **Icon/column view polish** — basic vs Finder
- **PDF preview** — requires `PyQt6` PDF bindings (`python-pyqt6-pdf` on Arch if packaged)

---

## Bug report template

```
**HyprFind version:** 0.1.0 (git commit: …)
**OS:** CachyOS / Hyprland
**View:** List / Icon / Column
**Path:** local / SMB / GVFS — exact path if relevant

**Steps:**
1.
2.

**Expected:**

**Actual:**

**Logs:** terminal output if launched from CLI
```
