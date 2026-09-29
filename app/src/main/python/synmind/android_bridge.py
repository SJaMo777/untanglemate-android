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
from synmind.core.commands import (
    AddNodeCommand,
    EditTextCommand,
    MoveToTrashCommand,
    ReparentNodeCommand,
    SetBorderColorCommand,
    SetFillColorCommand,
    SetPriorityLevelCommand,
    SetTodoStateCommand,
)
from synmind.core.history import History
from synmind.core.model import MindMap, Node

_current: MindMap | None = None
_history: History | None = None
# True once any command has executed since the last new/open/save. Not as
# precise as comparing undo-stack depth against a saved marker (undoing
# back to exactly the saved state still reads dirty), but simple, and
# good enough for a "you have unsaved changes" indicator rather than
# something correctness-critical.
_dirty: bool = False


def _node_to_dict(node: Node) -> dict:
    return {
        "id": node.id,
        "text": node.text,
        "collapsed": node.collapsed,
        "x": node.x,
        "y": node.y,
        # Hex strings ("#RRGGBB") or null — null means "theme default",
        # same meaning as on Windows (see model.py's own comment on
        # fill_color/border_color). Kotlin falls back to its own default
        # box colors when null rather than guessing a theme color here.
        "fillColor": node.fill_color,
        "borderColor": node.border_color,
        # Only the two fields a simple due-date list view needs — not
        # todo_recurrence/todo_priority's full Windows semantics, which
        # have no Android UI yet.
        "todoMarked": node.todo_marked,
        "todoDueAt": node.todo_due_at,
        # The node-box badges (see node_item.py's ToDo/priority/topic
        # painting): priority_level is the general 1-5 urgency label
        # (independent of todo_priority, which stays Windows-only), and
        # is_topic marks this node as naming the subject of its subtree.
        "priorityLevel": node.priority_level,
        "isTopic": node.is_topic,
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
    global _current, _history, _dirty
    _current = MindMap()
    _history = History(_current)
    _dirty = False
    return _map_to_json(_current)


def open_map_structure(path: str) -> str:
    """Load a real .smmap file (already copied to a local path — Chaquopy/
    core.document need a real filesystem path, not a content:// URI).
    Not laid out yet; call apply_measured_layout() next."""
    global _current, _history, _dirty
    _current = document.load(path)
    _history = History(_current)
    _dirty = False
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


def _execute(command) -> None:
    """history.execute(), plus a defensive extra invalidate_lookup_cache()
    afterward. AddNodeCommand.do() (and likely others) calls mind_map.find()
    on the PARENT before appending the new child — which, since History
    already invalidated the cache right before do() ran, lazily rebuilds it
    from the tree as it was A MOMENT before the mutation. Nothing rebuilds
    it again afterward on this bridge's own account (Windows's canvas
    masks this by rebuilding its scene, and the cache along with it, after
    every command) — so a find()/parent_of() call immediately after
    _history.execute() here would silently miss whatever the command just
    added. Confirmed by direct repro: reparent_node() on a node added this
    same call raised "no such node" even though it was plainly present in
    root.children — traced to exactly this stale cache, not a real
    "does it exist" problem."""
    _require_history().execute(command)
    _current.invalidate_lookup_cache()


def rename_node(node_id: str, new_text: str) -> str:
    """Renames through the real EditTextCommand/History (undo-capable,
    updates node.updated_at) rather than mutating node.text directly —
    the same path Windows's own rename goes through. Returns the
    structure shape again (x/y stale from the old text's size); caller
    must re-measure and call apply_measured_layout, same as after
    *_structure()."""
    global _dirty
    node = _current.find(node_id)
    if node is None:
        raise ValueError("No such node: %s" % node_id)
    _execute(EditTextCommand(
        node_id=node_id, old_text=node.text, new_text=new_text))
    _dirty = True
    return _map_to_json(_current)


def add_child(parent_id: str, text: str = "New Node") -> str:
    """Adds a real child Node via AddNodeCommand/History. Returns
    {"title", "root", "newNodeId"} — same structure shape as
    *_structure() plus the new node's id, so the caller can select/
    open a rename dialog on it immediately without a second round trip
    to search the tree for "whichever node wasn't there before"."""
    global _dirty
    parent = _current.find(parent_id)
    if parent is None:
        raise ValueError("No such node: %s" % parent_id)
    new_node = Node(text=text)
    _execute(AddNodeCommand(parent_id=parent_id, new_node=new_node))
    _dirty = True
    payload = json.loads(_map_to_json(_current))
    payload["newNodeId"] = new_node.id
    return json.dumps(payload)


def delete_node(node_id: str) -> str:
    """Moves the node (and its subtree) to mind_map.trash via
    MoveToTrashCommand — undo-capable, and matches Windows's own default
    Delete (a permanent DeleteNodeCommand also exists in commands.py but
    isn't used here — there's no trash-management UI on Android yet to
    make a permanent-delete option meaningful; undo is the only way back
    for now, same as it would be without a trash view at all)."""
    global _dirty
    if _current.root.id == node_id:
        raise ValueError("Cannot delete the root node")
    _execute(MoveToTrashCommand(node_id=node_id))
    _dirty = True
    return _map_to_json(_current)


def reparent_node(node_id: str, new_parent_id: str) -> str:
    """Moves a node (and its subtree) to under a different parent via
    ReparentNodeCommand/History. Caller must already have rejected
    obviously-invalid targets (new_parent_id == node_id or one of its own
    descendants) — Kotlin has the full tree client-side and can compute
    that set more cheaply than round-tripping to ask Python first."""
    global _dirty
    old_parent = _current.parent_of(node_id)
    if old_parent is None:
        raise ValueError("No such node, or it has no parent: %s" % node_id)
    if _current.find(new_parent_id) is None:
        raise ValueError("No such parent: %s" % new_parent_id)
    old_index = _current.index_of_child(old_parent.id, node_id)
    _execute(ReparentNodeCommand(
        node_id=node_id, old_parent_id=old_parent.id, old_index=old_index,
        new_parent_id=new_parent_id))
    _dirty = True
    return _map_to_json(_current)


def set_fill_color(node_id: str, hex_color: str | None) -> str:
    """hex_color: "#RRGGBB" or null to clear back to the theme default."""
    global _dirty
    node = _current.find(node_id)
    if node is None:
        raise ValueError("No such node: %s" % node_id)
    _execute(SetFillColorCommand(
        node_id=node_id, old_color=node.fill_color, new_color=hex_color))
    _dirty = True
    return _map_to_json(_current)


def set_border_color(node_id: str, hex_color: str | None) -> str:
    """hex_color: "#RRGGBB" or null to clear back to the theme default."""
    global _dirty
    node = _current.find(node_id)
    if node is None:
        raise ValueError("No such node: %s" % node_id)
    _execute(SetBorderColorCommand(
        node_id=node_id, old_color=node.border_color, new_color=hex_color))
    _dirty = True
    return _map_to_json(_current)


def set_todo(node_id: str, marked: bool, due_at: str | None) -> str:
    """Marks/unmarks a node as a ToDo with an optional due date, via the
    real SetTodoStateCommand/History (undo-capable) — same command
    Windows's own ToDo checkbox and due-date picker go through.
    due_at: an ISO date string ("YYYY-MM-DD") or null to clear it.
    todo_recurrence/todo_priority aren't touched — no Android UI for
    either yet, so they're left exactly as they were."""
    global _dirty
    node = _current.find(node_id)
    if node is None:
        raise ValueError("No such node: %s" % node_id)
    _execute(SetTodoStateCommand(
        node_id=node_id,
        old_marked=node.todo_marked, old_due_at=node.todo_due_at,
        new_marked=marked, new_due_at=due_at,
        old_priority=node.todo_priority, new_priority=node.todo_priority,
    ))
    _dirty = True
    return _map_to_json(_current)


def list_todos() -> str:
    """Every todo_marked node in the current map as {id, text, dueAt},
    sorted by due date (nodes with no due date last) — a plain due-date
    list rather than Windows's full month-grid Calendar panel (that
    panel's review scheduling, recurrence, and Google Calendar sync have
    no Android equivalent yet), but reading the same real todo_marked/
    todo_due_at fields."""
    out: list[dict] = []

    def walk(node: Node) -> None:
        if node.todo_marked:
            out.append({
                "id": node.id,
                "text": node.text,
                "dueAt": node.todo_due_at,
            })
        for child in node.children:
            walk(child)

    walk(_current.root)
    out.sort(key=lambda t: (t["dueAt"] is None, t["dueAt"] or ""))
    return json.dumps(out)


def set_priority(node_id: str, level: int | None) -> str:
    """1-5 (1 = most urgent, matching the color scale priority_panel.py's
    _PRIORITY_COLOR uses: red/orange/yellow/lime/blue) or null to clear,
    via the real SetPriorityLevelCommand/History (undo-capable)."""
    global _dirty
    node = _current.find(node_id)
    if node is None:
        raise ValueError("No such node: %s" % node_id)
    _execute(SetPriorityLevelCommand(node_id=node_id, new_level=level))
    _dirty = True
    return _map_to_json(_current)


def toggle_topic(node_id: str) -> str:
    """Flips is_topic on the given node — a direct mutation, not run
    through History, deliberately matching Windows's own
    toggle_topic_on_selected() (see its docstring: "topic marks are
    presentation metadata, like bookmark/view-lock" — not an undoable
    edit to the map's content)."""
    global _dirty
    node = _current.find(node_id)
    if node is None:
        raise ValueError("No such node: %s" % node_id)
    node.is_topic = not node.is_topic
    _dirty = True
    return _map_to_json(_current)


def undo() -> str:
    global _dirty
    _require_history().undo()
    _current.invalidate_lookup_cache()
    _dirty = True
    return _map_to_json(_current)


def redo() -> str:
    global _dirty
    _require_history().redo()
    _current.invalidate_lookup_cache()
    _dirty = True
    return _map_to_json(_current)


def can_undo() -> bool:
    return _require_history().can_undo()


def can_redo() -> bool:
    return _require_history().can_redo()


def is_dirty() -> bool:
    return _dirty


def save_map(path: str) -> None:
    """Writes the current map to a real filesystem path in the same
    Fernet-encrypted format Windows reads/writes (core.file_format,
    unmodified). Caller is responsible for getting those bytes to their
    real destination — a content:// URI (SAF) can't be written directly
    from core.document.save(), which does its own Path(path).write_bytes()."""
    global _dirty
    if _current is None:
        raise RuntimeError("save_map called before a map was loaded/created")
    # write_history=False: the node-history sidecar Windows writes
    # alongside a save has nowhere to go from here (we only copy the
    # single .smmap file's bytes back to a content:// URI, not a
    # sidecar file next to it), so skip generating one rather than
    # leave an orphaned file behind in the app's cache dir.
    document.save(_current, path, write_history=False)
    _dirty = False
