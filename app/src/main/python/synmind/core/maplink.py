"""Saveable mind-map view links.

A `.smlink` file is a small JSON document that points at a `.smmap` and
captures the view state (selected node, zoom, scroll, focus subtree,
layout/line style, collapse state) at the moment the link was created.
Double-clicking the `.smlink` reopens the map with that exact view.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LINK_VERSION = 1
LINK_EXT = ".smlink"


@dataclass
class MapViewLink:
    map_path: str
    selected_id: str | None = None
    focus_id: str | None = None
    view_scale: float = 1.0
    view_center_x: float | None = None
    view_center_y: float | None = None
    layout_style: str = "tidy_branched"
    line_style: str = "curved"
    line_thickness: float = 2.0
    collapsed_ids: list[str] = field(default_factory=list)
    created_at: str = ""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def save_link(link: MapViewLink, path: str | Path) -> None:
    if not link.created_at:
        link.created_at = _now_iso()
    payload: dict[str, Any] = {
        "version": LINK_VERSION,
        "type": "synmind-view-link",
        **asdict(link),
    }
    Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_link(path: str | Path) -> MapViewLink:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("type") != "synmind-view-link":
        raise ValueError("Not a synmind view link file.")
    version = data.get("version", 1)
    if version > LINK_VERSION:
        raise ValueError(
            f"Link version {version} is newer than this app supports "
            f"(max {LINK_VERSION})."
        )
    map_path = data.get("map_path")
    if not map_path:
        raise ValueError("Link is missing 'map_path'.")
    return MapViewLink(
        map_path=map_path,
        selected_id=data.get("selected_id"),
        focus_id=data.get("focus_id"),
        view_scale=float(data.get("view_scale", 1.0) or 1.0),
        view_center_x=(
            float(data["view_center_x"])
            if data.get("view_center_x") is not None
            else None
        ),
        view_center_y=(
            float(data["view_center_y"])
            if data.get("view_center_y") is not None
            else None
        ),
        layout_style=data.get("layout_style", "tidy_branched"),
        line_style=data.get("line_style", "curved"),
        line_thickness=float(data.get("line_thickness", 2.0) or 2.0),
        collapsed_ids=list(data.get("collapsed_ids") or []),
        created_at=data.get("created_at", ""),
    )
