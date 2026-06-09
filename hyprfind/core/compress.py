"""Compress files into zip archives."""

from __future__ import annotations

import os
import zipfile
from pathlib import Path


def compress_items(sources: list[str], destination_dir: str) -> tuple[str | None, str | None]:
    """Create a zip of sources in destination_dir. Returns (archive_path, error)."""
    if not sources:
        return None, "Nothing selected"
    destination_dir = os.path.abspath(destination_dir)
    if len(sources) == 1:
        base = os.path.basename(sources[0].rstrip(os.sep))
        name = base + ".zip" if not base.endswith(".zip") else base + ".zip"
    else:
        name = "Archive.zip"
    archive = os.path.join(destination_dir, name)
    index = 2
    while os.path.exists(archive):
        archive = os.path.join(destination_dir, f"Archive {index}.zip")
        index += 1
    try:
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            for source in sources:
                source = os.path.abspath(source)
                if os.path.isfile(source):
                    zf.write(source, os.path.basename(source))
                elif os.path.isdir(source):
                    base_name = os.path.basename(source.rstrip(os.sep))
                    for root, _dirs, files in os.walk(source):
                        for fname in files:
                            full = os.path.join(root, fname)
                            arcname = os.path.join(
                                base_name,
                                os.path.relpath(full, source),
                            )
                            zf.write(full, arcname)
    except OSError as exc:
        return None, str(exc)
    return archive, None
