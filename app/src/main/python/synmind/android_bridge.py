"""Android-only glue between Kotlin and synmind/core/.

Deliberately NOT part of core/ — this is the Android equivalent of what
synmind/ui/ is on Windows: a platform layer sitting on top of the shared,
unmodified core logic. Nothing in here should ever be needed by, or
copied into, the Windows app.

Returns plain JSON strings rather than raw Node objects because walking
a PyObject tree attribute-by-attribute from Kotlin (one Chaquopy call per
field per node) is chatty and slow for anything but a tiny map; one JSON
string crossing the bridge is a single call regardless of map size.
"""
from __future__ import annotations

import json

from synmind.core import document
from synmind.core.model import MindMap, Node


def _node_to_dict(node: Node) -> dict:
    return {
        "id": node.id,
        "text": node.text,
        "collapsed": node.collapsed,
        "children": [_node_to_dict(c) for c in node.children],
    }


def _map_to_json(mind_map: MindMap) -> str:
    return json.dumps({
        "title": mind_map.title,
        "root": _node_to_dict(mind_map.root),
    })


def new_map_as_json() -> str:
    """A fresh, empty map — what the app shows before anything is opened."""
    return _map_to_json(MindMap())


def load_map_as_json(path: str) -> str:
    """Load a real .smmap file (already copied to a local path — Chaquopy/
    core.document need a real filesystem path, not a content:// URI) and
    return it in the same shape as new_map_as_json()."""
    return _map_to_json(document.load(path))
