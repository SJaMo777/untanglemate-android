"""Android-only glue between Kotlin and synmind/core/.

Deliberately NOT part of core/ — this is the Android equivalent of what
synmind/ui/ is on Windows: a platform layer sitting on top of the shared,
unmodified core logic. Nothing in here should ever be needed by, or
copied into, the Windows app.

Returns plain JSON strings rather than raw Node objects because walking
a PyObject tree attribute-by-attribute from Kotlin (one Chaquopy call per
field per node) is chatty and slow for anything but a tiny map; one JSON
string crossing the bridge is a single call regardless of map size.

Layout is a TWO-STEP handshake, not one call, because good positions need
REAL text measurements and only Kotlin/Compose can measure text — the
same reason Windows's own canvas feeds real font-metric sizes into
`mind_map._layout_measured_sizes` (see layout.py's own comment on it)
rather than trusting its pure-Python, no-font-metrics width estimate.
Skipping this step and trusting the bare estimate is exactly what caused
visible box overlap on a wider real map during testing — the estimate
runs low for ordinary Latin text by design (layout.py's own words), and
Android's rendered font/padding never matches it closely enough to skip
this step and still look right:
    1. `open_map_structure(path)` / `new_map_structure()` — loads/creates
       the map (kept as module state in `_current`) and returns text/
       children only, x/y always 0.0 (not laid out yet).
    2. Kotlin measures each node's actual on-screen box size and calls
       `apply_measured_layout(sizes_json)` with `{node_id: [w, h]}`,
       which feeds those into `_current._layout_measured_sizes`, runs
       the real `layout.apply_layout`, and returns the full tree with
       real x/y this time.
"""
from __future__ import annotations

import json

from synmind.core import document, layout
from synmind.core.commands import EditTextCommand
from synmind.core.history import History
from synmind.core.model import MindMap, Node

_current: MindMap | None = None
_history: History | None = None


def _node_to_dict(node: Node) -> dict:
    return {
        "id": node.id,
        "text": node.text,
        "collapsed": node.collapsed,
        "x": node.x,
        "y": node.y,
        "children": [_node_to_dict(c) for c in node.children],
    }


def _map_to_json(mind_map: MindMap) -> str:
    return json.dumps({
        "title": mind_map.title,
        "root": _node_to_dict(mind_map.root),
    })


def new_map_structure() -> str:
    """A fresh, empty map — what the app shows before anything is opened.
    Not laid out yet; call apply_measured_layout() next."""
    global _current, _history
    _current = MindMap()
    _history = History(_current)
    return _map_to_json(_current)


def open_map_structure(path: str) -> str:
    """Load a real .smmap file (already copied to a local path — Chaquopy/
    core.document need a real filesystem path, not a content:// URI).
    Not laid out yet; call apply_measured_layout() next."""
    global _current, _history
    _current = document.load(path)
    _history = History(_current)
    return _map_to_json(_current)


def apply_measured_layout(sizes_json: str) -> str:
    """sizes_json: {node_id: [width, height], ...} from Kotlin's actual
    Compose text measurement (box size, padding included — the real
    on-screen footprint, not just the bare text glyphs) for every node
    returned by the most recent *_structure() call. Runs the real
    `core.layout.apply_layout` (mind_map.layout_style, "tidy_branched" by
    default) with those as the authoritative sizes and returns the same
    shape as *_structure() but with real x/y this time."""
    if _current is None:
        raise RuntimeError(
            "apply_measured_layout called before new_map_structure/"
            "open_map_structure")
    sizes = json.loads(sizes_json)
    _current._layout_measured_sizes = {
        node_id: (float(wh[0]), float(wh[1])) for node_id, wh in sizes.items()
    }
    layout.apply_layout(_current)
    return _map_to_json(_current)


def _require_history() -> History:
    if _current is None or _history is None:
        raise RuntimeError(
            "rename_node/undo/redo called before new_map_structure/"
            "open_map_structure")
    return _history


def rename_node(node_id: str, new_text: str) -> str:
    """Renames through the real EditTextCommand/History (undo-capable,
    updates node.updated_at) rather than mutating node.text directly —
    the same path Windows's own rename goes through. Returns the
    structure shape again (x/y stale from the old text's size); caller
    must re-measure and call apply_measured_layout, same as after
    *_structure()."""
    history = _require_history()
    node = _current.find(node_id)
    if node is None:
        raise ValueError("No such node: %s" % node_id)
    history.execute(EditTextCommand(
        node_id=node_id, old_text=node.text, new_text=new_text))
    return _map_to_json(_current)


def undo() -> str:
    _require_history().undo()
    return _map_to_json(_current)


def redo() -> str:
    _require_history().redo()
    return _map_to_json(_current)


def can_undo() -> bool:
    return _require_history().can_undo()


def can_redo() -> bool:
    return _require_history().can_redo()


def save_map(path: str) -> None:
    """Writes the current map to a real filesystem path in the same
    Fernet-encrypted format Windows reads/writes (core.file_format,
    unmodified). Caller is responsible for getting those bytes to their
    real destination — a content:// URI (SAF) can't be written directly
    from core.document.save(), which does its own Path(path).write_bytes()."""
    if _current is None:
        raise RuntimeError("save_map called before a map was loaded/created")
    # write_history=False: the node-history sidecar Windows writes
    # alongside a save has nowhere to go from here (we only copy the
    # single .smmap file's bytes back to a content:// URI, not a
    # sidecar file next to it), so skip generating one rather than
    # leave an orphaned file behind in the app's cache dir.
    document.save(_current, path, write_history=False)
