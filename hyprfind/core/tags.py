"""File tags stored in the ``user.xdg.tags`` extended attribute.

This is the same key Dolphin and Nautilus use, so tags set here show up there
too. Extended attributes are not universally supported — FAT, exFAT and most
SMB mounts reject them — so every write reports whether it landed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

XATTR_TAGS = "user.xdg.tags"

# Finder's colour set, which is also what the freedesktop tag convention uses
# for coloured labels. Hex values follow the macOS dark-mode label palette.
TAG_COLORS = {
    "Red": "#ff5f57",
    "Orange": "#ff9f0a",
    "Yellow": "#ffd60a",
    "Green": "#32d74b",
    "Blue": "#0a84ff",
    "Purple": "#bf5af2",
    "Grey": "#98989d",
}

STANDARD_TAGS = tuple(TAG_COLORS)


@dataclass(frozen=True)
class TagWriteResult:
    ok: bool
    error: str = ""


def _decode(raw: bytes) -> list[str]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return []
    return _split(text)


def _split(text: str) -> list[str]:
    """Tags are comma-separated; drop blanks and duplicates, keep order."""
    seen: dict[str, None] = {}
    for part in text.split(","):
        tag = part.strip()
        if tag:
            seen.setdefault(tag, None)
    return list(seen)


def read_tags(path: str) -> list[str]:
    """Tags on `path`, or an empty list if there are none or it is unreadable."""
    try:
        raw = os.getxattr(path, XATTR_TAGS, follow_symlinks=True)
    except OSError:
        # No attribute, no xattr support, or no permission — all mean "no tags".
        return []
    return _decode(raw)


def supports_tags(path: str) -> bool:
    """Whether the filesystem holding `path` accepts user extended attributes.

    Probed by listing rather than writing, so it never modifies the file.
    """
    try:
        os.listxattr(path, follow_symlinks=True)
    except OSError:
        return False
    return True


def write_tags(path: str, tags: list[str]) -> TagWriteResult:
    """Replace the tag set on `path`. Removing all tags removes the attribute."""
    cleaned = _split(",".join(tags))
    try:
        if not cleaned:
            try:
                os.removexattr(path, XATTR_TAGS, follow_symlinks=True)
            except OSError as exc:
                # Nothing to remove is success, not failure.
                if getattr(exc, "errno", None) not in (61, 93, 95, 2):
                    raise
            return TagWriteResult(True)
        os.setxattr(
            path,
            XATTR_TAGS,
            ",".join(cleaned).encode("utf-8"),
            follow_symlinks=True,
        )
    except OSError as exc:
        return TagWriteResult(False, _explain(exc, path))
    return TagWriteResult(True)


def add_tag(path: str, tag: str) -> TagWriteResult:
    tag = tag.strip()
    if not tag:
        return TagWriteResult(True)
    current = read_tags(path)
    if tag in current:
        return TagWriteResult(True)
    return write_tags(path, current + [tag])


def remove_tag(path: str, tag: str) -> TagWriteResult:
    current = read_tags(path)
    if tag not in current:
        return TagWriteResult(True)
    return write_tags(path, [t for t in current if t != tag])


def toggle_tag(path: str, tag: str) -> TagWriteResult:
    return remove_tag(path, tag) if tag in read_tags(path) else add_tag(path, tag)


def _explain(exc: OSError, path: str) -> str:
    errno = getattr(exc, "errno", None)
    if errno == 95:  # EOPNOTSUPP
        return f"{os.path.basename(path)}: this filesystem does not support tags"
    if errno == 13:
        return f"{os.path.basename(path)}: permission denied"
    if errno == 28:
        return f"{os.path.basename(path)}: no space left for attributes"
    return f"{os.path.basename(path)}: {exc.strerror or exc}"


def color_for(tag: str) -> str | None:
    """Swatch colour for a standard tag name, or None for a custom tag."""
    return TAG_COLORS.get(tag.capitalize()) or TAG_COLORS.get(tag)


def common_tags(paths: list[str]) -> list[str]:
    """Tags present on every path, for showing a multi-selection's state."""
    if not paths:
        return []
    shared = set(read_tags(paths[0]))
    for path in paths[1:]:
        shared &= set(read_tags(path))
        if not shared:
            break
    # Standard order first, then any custom tags alphabetically.
    ordered = [t for t in STANDARD_TAGS if t in shared]
    ordered += sorted(t for t in shared if t not in TAG_COLORS)
    return ordered


def all_tags(paths: list[str]) -> list[str]:
    """Every tag appearing on any path."""
    found: set[str] = set()
    for path in paths:
        found.update(read_tags(path))
    ordered = [t for t in STANDARD_TAGS if t in found]
    ordered += sorted(t for t in found if t not in TAG_COLORS)
    return ordered
