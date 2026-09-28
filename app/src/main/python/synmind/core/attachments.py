"""Path resolution for node attachments.

Each map keeps `attachments_folder` (str | None) on the MindMap:
    - None  → default: `<mapname>_files` next to the .smmap
    - relative path → resolved against the .smmap's parent directory
    - absolute path → used as-is

`folder_for_storage(picked, map_path)` decides whether a folder picked
via QFileDialog should be stored relative (when it lives inside the map
file's parent dir tree, so the pair travels well via Dropbox / git) or
absolute (when it sits anywhere else).
"""
from __future__ import annotations

import os
from pathlib import Path


def default_folder_name(map_path: str | os.PathLike) -> str:
    """Default attachments folder name: `<map basename>_files`."""
    return f"{Path(map_path).stem}_files"


def resolve_dir(
    attachments_folder: str | None, map_path: str | os.PathLike | None
) -> Path | None:
    """Resolve the absolute path of the attachment folder for a given map.

    Returns None when the map has no on-disk path yet (a brand-new
    untitled map) — callers should surface a "save the map first"
    message rather than guessing a location.
    """
    if map_path is None:
        return None
    map_path = Path(map_path)
    map_dir = map_path.parent
    if not attachments_folder:
        return map_dir / default_folder_name(map_path)
    p = Path(attachments_folder)
    if p.is_absolute():
        return p
    return (map_dir / p).resolve()


def folder_for_storage(picked: str | os.PathLike, map_path: str | os.PathLike) -> str:
    """Decide how to store a user-picked folder in `attachments_folder`.

    If `picked` is inside the map file's parent directory (or one of its
    descendants), store as a relative path so the map+folder pair stays
    portable when synced together. Otherwise store the absolute path.
    """
    picked_abs = Path(picked).resolve()
    map_dir = Path(map_path).resolve().parent
    try:
        rel = picked_abs.relative_to(map_dir)
        return str(rel).replace("\\", "/")
    except ValueError:
        # `picked` is outside map_dir's tree — keep as absolute.
        return str(picked_abs)
