"""File I/O for mind maps. Versioned JSON format."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from synmind.core.colors import (
    DEFAULT_MIN_CONTRAST,
    clamp_min_contrast,
    parse_hex,
)
from synmind.core.model import (
    MindMap,
    Node,
    _default_backup_entry,
    current_machine_id,
)

FILE_VERSION = 2


def _app_version() -> str:
    """The running build's version, or "" if it cannot be read. Never
    raises: a save must not fail because a version string was missing."""
    try:
        from synmind import __version__
        return str(__version__ or "")
    except Exception:
        return ""


def written_by_newer_build(mind_map: MindMap) -> str:
    """The version that last saved this map, but ONLY when that build is
    newer than the one running now. "" in every other case — same build,
    older build, unstamped file, unparseable number.

    The caller is expected to treat a non-empty answer as "saving over
    this file may destroy data", not as "refuse to open it". Reading a
    newer map is safe and always has been; it is the write-back that
    drops unknown fields.
    """
    try:
        from synmind.core.updater import is_newer
        wrote = str(getattr(mind_map, "saved_by_version", "") or "")
        # is_newer returns False when either side has no parseable
        # version in it, so an unstamped map (every file written before
        # this feature) answers "" and nothing is claimed about it.
        return wrote if is_newer(wrote, _app_version()) else ""
    except Exception:
        return ""


def _valid_hex(value: Any) -> str | None:
    """Map-wide colors paint every uncustomized node, so a hand-edited or
    corrupted value would recolor the whole map rather than one node.
    Anything unparseable falls back to the theme."""
    return str(value).strip() if parse_hex(value) else None


def _finite_float(value: Any, default: float = 0.0) -> float:
    """Coerce to a finite float, mapping NaN / ±inf (and unparseable
    values) to `default`. Python's json module parses `NaN`/`Infinity`
    literals into float nan/inf, so a map saved while a node's position
    was non-finite loads back with a NaN position. Handing that to
    QGraphicsItem.setPos() gives the item a NaN transform, which aborts
    the native Windows paint path (offscreen tolerates it). Sanitising
    on load keeps one bad coordinate from taking down startup."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(f):
        return default
    return f


def _serialize_note_comments(comments: Any) -> list[dict]:
    """Normalise the node's `note_comments` for on-disk storage. Drops
    malformed entries and coerces types so a hand-edited or legacy map
    never crashes the loader. Each kept entry is
    {id, start, end, text, quote}."""
    if not isinstance(comments, list):
        return []
    out: list[dict] = []
    for c in comments:
        if not isinstance(c, dict):
            continue
        text = str(c.get("text", "") or "")
        if not text:
            # A comment with no body is meaningless — skip it.
            continue
        try:
            start = int(c.get("start", 0))
            end = int(c.get("end", 0))
        except (TypeError, ValueError):
            continue
        if end < start:
            start, end = end, start
        out.append(
            {
                "id": str(c.get("id", "") or ""),
                "start": start,
                "end": end,
                "text": text,
                "quote": str(c.get("quote", "") or ""),
            }
        )
    return out


def _deserialize_note_comments(raw: Any) -> list[dict]:
    """Inverse of `_serialize_note_comments`; same validation, so a
    corrupt list degrades to an empty one rather than raising."""
    return _serialize_note_comments(raw)


def _clean_procedures(raw: Any) -> dict:
    """Normalise the procedures store: {name: [node_id, ...]}.

    LEGACY. Procedures are nodes now (`Node.is_procedure`, children as
    steps); this only has to survive long enough for
    `MapCanvas._migrate_legacy_procedures` to convert it on load, which
    then clears it. Order is preserved exactly because it becomes the
    order of the new procedure node's children."""
    if not isinstance(raw, dict):
        return {}
    out: dict = {}
    for name, ids in raw.items():
        name = str(name or "").strip()
        if not name or not isinstance(ids, list):
            continue
        seen: set = set()
        kept: list = []
        for i in ids:
            i = str(i or "")
            if i and i not in seen:
                seen.add(i)
                kept.append(i)
        out[name] = kept
    return out


def _clean_remembered_mode(raw: Any) -> str:
    """Normalise `remembered_display_mode` to the two it now has.

    The retired "individual" mode meant "load remembered layouts, but
    only for nodes ticked in individually". The tick is gone, so the
    honest translation of that intent is "on" — not "off"."""
    value = str(raw or "off")
    if value == "individual":
        return "whole"
    return value if value in ("off", "whole") else "off"


def _clean_auto_export(raw: Any) -> dict:
    """Normalise a node's `auto_export` blob for storage / load. Unknown
    or malformed values degrade to an empty dict (auto-export off).
    Empty dict is returned as-is so unconfigured nodes stay tiny on
    disk."""
    if not isinstance(raw, dict) or not raw:
        return {}
    fmt = str(raw.get("format", "html") or "html").lower()
    if fmt not in ("html", "pdf", "word", "pptx"):
        fmt = "html"
    out = {
        "enabled": bool(raw.get("enabled", False)),
        "path": str(raw.get("path", "") or ""),
        "format": fmt,
        "overwrite": bool(raw.get("overwrite", True)),
        # Per-export: re-run this one automatically as the map closes, so
        # the folder on disk always matches the map you last worked on.
        # Off by default — an export that runs itself is opt-in.
        "sync_on_close": bool(raw.get("sync_on_close", False)),
    }
    # Per-export HTML presentation options. Written ONLY when the user
    # has made a choice for this export: absent means "follow the
    # app-wide default on the Exports tab", which is what a newly
    # configured export should do. Storing a bool here unconditionally
    # would freeze every existing export at whatever the default
    # happened to be the first time the file was saved.
    #
    # This list must be kept in step with
    # `MapCanvas.EXPORT_OPTION_KEYS` (synmind/ui/canvas.py) — every key
    # that panel can set needs an entry here too, or the choice is
    # silently dropped the next time the map is saved and reopened.
    # That happened once already: `embed_images` (and several others
    # added alongside it) worked perfectly for the rest of the session
    # but reverted to the app-wide default after a reload, because only
    # the original three keys were ever added to this whitelist.
    for key in (
        "search", "search_inline", "images", "beautify", "effects",
        "breadcrumbs", "page_title", "edited_stamp", "search_bottom",
        "attachments", "contents", "embed_images", "phone_file",
        "pptx_no_lone_child_slide", "pptx_title_highlight",
        "node_divider", "number_nodes", "tabulate_by_level",
        "include_notes", "include_attachments", "show_priorities",
    ):
        if raw.get(key) is not None:
            out[key] = bool(raw[key])
    # The page-width choice is not a flag — it is "fluid", a pixel
    # number, or absent for "follow the app-wide default" — so it is
    # kept as the string `node_export_search_opts` already knows how to
    # re-parse (`html_export.parse_page_width`) rather than coerced to
    # bool like the options above.
    if raw.get("width") is not None:
        out["width"] = str(raw["width"])
    # PowerPoint-only integer settings ("Node progression per slide",
    # "Last layer level") -- not bools, so handled apart from the
    # for-loop above, same as "width". 0 means off/unlimited in both;
    # a malformed value degrades to that rather than raising.
    for int_key in ("pptx_node_progression", "pptx_last_layer_level"):
        if raw.get(int_key) is not None:
            try:
                out[int_key] = max(0, int(raw[int_key]))
            except (TypeError, ValueError):
                pass
    # PowerPoint-only title highlight color -- a "#rrggbb" string, same
    # format `fill_color`/`border_color` already use. Reuses this
    # module's own `parse_hex` (accepts #rgb/#rrggbb/#aarrggbb) just to
    # VALIDATE; malformed values are dropped rather than stored, same
    # "degrade to absent" rule as everything else here.
    hc = raw.get("pptx_title_highlight_color")
    if isinstance(hc, str) and parse_hex(hc) is not None:
        out["pptx_title_highlight_color"] = hc
    ls = raw.get("last_synced_at")
    if isinstance(ls, str) and ls:
        out["last_synced_at"] = ls
    return out


def _serialise_display_memories(
    memories: dict[str, dict[str, bool]] | None,
) -> dict[str, dict[str, bool]]:
    """JSON-clean dump of the per-node display memories. Filters out
    malformed entries so a corrupt or partial dict can't break the save."""
    if not isinstance(memories, dict):
        return {}
    out: dict[str, dict[str, bool]] = {}
    for root_id, sub in memories.items():
        if not isinstance(root_id, str) or not isinstance(sub, dict):
            continue
        cleaned = {
            str(k): bool(v) for k, v in sub.items() if isinstance(k, str)
        }
        if cleaned:
            out[root_id] = cleaned
    return out


def _clean_display_memories(raw: Any) -> dict[str, dict[str, bool]]:
    """Load-side validator. Same shape requirements as the serialiser
    so corrupt entries don't crash the open path or wire memories to
    nonsense. Dead node ids (root or descendants that no longer exist)
    are pruned lazily at apply time instead of here — the model layer
    doesn't know which ids are still live."""
    return _serialise_display_memories(raw)


def _clean_memorized_views(raw: Any) -> list:
    """Validate the "Memorized" (M) entries on both save and load.

    An entry is {"id", "name", "node_id", "created_at", "used_at",
    "use_count", "snapshot"}; the snapshot holds primitives, small
    string lists (the collapse delta) and one flat "settings" dict.
    Anything else is dropped rather than written, so one corrupt entry
    can't take the whole file's save or open path down with it. Entries
    without an id or a node to hang off are meaningless — skipped."""
    if not isinstance(raw, list):
        return []
    out: list = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        eid = entry.get("id")
        node_id = entry.get("node_id")
        if not isinstance(eid, str) or not isinstance(node_id, str):
            continue
        snap_in = entry.get("snapshot")
        snap: dict = {}
        if isinstance(snap_in, dict):
            for k, v in snap_in.items():
                if not isinstance(k, str):
                    continue
                if isinstance(v, (str, int, float, bool)) or v is None:
                    snap[k] = v
                elif isinstance(v, list):
                    snap[k] = [m for m in v if isinstance(m, str)]
                elif isinstance(v, dict) and k == "settings":
                    snap[k] = {
                        sk: sv for sk, sv in v.items()
                        if isinstance(sk, str)
                        and (
                            isinstance(sv, (str, int, float, bool))
                            or sv is None
                        )
                    }
        try:
            uses = int(entry.get("use_count") or 0)
        except (TypeError, ValueError):
            uses = 0
        out.append({
            "id": eid,
            "name": str(entry.get("name") or "").strip() or "Memorized view",
            "node_id": node_id,
            "created_at": str(entry.get("created_at") or ""),
            "used_at": str(entry.get("used_at") or "") or None,
            "use_count": max(0, uses),
            "snapshot": snap,
        })
    return out


def _clean_remembered_layouts(raw: Any) -> dict[str, dict]:
    """Validate the 'Remembered' layout snapshots on both save and load.
    Outer key is the remembered node id; each value is a JSON-safe dict
    of primitive / list fields. Malformed entries are dropped so a
    corrupt snapshot can't break the save or open path."""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict] = {}
    for node_id, snap in raw.items():
        if not isinstance(node_id, str) or not isinstance(snap, dict):
            continue
        cleaned: dict = {}
        for k, v in snap.items():
            if not isinstance(k, str):
                continue
            if isinstance(v, (str, int, float, bool)) or v is None:
                cleaned[k] = v
            elif isinstance(v, list):
                # Collapsed-id lists (and any future list field) — keep
                # only JSON-safe primitive members.
                cleaned[k] = [
                    m for m in v
                    if isinstance(m, (str, int, float, bool))
                ]
            elif isinstance(v, dict) and k == "positions":
                # {node_id: [x, y]} — exact saved node positions. Keep
                # string keys mapping to a 2-number list so a manual
                # arrangement survives save / reload.
                pos: dict = {}
                for sk, sv in v.items():
                    if (
                        isinstance(sk, str)
                        and isinstance(sv, (list, tuple))
                        and len(sv) == 2
                        and all(isinstance(c, (int, float)) for c in sv)
                    ):
                        pos[sk] = [float(sv[0]), float(sv[1])]
                cleaned[k] = pos
            elif isinstance(v, dict):
                # The "settings" sub-dict (toggle / display flags). Keep
                # string keys mapping to JSON-safe primitives so recall
                # can restore the exact working state.
                cleaned[k] = {
                    sk: sv
                    for sk, sv in v.items()
                    if isinstance(sk, str)
                    and (isinstance(sv, (str, int, float, bool)) or sv is None)
                }
        if cleaned:
            out[node_id] = cleaned
    return out


def _serialise_saved_searches(searches: list) -> list[dict]:
    """JSON-clean dump of the per-map saved-search list. Each
    SavedSearch turns into a plain dict so the .smmap payload stays
    pure JSON. Skips malformed entries silently so a corrupt list
    can't break save."""
    from synmind.core.model import SavedSearch
    out: list[dict] = []
    if not isinstance(searches, list):
        return out
    for s in searches:
        if not isinstance(s, SavedSearch):
            continue
        out.append({
            "id": str(s.id),
            "name": str(s.name or ""),
            "kind": str(s.kind or "standard"),
            "query": str(s.query or ""),
            "standard_mode": str(s.standard_mode or "text"),
            "standard_scope": str(s.standard_scope or "map"),
            "standard_text": str(s.standard_text or ""),
            "standard_tag": str(s.standard_tag or ""),
            "standard_date_from": s.standard_date_from,
            "standard_date_to": s.standard_date_to,
            "created_at": str(s.created_at or ""),
            "updated_at": str(s.updated_at or ""),
        })
    return out


def _clean_saved_searches(raw: Any) -> list:
    """Load-side validator. Rejects entries with no id or unknown
    `kind`. Returns a list of SavedSearch instances."""
    from synmind.core.model import SavedSearch
    out: list[SavedSearch] = []
    if not isinstance(raw, list):
        return out
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        sid = entry.get("id")
        if not isinstance(sid, str) or not sid:
            continue
        kind = str(entry.get("kind", "standard") or "standard")
        if kind not in ("standard", "advanced"):
            continue
        out.append(SavedSearch(
            id=sid,
            name=str(entry.get("name", "") or ""),
            kind=kind,
            query=str(entry.get("query", "") or ""),
            standard_mode=str(entry.get("standard_mode", "text") or "text"),
            standard_scope=str(entry.get("standard_scope", "map") or "map"),
            standard_text=str(entry.get("standard_text", "") or ""),
            standard_tag=str(entry.get("standard_tag", "") or ""),
            standard_date_from=entry.get("standard_date_from"),
            standard_date_to=entry.get("standard_date_to"),
            created_at=str(entry.get("created_at", "") or ""),
            updated_at=str(entry.get("updated_at", "") or ""),
        ))
    return out


def _clean_node_shortcuts(raw: Any) -> dict[str, str]:
    """Validate the persisted Shift+Alt+N -> node_id mapping. Discards
    malformed entries (non-string keys/values, slots outside 1..9) so a
    corrupt file can't crash the load or wire a shortcut to nonsense.
    The model layer doesn't know which node ids are still alive, so
    dead-id pruning happens lazily at jump time instead of here."""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in raw.items():
        key = str(k).strip()
        if key not in ("1", "2", "3", "4", "5", "6", "7", "8", "9"):
            continue
        if not isinstance(v, str) or not v:
            continue
        out[key] = v
    return out


def _load_backup_settings(data: dict[str, Any]) -> dict[str, dict]:
    """Build the per-machine backup-settings dict for a loaded map,
    migrating any old flat `backup_*` fields into the current
    machine's entry the first time we see a pre-feature file."""
    per_machine = data.get("backup_settings_per_machine")
    if isinstance(per_machine, dict) and per_machine:
        # Sanitize: keep only entries that look like dicts.
        return {
            str(k): dict(v) for k, v in per_machine.items()
            if isinstance(v, dict)
        }
    # No per-machine block yet — pull the old flat fields into a new
    # entry keyed by the current machine. Only happens once: the next
    # save writes the per-machine dict and the old keys are dropped.
    has_legacy = any(
        key in data
        for key in (
            "backup_folder", "backup_hourly", "backup_daily",
            "backup_weekly", "backup_monthly", "backup_copy_files",
            "backup_retention",
            "backup_last_hourly_at", "backup_last_daily_at",
            "backup_last_weekly_at", "backup_last_monthly_at",
        )
    )
    if not has_legacy:
        return {}
    entry = _default_backup_entry()
    entry["folder"] = data.get("backup_folder")
    entry["hourly"] = bool(data.get("backup_hourly", False))
    entry["daily"] = bool(data.get("backup_daily", False))
    entry["weekly"] = bool(data.get("backup_weekly", False))
    entry["monthly"] = bool(data.get("backup_monthly", False))
    entry["copy_files"] = bool(data.get("backup_copy_files", True))
    entry["retention"] = str(
        data.get("backup_retention", "never") or "never"
    )
    entry["last_hourly_at"] = data.get("backup_last_hourly_at")
    entry["last_daily_at"] = data.get("backup_last_daily_at")
    entry["last_weekly_at"] = data.get("backup_last_weekly_at")
    entry["last_monthly_at"] = data.get("backup_last_monthly_at")
    return {current_machine_id(): entry}


def _node_to_dict(node: Node) -> dict[str, Any]:
    return {
        "id": node.id,
        "text": node.text,
        "x": node.x,
        "y": node.y,
        "image_data": node.image_data,
        "image_format": node.image_format,
        "fill_color": node.fill_color,
        "border_color": getattr(node, "border_color", None),
        "collapsed": node.collapsed,
        "edge_thickness": node.edge_thickness,
        "link_target_id": node.link_target_id,
        "cross_map_link": node.cross_map_link,
        "tags": list(node.tags),
        "review_marked": node.review_marked,
        "review_step": node.review_step,
        "review_due_at": node.review_due_at,
        "google_review_event_id": getattr(
            node, "google_review_event_id", None
        ),
        "google_review_event_synced_hash": getattr(
            node, "google_review_event_synced_hash", None
        ),
        "review_correct_count": int(
            getattr(node, "review_correct_count", 0) or 0
        ),
        "review_wrong_count": int(
            getattr(node, "review_wrong_count", 0) or 0
        ),
        "review_last_tested_at": getattr(
            node, "review_last_tested_at", None
        ),
        "note_review_marked": node.note_review_marked,
        "note_review_step": node.note_review_step,
        "note_review_due_at": node.note_review_due_at,
        # getattr with a default, like the node-level counters above: a
        # map written before these fields existed loads without them.
        "note_review_correct_count": int(
            getattr(node, "note_review_correct_count", 0) or 0
        ),
        "note_review_wrong_count": int(
            getattr(node, "note_review_wrong_count", 0) or 0
        ),
        "note_review_last_tested_at": getattr(
            node, "note_review_last_tested_at", None
        ),
        "todo_marked": node.todo_marked,
        "todo_due_at": node.todo_due_at,
        "todo_recurrence": (
            dict(node.todo_recurrence) if node.todo_recurrence else None
        ),
        "todo_priority": node.todo_priority,
        "google_event_id": getattr(node, "google_event_id", None),
        "google_event_synced_hash": getattr(
            node, "google_event_synced_hash", None
        ),
        "priority_level": getattr(node, "priority_level", None),
        "maturity": int(getattr(node, "maturity", 0) or 0),
        "evidence": int(getattr(node, "evidence", 0) or 0),
        "is_medical_root": bool(getattr(node, "is_medical_root", False)),
        "sketch_host_id": getattr(node, "sketch_host_id", None),
        "completed_at": node.completed_at,
        "completion_rate": node.completion_rate,
        "note_html": node.note_html,
        "note_locked": bool(getattr(node, "note_locked", False)),
        "note_sections_collapsed": {
            str(k): bool(v)
            for k, v in getattr(node, "note_sections_collapsed", {}).items()
        },
        "note_sections_recall": {
            str(k): bool(v)
            for k, v in getattr(node, "note_sections_recall", {}).items()
        },
        "note_comments": _serialize_note_comments(
            getattr(node, "note_comments", None)
        ),
        "auto_export": _clean_auto_export(getattr(node, "auto_export", None)),
        "export_excluded": bool(getattr(node, "export_excluded", False)),
        "ppt_slide_topic": bool(getattr(node, "ppt_slide_topic", False)),
        "ppt_include_attachments": bool(
            getattr(node, "ppt_include_attachments", False)
        ),
        "note_cursor_position": node.note_cursor_position,
        "note_updated_at": node.note_updated_at,
        "last_viewed_at": getattr(node, "last_viewed_at", None),
        "note_background_color": node.note_background_color,
        "image_ocr_text": dict(node.image_ocr_text),
        "image_sketch_ids": dict(getattr(node, "image_sketch_ids", {}) or {}),
        "pdf_text_cache": dict(node.pdf_text_cache),
        "attachment_text": dict(getattr(node, "attachment_text", {}) or {}),
        "attachment_stamps": dict(getattr(node, "attachment_stamps", {}) or {}),
        "image_recall_regions": {
            k: [dict(r) for r in v]
            for k, v in node.image_recall_regions.items()
        },
        "title_recall_regions": [
            list(rng) for rng in getattr(node, "title_recall_regions", []) or []
        ],
        "external_link": node.external_link,
        "alias_of": node.alias_of,
        "function_id": getattr(node, "function_id", None),
        "function_setting": getattr(node, "function_setting", None),
        "function_values": dict(getattr(node, "function_values", None)
                                or {}),
        "archived_from_parent_id": node.archived_from_parent_id,
        "backed_up_from_parent_id": getattr(node, "backed_up_from_parent_id", None),
        "backed_up_at": getattr(node, "backed_up_at", None),
        "auto_archived_on_completion": bool(
            getattr(node, "auto_archived_on_completion", False)
        ),
        "attachments": list(node.attachments),
        "manual_width": (
            float(node.manual_width)
            if getattr(node, "manual_width", None) is not None else None
        ),
        "text_bold": node.text_bold,
        "text_italic": node.text_italic,
        "text_underline": node.text_underline,
        "text_strikethrough": node.text_strikethrough,
        "text_font_size": node.text_font_size,
        "text_highlight": node.text_highlight,
        "text_color": node.text_color,
        "text_alignment": str(getattr(node, "text_alignment", "center")),
        "text_html": node.text_html,
        "hide_node_image": node.hide_node_image,
        "hide_note_image": node.hide_note_image,
        "sketch_id": node.sketch_id,
        "sketch_ocr_text": dict(getattr(node, "sketch_ocr_text", {}) or {}),
        "is_topic": bool(getattr(node, "is_topic", False)),
        "is_procedure": bool(getattr(node, "is_procedure", False)),
        "remembered_auto": bool(getattr(node, "remembered_auto", False)),
        "working": bool(getattr(node, "working", False)),
        "working_forget_until": getattr(node, "working_forget_until", None),
        "do_after_completion": list(
            getattr(node, "do_after_completion", None) or []
        ),
        "in_work_flow": bool(getattr(node, "in_work_flow", False)),
        "workflow_name": str(getattr(node, "workflow_name", "") or ""),
        "workflow_finish_id": getattr(node, "workflow_finish_id", None),
        "workflow_finish_for": getattr(node, "workflow_finish_for", None),
        "workflow_pos": (
            list(node.workflow_pos)
            if getattr(node, "workflow_pos", None) is not None else None
        ),
        "workflow_group_id": getattr(node, "workflow_group_id", None),
        "created_at": node.created_at,
        "updated_at": node.updated_at,
        "history_recording": bool(getattr(node, "history_recording", False)),
        "children": [_node_to_dict(c) for c in node.children],
    }


def _dict_to_node(data: dict[str, Any]) -> Node:
    from synmind.core.model import _now_iso, _new_id

    fallback = _now_iso()
    node = Node(
        # `id` and `text` are tolerant of omission so hand- or AI-authored
        # files don't have to supply them: a missing id is auto-generated
        # (uuid4 hex), a missing text becomes empty.
        id=(str(data.get("id")) if data.get("id") else _new_id()),
        text=str(data.get("text", "") or ""),
        x=_finite_float(data.get("x", 0.0)),
        y=_finite_float(data.get("y", 0.0)),
        image_data=data.get("image_data"),
        image_format=data.get("image_format"),
        fill_color=data.get("fill_color"),
        border_color=data.get("border_color"),
        collapsed=data.get("collapsed", False),
        edge_thickness=data.get("edge_thickness"),
        link_target_id=data.get("link_target_id"),
        cross_map_link=(
            dict(data["cross_map_link"])
            if isinstance(data.get("cross_map_link"), dict)
            else None
        ),
        tags=list(data.get("tags") or []),
        review_marked=bool(data.get("review_marked", False)),
        review_step=int(data.get("review_step", 0)),
        review_due_at=data.get("review_due_at"),
        google_review_event_id=data.get("google_review_event_id"),
        google_review_event_synced_hash=data.get(
            "google_review_event_synced_hash"
        ),
        review_correct_count=int(data.get("review_correct_count", 0) or 0),
        review_wrong_count=int(data.get("review_wrong_count", 0) or 0),
        review_last_tested_at=data.get("review_last_tested_at"),
        note_review_marked=bool(data.get("note_review_marked", False)),
        note_review_step=int(data.get("note_review_step", 0)),
        note_review_due_at=data.get("note_review_due_at"),
        note_review_correct_count=int(
            data.get("note_review_correct_count", 0) or 0
        ),
        note_review_wrong_count=int(
            data.get("note_review_wrong_count", 0) or 0
        ),
        note_review_last_tested_at=data.get("note_review_last_tested_at"),
        todo_marked=bool(data.get("todo_marked", False)),
        todo_due_at=data.get("todo_due_at"),
        todo_recurrence=(
            dict(data["todo_recurrence"])
            if isinstance(data.get("todo_recurrence"), dict)
            else None
        ),
        todo_priority=(
            str(data.get("todo_priority")).upper()
            if data.get("todo_priority") in (
                "URGENT", "HIGH", "MEDIUM", "LOW",
                "urgent", "high", "medium", "low",
            )
            else None
        ),
        google_event_id=data.get("google_event_id"),
        google_event_synced_hash=data.get("google_event_synced_hash"),
        priority_level=(
            int(data["priority_level"])
            if str(data.get("priority_level")) in ("1", "2", "3", "4", "5")
            else None
        ),
        maturity=(
            int(data["maturity"])
            if str(data.get("maturity")) in ("1", "2", "3", "4", "5")
            else 0
        ),
        evidence=(
            int(data["evidence"])
            if str(data.get("evidence")) in ("1", "2", "3", "4", "5")
            else 0
        ),
        is_medical_root=bool(data.get("is_medical_root", False)),
        sketch_host_id=data.get("sketch_host_id"),
        completed_at=data.get("completed_at"),
        completion_rate=(
            int(data["completion_rate"])
            if data.get("completion_rate") in (0, 20, 40, 60, 80, 100)
            else None
        ),
        note_html=data.get("note_html", "") or "",
        note_locked=bool(data.get("note_locked", False)),
        note_sections_collapsed={
            str(k): bool(v)
            for k, v in (data.get("note_sections_collapsed") or {}).items()
        },
        note_sections_recall={
            str(k): bool(v)
            for k, v in (data.get("note_sections_recall") or {}).items()
        },
        note_comments=_deserialize_note_comments(data.get("note_comments")),
        auto_export=_clean_auto_export(data.get("auto_export")),
        export_excluded=bool(data.get("export_excluded", False)),
        ppt_slide_topic=bool(data.get("ppt_slide_topic", False)),
        ppt_include_attachments=bool(
            data.get("ppt_include_attachments", False)
        ),
        note_cursor_position=(
            int(data["note_cursor_position"])
            if isinstance(data.get("note_cursor_position"), (int, float))
            and int(data["note_cursor_position"]) >= 0
            else None
        ),
        note_updated_at=data.get("note_updated_at"),
        last_viewed_at=data.get("last_viewed_at"),
        note_background_color=data.get("note_background_color"),
        image_ocr_text={
            str(k): str(v)
            for k, v in (data.get("image_ocr_text") or {}).items()
            if isinstance(v, str)
        },
        image_sketch_ids={
            str(k): str(v)
            for k, v in (data.get("image_sketch_ids") or {}).items()
            if isinstance(v, str)
        },
        pdf_text_cache={
            str(k): str(v)
            for k, v in (data.get("pdf_text_cache") or {}).items()
            if isinstance(v, str)
        },
        attachment_text={
            str(k): str(v)
            for k, v in (data.get("attachment_text") or {}).items()
            if isinstance(v, str)
        },
        attachment_stamps={
            str(k): str(v)
            for k, v in (data.get("attachment_stamps") or {}).items()
            if isinstance(v, str)
        },
        image_recall_regions={
            str(k): [
                {
                    "x": float(r.get("x", 0)),
                    "y": float(r.get("y", 0)),
                    "w": float(r.get("w", 0)),
                    "h": float(r.get("h", 0)),
                }
                for r in (v or [])
                if isinstance(r, dict)
            ]
            for k, v in (data.get("image_recall_regions") or {}).items()
            if isinstance(v, list)
        },
        title_recall_regions=[
            [int(rng[0]), int(rng[1])]
            for rng in (data.get("title_recall_regions") or [])
            if isinstance(rng, (list, tuple)) and len(rng) >= 2
        ],
        external_link=data.get("external_link"),
        alias_of=data.get("alias_of"),
        function_id=data.get("function_id"),
        function_setting=data.get("function_setting"),
        function_values=dict(data.get("function_values") or {}),
        archived_from_parent_id=data.get("archived_from_parent_id"),
        backed_up_from_parent_id=data.get("backed_up_from_parent_id"),
        backed_up_at=data.get("backed_up_at"),
        auto_archived_on_completion=bool(
            data.get("auto_archived_on_completion") or False
        ),
        attachments=list(data.get("attachments") or []),
        manual_width=(
            float(data["manual_width"])
            if data.get("manual_width") is not None
            else None
        ),
        text_bold=bool(data.get("text_bold", False)),
        text_italic=bool(data.get("text_italic", False)),
        text_underline=bool(data.get("text_underline", False)),
        text_strikethrough=bool(data.get("text_strikethrough", False)),
        text_font_size=(
            int(data["text_font_size"])
            if data.get("text_font_size") is not None
            else None
        ),
        text_highlight=data.get("text_highlight"),
        text_color=data.get("text_color"),
        text_html=(
            str(data["text_html"])
            if isinstance(data.get("text_html"), str)
            and data.get("text_html")
            else None
        ),
        text_alignment=(
            str(data.get("text_alignment"))
            if str(data.get("text_alignment") or "") in ("left", "center", "right")
            else "center"
        ),
        hide_node_image=bool(data.get("hide_node_image", False)),
        hide_note_image=bool(data.get("hide_note_image", False)),
        sketch_id=(
            str(data["sketch_id"])
            if isinstance(data.get("sketch_id"), str)
            and data.get("sketch_id")
            else None
        ),
        sketch_ocr_text={
            str(k): str(v)
            for k, v in (data.get("sketch_ocr_text") or {}).items()
            if isinstance(v, str)
        },
        is_topic=bool(data.get("is_topic", False)),
        is_procedure=bool(data.get("is_procedure", False)),
        remembered_auto=bool(data.get("remembered_auto", False)),
        working=bool(data.get("working", False)),
        working_forget_until=(
            str(data["working_forget_until"])
            if data.get("working_forget_until")
            else None
        ),
        do_after_completion=[
            str(x) for x in (data.get("do_after_completion") or [])
        ],
        in_work_flow=bool(data.get("in_work_flow", False)),
        workflow_name=str(data.get("workflow_name", "") or ""),
        workflow_finish_id=data.get("workflow_finish_id"),
        workflow_finish_for=data.get("workflow_finish_for"),
        workflow_pos=(
            tuple(data["workflow_pos"])
            if isinstance(data.get("workflow_pos"), (list, tuple))
            and len(data.get("workflow_pos") or []) == 2 else None
        ),
        workflow_group_id=data.get("workflow_group_id"),
        created_at=data.get("created_at") or fallback,
        updated_at=data.get("updated_at") or fallback,
        history_recording=bool(data.get("history_recording", False)),
    )
    for child_data in data.get("children", []):
        node.children.append(_dict_to_node(child_data))
    return node


def to_json_text(mind_map: MindMap) -> str:
    """The map as the JSON text `save` writes. Split out so a caller can
    do this cheap part where the model is safe to read (the UI thread)
    and hand the slow part — compress, encrypt, write — to a worker."""
    payload = {
        "version": FILE_VERSION,
        # The APP version doing the writing — deliberately not
        # FILE_VERSION, which is the format number and moves far more
        # slowly. Fields get added to the format all the time without
        # FILE_VERSION changing (functions did), so the format number
        # cannot tell an old build that a map holds things it would
        # destroy on save. The build number can.
        "app_version": _app_version(),
        "title": mind_map.title,
        "theme_name": mind_map.theme_name,
        "layout_style": mind_map.layout_style,
        "line_style": mind_map.line_style,
        "line_thickness": mind_map.line_thickness,
        "edge_anchor_mode": mind_map.edge_anchor_mode,
        "show_edited_date": bool(mind_map.show_edited_date),
        "custom_tags": [str(t) for t in (mind_map.custom_tags or [])],
        "map_node_fill_color": mind_map.map_node_fill_color,
        "map_node_text_color": mind_map.map_node_text_color,
        "map_text_color_auto": bool(mind_map.map_text_color_auto),
        "priority_node_colors": bool(
            getattr(mind_map, "priority_node_colors", False)
        ),
        "working_map_fit_to_view": bool(
            getattr(mind_map, "working_map_fit_to_view", False)
        ),
        "auto_adjust_enabled": bool(
            getattr(mind_map, "auto_adjust_enabled", True)
        ),
        "movement_placement": str(
            getattr(mind_map, "movement_placement", "middle") or "middle"
        ),
        "scale_mode": str(
            getattr(mind_map, "scale_mode", "fit_map") or "fit_map"
        ),
        "pause_state": str(
            getattr(mind_map, "pause_state", "off") or "off"
        ),
        "auto_adjust_delayed": bool(
            getattr(mind_map, "auto_adjust_delayed", False)
        ),
        "auto_optimize_colors_on_style_change": bool(
            mind_map.auto_optimize_colors_on_style_change
        ),
        "color_contrast_min_ratio": float(mind_map.color_contrast_min_ratio),
        "display_mode": mind_map.display_mode,
        "follow_depth": mind_map.follow_depth,
        "follow_depth_above": mind_map.follow_depth_above,
        "follow_unbounded_above": bool(mind_map.follow_unbounded_above),
        "follow_unbounded_below": bool(mind_map.follow_unbounded_below),
        "recall_depth": int(getattr(mind_map, "recall_depth", 2)),
        "recall_depth_above": int(getattr(mind_map, "recall_depth_above", 1)),
        "auto_center_on_selection": bool(mind_map.auto_center_on_selection),
        "auto_center_left": bool(getattr(mind_map, "auto_center_left", False)),
        "auto_center_delayed": bool(
            getattr(mind_map, "auto_center_delayed", False)
        ),
        "no_view_move_on_end_node": bool(
            getattr(mind_map, "no_view_move_on_end_node", False)
        ),
        "auto_toggles": bool(getattr(mind_map, "auto_toggles", False)),
        "auto_move_enabled": bool(getattr(mind_map, "auto_move_enabled", True)),
        "fit_descendants_only": bool(getattr(mind_map, "fit_descendants_only", False)),
        "fit_descendants_depth": int(getattr(mind_map, "fit_descendants_depth", 0) or 0),
        "scale_auto_delayed": bool(getattr(mind_map, "scale_auto_delayed", False)),
        "follow_fit_to_view": mind_map.follow_fit_to_view,
        "standard_max_depth": mind_map.standard_max_depth,
        "standard_drag_locked": bool(
            getattr(mind_map, "standard_drag_locked", False)
        ),
        "tag_map_tag": mind_map.tag_map_tag,
        "procedures": {
            str(name): [str(i) for i in (ids or [])]
            for name, ids in (getattr(mind_map, "procedures", None) or {}).items()
        },
        "procedure_map_name": str(
            getattr(mind_map, "procedure_map_name", "") or ""
        ),
        "procedure_map_depth": int(
            getattr(mind_map, "procedure_map_depth", 1) or 1
        ),
        "tag_map_depth": mind_map.tag_map_depth,
        "todo_map_depth": mind_map.todo_map_depth,
        "bookmark_map_depth": mind_map.bookmark_map_depth,
        "bookmark_map_depth_above": mind_map.bookmark_map_depth_above,
        "alias_map_depth": mind_map.alias_map_depth,
        "alias_map_depth_above": int(getattr(mind_map, "alias_map_depth_above", 2)),
        "alias_focus_id": getattr(mind_map, "alias_focus_id", None),
        "bookmark_panel_jump_on_click": mind_map.bookmark_panel_jump_on_click,
        "node_shortcuts": dict(mind_map.node_shortcuts or {}),
        "tag_shortcuts": dict(mind_map.tag_shortcuts or {}),
        "saved_searches": _serialise_saved_searches(
            getattr(mind_map, "saved_searches", []) or []
        ),
        "saved_search_shortcuts": dict(
            getattr(mind_map, "saved_search_shortcuts", {}) or {}
        ),
        "control_panel_saved_searches": [
            str(s)
            for s in (getattr(mind_map, "control_panel_saved_searches", []) or [])
        ],
        "saved_layout_shortcuts": dict(
            getattr(mind_map, "saved_layout_shortcuts", {}) or {}
        ),
        "node_shortcut_layouts": _clean_remembered_layouts(
            getattr(mind_map, "node_shortcut_layouts", None)
        ),
        "bookmark_layouts": _clean_remembered_layouts(
            getattr(mind_map, "bookmark_layouts", None)
        ),
        "open_on_click_when_paused": bool(
            getattr(mind_map, "open_on_click_when_paused", False)
        ),
        "auto_ocr_on_close": bool(getattr(mind_map, "auto_ocr_on_close", False)),
        "auto_pause_levels": max(
            0, min(3, int(getattr(mind_map, "auto_pause_levels", 0) or 0))
        ),
        "open_on_select": bool(getattr(mind_map, "open_on_select", False)),
        "shortcut_manager_items": [
            {"kind": str(it.get("kind")),
             "target_id": str(it.get("target_id"))}
            for it in (getattr(mind_map, "shortcut_manager_items", None) or [])
            if isinstance(it, dict) and it.get("kind") and it.get("target_id")
        ],
        "view_locked": bool(mind_map.view_locked),
        "working_map_show_all": bool(
            getattr(mind_map, "working_map_show_all", False)
        ),
        "node_display_memories": _serialise_display_memories(
            mind_map.node_display_memories
        ),
        "recall_node_display_memories": bool(
            mind_map.recall_node_display_memories
        ),
        "auto_beautify": bool(mind_map.auto_beautify),
        "info_page_enabled": bool(
            getattr(mind_map, "info_page_enabled", False)
        ),
        "revise_map_depth": mind_map.revise_map_depth,
        "standard_fit_to_view": mind_map.standard_fit_to_view,
        "tag_map_fit_to_view": mind_map.tag_map_fit_to_view,
        "todo_map_fit_to_view": mind_map.todo_map_fit_to_view,
        "bookmark_map_fit_to_view": mind_map.bookmark_map_fit_to_view,
        "revise_map_fit_to_view": mind_map.revise_map_fit_to_view,
        "alias_map_fit_to_view": bool(getattr(mind_map, "alias_map_fit_to_view", True)),
        "show_edited_date_on_hover": mind_map.show_edited_date_on_hover,
        "last_base_mode": mind_map.last_base_mode,
        "quick_input_target_id": mind_map.quick_input_target_id,
        "archive_node_id": mind_map.archive_node_id,
        "backup_node_id": getattr(mind_map, "backup_node_id", None),
        "completed_display_mode": str(
            getattr(mind_map, "completed_display_mode", "original")
            or "original"
        ),
        "hover_preview_enabled": bool(
            getattr(mind_map, "hover_preview_enabled", False)
        ),
        "minimalist_layout": bool(
            getattr(mind_map, "minimalist_layout", False)
        ),
        "horizontal_line_length": float(
            getattr(mind_map, "horizontal_line_length", 60.0) or 60.0
        ),
        "node_image_mode": mind_map.node_image_mode,
        "open_at": mind_map.open_at,
        "last_selected_id": mind_map.last_selected_id,
        "open_at_node_id": mind_map.open_at_node_id,
        "focus_id": mind_map.focus_id,
        "view_scale": mind_map.view_scale,
        "view_center_x": mind_map.view_center_x,
        "view_center_y": mind_map.view_center_y,
        "bookmarked_ids": list(mind_map.bookmarked_ids),
        "bookmark_center_ids": [
            str(x) for x in (getattr(mind_map, "bookmark_center_ids", None) or [])
        ],
        "attachments_folder": mind_map.attachments_folder,
        # node_history is NOT written here any more — it lives in the
        # .smhist sidecar (see save_node_history). Old files still carry
        # it; `load` migrates those on the next save.
        "history_filter_days": getattr(mind_map, "history_filter_days", None),
        "history_recording_enabled": bool(
            getattr(mind_map, "history_recording_enabled", True)
        ),
        "history_max_entries_per_node": int(
            getattr(mind_map, "history_max_entries_per_node", 30) or 30
        ),
        "history_max_age_days": (
            int(getattr(mind_map, "history_max_age_days", None))
            if isinstance(getattr(mind_map, "history_max_age_days", None), int)
            and not isinstance(
                getattr(mind_map, "history_max_age_days", None), bool
            )
            else None
        ),
        # Recent Views' own auto-delete threshold (history_panel.py) —
        # a different setting from history_max_age_days above (that one
        # is the per-node EDIT-diff log; this one only ever clears
        # last_viewed_at). Same int-or-None shape, same reason: keep a
        # bad/legacy value from silently becoming a real number.
        "views_auto_delete_days": (
            int(getattr(mind_map, "views_auto_delete_days", None))
            if isinstance(getattr(mind_map, "views_auto_delete_days", None), int)
            and not isinstance(
                getattr(mind_map, "views_auto_delete_days", None), bool
            )
            else None
        ),
        # Per-machine backup config — see MindMap docstring. Keyed by
        # hostname. Other computers' entries are preserved unchanged.
        "backup_settings_per_machine": dict(
            mind_map.backup_settings_per_machine
        ),
        "ocr_languages": list(mind_map.ocr_languages),
        "ocr_engine": mind_map.ocr_engine,
        "review_timer_seconds": int(
            getattr(mind_map, "review_timer_seconds", 0) or 0
        ),
        "last_review_test_mode": str(
            getattr(mind_map, "last_review_test_mode", "untimed") or "untimed"
        ),
        "review_timer_multiply_by_masks": bool(
            getattr(mind_map, "review_timer_multiply_by_masks", False)
        ),
        "review_filter_overdue": bool(
            getattr(mind_map, "review_filter_overdue", False)
        ),
        "review_kind_filter": str(
            getattr(mind_map, "review_kind_filter", "both") or "both"
        ),
        "review_correct_threshold_enabled": bool(
            getattr(mind_map, "review_correct_threshold_enabled", False)
        ),
        "review_correct_threshold_pct": int(
            getattr(mind_map, "review_correct_threshold_pct", 80) or 80
        ),
        "sr_intervals_days": list(
            getattr(mind_map, "sr_intervals_days", []) or []
        ),
        "sr_correct_multiplier": float(
            getattr(mind_map, "sr_correct_multiplier", 1.0) or 1.0
        ),
        "sr_use_hours": bool(
            getattr(mind_map, "sr_use_hours", False)
        ),
        "filter_node_id": getattr(mind_map, "filter_node_id", None),
        "todo_filter_mode": str(
            getattr(mind_map, "todo_filter_mode", "off") or "off"
        ),
        "recent_filter_ids": list(
            getattr(mind_map, "recent_filter_ids", []) or []
        ),
        "remembered_layouts": _clean_remembered_layouts(
            getattr(mind_map, "remembered_layouts", None)
        ),
        "saved_remembered_layouts": [
            dict(e) for e in
            (getattr(mind_map, "saved_remembered_layouts", None) or [])
            if isinstance(e, dict)
        ],
        "memorized_views": _clean_memorized_views(
            getattr(mind_map, "memorized_views", None)
        ),
        "shortcut_palette_state": dict(
            getattr(mind_map, "shortcut_palette_state", {}) or {}
        ),
        "control_panel_state": dict(
            getattr(mind_map, "control_panel_state", {}) or {}
        ),
        "control_panel_favorites": list(
            getattr(mind_map, "control_panel_favorites", []) or []
        ),
        "menu_bar_items": list(
            getattr(mind_map, "menu_bar_items", []) or []
        ),
        "button_states": dict(
            getattr(mind_map, "button_states", None) or {}
        ),
        "machine_ui_settings": {
            str(k): v
            for k, v in (
                getattr(mind_map, "machine_ui_settings", None) or {}
            ).items()
            if isinstance(v, dict)
        },
        "search_include_archives": bool(
            getattr(mind_map, "search_include_archives", False)
        ),
        "review_toolbar_geometry": str(
            getattr(mind_map, "review_toolbar_geometry", "") or ""
        ),
        "note_editor_geometry": str(
            getattr(mind_map, "note_editor_geometry", "") or ""
        ),
        "note_editor_maximized": bool(
            getattr(mind_map, "note_editor_maximized", False)
        ),
        "calendar_view_mode": str(
            getattr(mind_map, "calendar_view_mode", "month") or "month"
        ),
        "calendar_show_overdue": bool(
            getattr(mind_map, "calendar_show_overdue", True)
        ),
        "calendar_show_today_due": bool(
            getattr(mind_map, "calendar_show_today_due", True)
        ),
        "calendar_show_upcoming": bool(
            getattr(mind_map, "calendar_show_upcoming", True)
        ),
        "ocr_trigger_mode": mind_map.ocr_trigger_mode,
        "ocr_last_daily_run": float(mind_map.ocr_last_daily_run),
        "ocr_run_in_background": bool(mind_map.ocr_run_in_background),
        "badge_position": mind_map.badge_position,
        "badge_visibility": {
            str(k): bool(v)
            for k, v in (getattr(mind_map, "badge_visibility", None) or {}).items()
        },
        "view_dwell_ms": int(getattr(mind_map, "view_dwell_ms", 5000) or 5000),
        "follow_reapply_ms": int(
            getattr(mind_map, "follow_reapply_ms", 700) or 700),
        "calendar_show_todos": bool(mind_map.calendar_show_todos),
        "calendar_show_reviews": bool(mind_map.calendar_show_reviews),
        "calendar_week_start": str(mind_map.calendar_week_start or "monday"),
        "google_sync_scope": str(
            getattr(mind_map, "google_sync_scope", "all") or "all"
        ),
        "google_sync_priority_filter": bool(
            getattr(mind_map, "google_sync_priority_filter", False)
        ),
        "google_sync_priority_max_level": int(
            getattr(mind_map, "google_sync_priority_max_level", 5) or 5
        ),
        "google_sync_on_close": bool(
            getattr(mind_map, "google_sync_on_close", False)
        ),
        "google_calendar_known_event_ids": list(
            getattr(mind_map, "google_calendar_known_event_ids", []) or []
        ),
        "google_calendar_last_synced_calendar_id": getattr(
            mind_map, "google_calendar_last_synced_calendar_id", None
        ),
        "search_target": str(
            getattr(mind_map, "search_target", "subtree_title")
            or "subtree_title"
        ),
        "search_sort": str(
            getattr(mind_map, "search_sort", "default") or "default"
        ),
        "search_history": [
            str(s) for s in (
                getattr(mind_map, "search_history", None) or []
            )
            if isinstance(s, str) and s.strip()
        ],
        "show_trash_widget": bool(mind_map.show_trash_widget),
        "editable": bool(getattr(mind_map, "editable", True)),
        "edit_mode": str(getattr(mind_map, "edit_mode", "editable")),
        "sketch_finger_input_enabled": bool(
            getattr(mind_map, "sketch_finger_input_enabled", True)
        ),
        "sketch_palm_rejection_enabled": bool(
            getattr(mind_map, "sketch_palm_rejection_enabled", True)
        ),
        "review_show_mode": str(
            getattr(mind_map, "review_show_mode", "relationships") or "relationships"
        ),
        "show_topic_label_on_descendants": bool(
            getattr(mind_map, "show_topic_label_on_descendants", False)
        ),
        "search_panel_auto_close": bool(
            getattr(mind_map, "search_panel_auto_close", False)
        ),
        "search_panel_auto_close_tabs": {
            str(k): bool(v)
            for k, v in (
                getattr(mind_map, "search_panel_auto_close_tabs", None) or {}
            ).items()
        },
        "todo_panel_auto_close_tabs": {
            str(k): bool(v)
            for k, v in (
                getattr(mind_map, "todo_panel_auto_close_tabs", None) or {}
            ).items()
        },
        "panel_auto_close": {
            str(k): bool(v)
            for k, v in (
                getattr(mind_map, "panel_auto_close", None) or {}
            ).items()
        },
        "panel_sort_order": {
            str(k): str(v)
            for k, v in (
                getattr(mind_map, "panel_sort_order", None) or {}
            ).items()
            if isinstance(v, str)
        },
        "todo_panel_filter": (
            str(getattr(mind_map, "todo_panel_filter", "all") or "all")
        ),
        "panel_last_tab": {
            str(k): str(v)
            for k, v in (
                getattr(mind_map, "panel_last_tab", None) or {}
            ).items()
            if isinstance(v, str)
        },
        "remembered_display_mode": str(
            getattr(mind_map, "remembered_display_mode", "off") or "off"
        ),
        "auto_layers_on_select": bool(
            getattr(mind_map, "auto_layers_on_select", True)
        ),
        "trash": [
            {
                "node": _node_to_dict(e.node),
                "parent_id": e.parent_id,
                "child_index": int(e.child_index),
                "deleted_at": e.deleted_at,
                "display_text": e.display_text,
            }
            for e in (mind_map.trash or [])
        ],
        "navigation_history": dict(
            getattr(mind_map, "navigation_history", None) or {}
        ),
        "root": _node_to_dict(mind_map.root),
    }
    return json.dumps(payload, indent=2)


def save(
    mind_map: MindMap, path: str | Path, *, write_history: bool = True
) -> None:
    """Write the map to `path`.

    `write_history=False` is for copies that are not THE map — the timed
    revert snapshots and pre-revert `deleted_` files. The history
    sidecar belongs to the live map: writing one beside every copy put a
    ~90 MB file into the revert folder every five minutes (the ladder
    only ever pruned the .smmap, so they piled up), and, worse, it
    cleared `node_history_dirty` for a file nobody would ever read, so
    the next real save believed the live sidecar was current and skipped
    it."""
    # Encrypted on-disk format. The save always emits the encrypted
    # form — legacy plaintext maps loaded via `load()` get rewritten
    # in the new format on the next save, no manual conversion step.
    from synmind.core.file_format import write_map_text
    write_map_text(path, to_json_text(mind_map))
    if write_history:
        save_node_history(mind_map, path)


# ---------------------------------------------------------------------
# Node history sidecar
# ---------------------------------------------------------------------
# The history store used to live inside the .smmap. On a long-lived map
# it became the single biggest thing in the file — 42 MB of 89 MB on the
# map this was measured against — and every open parsed it and every
# save re-serialised, gzipped, encrypted and wrote it, despite nothing
# reading it until the user opens a node's History dialog.
#
# It now lives beside the map as `<name>.smhist`, in the same encrypted
# container. `MindMap.node_history` is None while unread; the UI calls
# `load_node_history` on first use. A save writes the sidecar only when
# the store was actually loaded AND touched, so an ordinary session that
# never opens a history dialog never pays for it at all.

HISTORY_EXT = ".smhist"


def node_history_path(map_path: str | Path) -> Path:
    return Path(map_path).with_suffix(HISTORY_EXT)


def load_node_history(map_path: str | Path) -> dict:
    """Read the sidecar for `map_path`. Returns an empty store when it
    doesn't exist or can't be read — a missing history is a normal
    state (no node has ever been recorded), not an error."""
    side = node_history_path(map_path)
    try:
        if not side.is_file():
            return {}
        from synmind.core.file_format import read_map_text
        data = json.loads(read_map_text(side))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_node_history(mind_map: MindMap, map_path: str | Path) -> None:
    """Write the sidecar, but only when there's a reason to.

    Skipped when the store was never loaded (None) — that means nothing
    in this session touched history, so whatever is on disk is still
    current — and when it's loaded but unchanged."""
    store = getattr(mind_map, "node_history", None)
    if store is None:
        return
    if not getattr(mind_map, "node_history_dirty", False):
        return
    side = node_history_path(map_path)
    try:
        if not store or not (store.get("entries") or store.get("snapshots")):
            # Nothing left to keep — drop the file rather than leave a
            # stale one that a later load would resurrect.
            if side.is_file():
                side.unlink()
            mind_map.node_history_dirty = False
            return
        from synmind.core.file_format import write_map_text
        write_map_text(side, json.dumps(store))
        mind_map.node_history_dirty = False
    except Exception:
        # Leave the dirty flag set so the next save retries rather than
        # silently dropping the history.
        pass


def _cleanup_empty_note_wrappers(node) -> None:
    """One-shot cleanup for `note_html` values that are just an empty
    QTextEdit HTML wrapper (no actual plain text inside). A bug in the
    Info Page panel was committing the wrapper back as the new note
    on every click, falsely marking nodes as having a note (the N
    badge). Running this on load wipes those phantom notes; nodes
    that have real content are left alone.

    Detection: strip tags, strip whitespace; if nothing remains, the
    note is empty even though the HTML field is non-falsy. Media tags
    (img / video / audio / embed) bypass the check — an Alt+S sketch
    that's nothing but `<p><img …/></p>` strips to "" but is not empty
    in any meaningful sense, and silently nuking it on load was the
    cause of the disappearing-sketch bug.
    """
    import re
    if node is None:
        return
    nh = getattr(node, "note_html", None)
    if nh:
        lowered = nh.lower()
        has_media = (
            "<img" in lowered
            or "<video" in lowered
            or "<audio" in lowered
            or "<embed" in lowered
            or "<svg" in lowered
        )
        if not has_media:
            stripped = re.sub(r"<[^>]+>", "", nh).strip()
            if not stripped:
                node.note_html = None
    for c in getattr(node, "children", None) or []:
        _cleanup_empty_note_wrappers(c)


def load(path: str | Path) -> MindMap:
    # `read_map_text` transparently handles both encrypted and legacy
    # plaintext .smmap files — the loader doesn't need to care which
    # format the file is in.
    from synmind.core.file_format import read_map_text
    raw = read_map_text(path)
    data = json.loads(raw)
    version = data.get("version", 1)
    # A file written by a newer build is loaded best-effort rather than
    # rejected: the on-disk format is purely ADDITIVE and every field below is
    # read via `.get(key, default)` with unknown keys ignored, so a
    # forward-version file degrades gracefully (you just don't get fields this
    # build doesn't know about). Hard-failing here only blocked otherwise-
    # loadable maps — e.g. an AI-generated file tagged with a higher version.
    if version > FILE_VERSION:
        try:
            import logging
            logging.getLogger("synmind").info(
                "Loading map file version %s (this build supports up to %s) "
                "best-effort.", version, FILE_VERSION)
        except Exception:
            pass
    # Edit mode. Prefer the explicit `edit_mode`; for legacy files that
    # only carry the boolean `editable`, a False maps to the fully-locked
    # state so a previously-locked map stays locked. Keep this tuple in
    # step with `MapCanvas.EDIT_MODES` — an unlisted mode silently
    # degrades to editable/locked_strong, which is how a new level can
    # look like it "doesn't persist".
    _raw_mode = data.get("edit_mode")
    if _raw_mode in (
        "editable", "locked_weak", "locked_strong", "locked_sealed",
    ):
        _edit_mode = str(_raw_mode)
    else:
        _edit_mode = (
            "editable" if bool(data.get("editable", True)) else "locked_strong"
        )
    mm = MindMap(
        title=data.get("title", "Untitled"),
        theme_name=data.get("theme_name", "dark"),
        layout_style=data.get("layout_style", "tidy_branched"),
        line_style=data.get("line_style", "curved"),
        line_thickness=float(data.get("line_thickness", 2.0)),
        edge_anchor_mode=(
            data.get("edge_anchor_mode")
            if data.get("edge_anchor_mode") in ("nearest", "layout")
            else "nearest"
        ),
        show_edited_date=bool(data.get("show_edited_date", False)),
        # isinstance check, not str(t): str(None) is the truthy "None",
        # so a null entry in a hand-edited file became a tag literally
        # named None.
        custom_tags=[
            t.strip() for t in (data.get("custom_tags") or [])
            if isinstance(t, str) and t.strip()
        ],
        map_node_fill_color=_valid_hex(data.get("map_node_fill_color")),
        map_node_text_color=_valid_hex(data.get("map_node_text_color")),
        map_text_color_auto=bool(data.get("map_text_color_auto", False)),
        priority_node_colors=bool(data.get("priority_node_colors", False)),
        working_map_fit_to_view=bool(
            data.get("working_map_fit_to_view", False)
        ),
        auto_adjust_enabled=bool(data.get("auto_adjust_enabled", True)),
        movement_placement=str(
            data.get("movement_placement", "middle") or "middle"
        ),
        scale_mode=str(data.get("scale_mode", "fit_map") or "fit_map"),
        pause_state=str(data.get("pause_state", "off") or "off"),
        auto_adjust_delayed=bool(data.get("auto_adjust_delayed", False)),
        auto_optimize_colors_on_style_change=bool(
            data.get("auto_optimize_colors_on_style_change", True)
        ),
        color_contrast_min_ratio=clamp_min_contrast(
            data.get("color_contrast_min_ratio", DEFAULT_MIN_CONTRAST)
        ),
        display_mode=data.get("display_mode", "standard"),
        follow_depth=int(data.get("follow_depth", 2)),
        follow_depth_above=int(data.get("follow_depth_above", 1)),
        follow_unbounded_above=bool(data.get("follow_unbounded_above", False)),
        follow_unbounded_below=bool(data.get("follow_unbounded_below", False)),
        recall_depth=max(1, int(data.get("recall_depth", 2))),
        recall_depth_above=max(0, int(data.get("recall_depth_above", 1))),
        auto_center_on_selection=bool(data.get("auto_center_on_selection", True)),
        # str() would turn a null into the literal "None", which parses
        # as no version at all but reads like one in a warning dialog.
        saved_by_version=str(data.get("app_version") or ""),
        auto_center_left=bool(data.get("auto_center_left", False)),
        auto_center_delayed=bool(data.get("auto_center_delayed", False)),
        no_view_move_on_end_node=bool(
            data.get("no_view_move_on_end_node", False)
        ),
        auto_toggles=bool(data.get("auto_toggles", False)),
        auto_move_enabled=bool(data.get("auto_move_enabled", True)),
        fit_descendants_only=bool(data.get("fit_descendants_only", False)),
        fit_descendants_depth=int(data.get("fit_descendants_depth", 0) or 0),
        scale_auto_delayed=bool(data.get("scale_auto_delayed", False)),
        follow_fit_to_view=bool(data.get("follow_fit_to_view", False)),
        standard_max_depth=int(data.get("standard_max_depth", 0)),
        standard_drag_locked=bool(data.get("standard_drag_locked", False)),
        tag_map_tag=str(data.get("tag_map_tag", "") or ""),
        procedures=_clean_procedures(data.get("procedures")),
        procedure_map_name=str(data.get("procedure_map_name", "") or ""),
        procedure_map_depth=max(
            0, int(data.get("procedure_map_depth", 1) or 1)
        ),
        tag_map_depth=int(data.get("tag_map_depth", 1)),
        todo_map_depth=int(data.get("todo_map_depth", 1)),
        bookmark_map_depth=int(data.get("bookmark_map_depth", 1)),
        bookmark_map_depth_above=max(0, int(data.get("bookmark_map_depth_above", 0))),
        alias_map_depth=max(0, int(data.get("alias_map_depth", 0))),
        alias_map_depth_above=max(0, int(data.get("alias_map_depth_above", 2))),
        alias_focus_id=(data.get("alias_focus_id") or None),
        bookmark_panel_jump_on_click=bool(data.get("bookmark_panel_jump_on_click", False)),
        node_shortcuts=_clean_node_shortcuts(data.get("node_shortcuts")),
        tag_shortcuts=_clean_node_shortcuts(data.get("tag_shortcuts")),
        saved_searches=_clean_saved_searches(data.get("saved_searches")),
        saved_search_shortcuts=_clean_node_shortcuts(
            data.get("saved_search_shortcuts")
        ),
        control_panel_saved_searches=[
            str(s)
            for s in (data.get("control_panel_saved_searches") or [])
            if isinstance(s, (str, int))
        ],
        saved_layout_shortcuts=_clean_node_shortcuts(
            data.get("saved_layout_shortcuts")
        ),
        node_shortcut_layouts=_clean_remembered_layouts(
            data.get("node_shortcut_layouts")
        ),
        bookmark_layouts=_clean_remembered_layouts(
            data.get("bookmark_layouts")
        ),
        open_on_click_when_paused=bool(
            data.get("open_on_click_when_paused", False)
        ),
        auto_ocr_on_close=bool(data.get("auto_ocr_on_close", False)),
        auto_pause_levels=(
            max(0, min(3, int(data.get("auto_pause_levels") or 0)))
            if "auto_pause_levels" in data
            # Maps saved by 2.6.10.11 / .12 used two bools.
            else (
                2 if data.get("auto_pause_bottom_levels")
                else 1 if data.get("auto_pause_bottom_level")
                else 0
            )
        ),
        open_on_select=bool(data.get("open_on_select", False)),
        shortcut_manager_items=[
            {"kind": str(it.get("kind")),
             "target_id": str(it.get("target_id"))}
            for it in (data.get("shortcut_manager_items") or [])
            if isinstance(it, dict) and it.get("kind") and it.get("target_id")
        ],
        view_locked=bool(data.get("view_locked", False)),
        working_map_show_all=bool(data.get("working_map_show_all", False)),
        node_display_memories=_clean_display_memories(
            data.get("node_display_memories")
        ),
        recall_node_display_memories=bool(
            data.get("recall_node_display_memories", False)
        ),
        auto_beautify=bool(data.get("auto_beautify", False)),
        info_page_enabled=bool(data.get("info_page_enabled", False)),
        revise_map_depth=int(data.get("revise_map_depth", 1)),
        standard_fit_to_view=bool(data.get("standard_fit_to_view", False)),
        tag_map_fit_to_view=bool(data.get("tag_map_fit_to_view", True)),
        todo_map_fit_to_view=bool(data.get("todo_map_fit_to_view", True)),
        bookmark_map_fit_to_view=bool(data.get("bookmark_map_fit_to_view", True)),
        revise_map_fit_to_view=bool(data.get("revise_map_fit_to_view", True)),
        alias_map_fit_to_view=bool(data.get("alias_map_fit_to_view", True)),
        show_edited_date_on_hover=bool(data.get("show_edited_date_on_hover", True)),
        last_base_mode=str(data.get("last_base_mode", "standard") or "standard"),
        quick_input_target_id=data.get("quick_input_target_id"),
        archive_node_id=data.get("archive_node_id"),
        backup_node_id=data.get("backup_node_id"),
        completed_display_mode=(
            "archive"
            if str(data.get("completed_display_mode") or "original").lower()
            == "archive"
            else "original"
        ),
        hover_preview_enabled=bool(
            data.get("hover_preview_enabled", False)
        ),
        minimalist_layout=bool(data.get("minimalist_layout", False)),
        horizontal_line_length=float(
            data.get("horizontal_line_length", 60.0) or 60.0
        ),
        node_image_mode=str(data.get("node_image_mode", "node") or "node"),
        open_at=data.get("open_at", "root"),
        last_selected_id=data.get("last_selected_id"),
        open_at_node_id=data.get("open_at_node_id"),
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
        bookmarked_ids=list(data.get("bookmarked_ids") or []),
        bookmark_center_ids=[
            str(x) for x in (data.get("bookmark_center_ids") or [])
        ],
        attachments_folder=data.get("attachments_folder"),
        # Left as None = "not read yet"; the UI loads the sidecar on
        # first use. A map written by an older build still has the store
        # inline, so take it and mark it dirty to migrate it out on the
        # next save.
        node_history=(
            data.get("node_history")
            if isinstance(data.get("node_history"), dict)
            and data.get("node_history") else None
        ),
        node_history_dirty=bool(
            isinstance(data.get("node_history"), dict)
            and data.get("node_history")
        ),
        history_filter_days=(
            int(data["history_filter_days"])
            if isinstance(data.get("history_filter_days"), int)
            and not isinstance(data.get("history_filter_days"), bool)
            else None
        ),
        history_recording_enabled=bool(
            data.get("history_recording_enabled", True)
        ),
        history_max_entries_per_node=int(
            data.get("history_max_entries_per_node", 30) or 30
        ),
        history_max_age_days=(
            int(data["history_max_age_days"])
            if isinstance(data.get("history_max_age_days"), int)
            and not isinstance(data.get("history_max_age_days"), bool)
            else None
        ),
        views_auto_delete_days=(
            int(data["views_auto_delete_days"])
            if isinstance(data.get("views_auto_delete_days"), int)
            and not isinstance(data.get("views_auto_delete_days"), bool)
            else None
        ),
        backup_settings_per_machine=_load_backup_settings(data),
        ocr_languages=[
            str(L) for L in (data.get("ocr_languages") or ["en"])
            if isinstance(L, str) and L.strip()
        ] or ["en"],
        # Migration: the legacy "google_vision" engine (direct API
        # key) was retired in favor of credit-metered managed mode.
        # Old maps that used direct mode get auto-flipped here so
        # the user doesn't have to re-select on every load. The
        # underlying behavior is closer to what they intended anyway
        # (still Google Vision, just billed via credits).
        ocr_engine=(
            "managed_google_vision"
            if (data.get("ocr_engine") or "").lower() == "google_vision"
            else str(data.get("ocr_engine") or "rapidocr")
        ),
        review_timer_seconds=int(
            data.get("review_timer_seconds") or 0
        ),
        last_review_test_mode=str(
            data.get("last_review_test_mode") or "untimed"
        ),
        review_timer_multiply_by_masks=bool(
            data.get("review_timer_multiply_by_masks") or False
        ),
        review_filter_overdue=bool(
            data.get("review_filter_overdue") or False
        ),
        review_kind_filter=str(
            data.get("review_kind_filter") or "both"
        ).lower() if str(
            data.get("review_kind_filter") or "both"
        ).lower() in ("both", "nodes", "notes") else "both",
        review_correct_threshold_enabled=bool(
            data.get("review_correct_threshold_enabled") or False
        ),
        review_correct_threshold_pct=max(
            1, min(100, int(
                data.get("review_correct_threshold_pct") or 80
            ))
        ),
        sr_intervals_days=[
            float(x) for x in (data.get("sr_intervals_days") or [])
            if isinstance(x, (int, float))
        ],
        sr_correct_multiplier=float(
            data.get("sr_correct_multiplier") or 1.0
        ),
        sr_use_hours=bool(
            data.get("sr_use_hours") or False
        ),
        filter_node_id=data.get("filter_node_id"),
        todo_filter_mode=(
            "all" if str(data.get("todo_filter_mode") or "off").lower()
            == "all"
            else "overdue" if str(data.get("todo_filter_mode") or "off").lower()
            == "overdue"
            else "off"
        ),
        recent_filter_ids=list(
            data.get("recent_filter_ids", []) or []
        ),
        remembered_layouts=_clean_remembered_layouts(
            data.get("remembered_layouts")
        ),
        saved_remembered_layouts=[
            dict(e) for e in (data.get("saved_remembered_layouts") or [])
            if isinstance(e, dict)
        ],
        memorized_views=_clean_memorized_views(data.get("memorized_views")),
        shortcut_palette_state=dict(
            data.get("shortcut_palette_state") or {}
        ),
        control_panel_state=dict(
            data.get("control_panel_state") or {}
        ),
        control_panel_favorites=list(
            data.get("control_panel_favorites") or []
        ),
        menu_bar_items=list(
            data.get("menu_bar_items") or []
        ),
        button_states=dict(
            data.get("button_states") or {}
        ),
        machine_ui_settings={
            str(k): dict(v)
            for k, v in (data.get("machine_ui_settings") or {}).items()
            if isinstance(v, dict)
        },
        search_include_archives=bool(
            data.get("search_include_archives", False)
        ),
        note_editor_geometry=str(
            data.get("note_editor_geometry") or ""
        ),
        note_editor_maximized=bool(
            data.get("note_editor_maximized") or False
        ),
        review_toolbar_geometry=str(
            data.get("review_toolbar_geometry") or ""
        ),
        calendar_view_mode=str(
            data.get("calendar_view_mode") or "month"
        ).lower(),
        calendar_show_overdue=bool(
            data.get("calendar_show_overdue", True)
        ),
        calendar_show_today_due=bool(
            data.get("calendar_show_today_due", True)
        ),
        calendar_show_upcoming=bool(
            data.get("calendar_show_upcoming", True)
        ),
        ocr_trigger_mode=(
            str(data.get("ocr_trigger_mode") or "immediate").lower()
            if str(data.get("ocr_trigger_mode") or "immediate").lower()
            in ("immediate", "manual", "on_close", "daily")
            else "immediate"
        ),
        ocr_last_daily_run=float(data.get("ocr_last_daily_run") or 0.0),
        ocr_run_in_background=bool(data.get("ocr_run_in_background") or False),
        badge_position=(
            str(data.get("badge_position") or "right").lower()
            if str(data.get("badge_position") or "right").lower()
            in ("right", "below")
            else "right"
        ),
        badge_visibility=(
            {str(k): bool(v)
             for k, v in data.get("badge_visibility", {}).items()}
            if isinstance(data.get("badge_visibility"), dict) else {}
        ),
        view_dwell_ms=int(data.get("view_dwell_ms", 5000) or 5000),
        follow_reapply_ms=int(data.get("follow_reapply_ms", 700) or 700),
        # Default True so the calendar feels useful out of the box
        # when toggled on. Legacy files (no field) get the default.
        calendar_show_todos=bool(
            data.get("calendar_show_todos", True)
        ),
        calendar_show_reviews=bool(
            data.get("calendar_show_reviews", True)
        ),
        calendar_week_start=(
            str(data.get("calendar_week_start") or "monday").lower()
            if str(data.get("calendar_week_start") or "monday").lower()
            in ("monday", "sunday")
            else "monday"
        ),
        google_sync_scope=(
            str(data.get("google_sync_scope") or "all")
            if str(data.get("google_sync_scope") or "all")
            in ("all", "overdue")
            else "all"
        ),
        google_sync_priority_filter=bool(
            data.get("google_sync_priority_filter", False)
        ),
        google_sync_priority_max_level=(
            int(data["google_sync_priority_max_level"])
            if str(data.get("google_sync_priority_max_level"))
            in ("1", "2", "3", "4", "5")
            else 5
        ),
        google_sync_on_close=bool(data.get("google_sync_on_close", False)),
        google_calendar_known_event_ids=(
            [str(v) for v in data["google_calendar_known_event_ids"]]
            if isinstance(data.get("google_calendar_known_event_ids"), list)
            else []
        ),
        google_calendar_last_synced_calendar_id=data.get(
            "google_calendar_last_synced_calendar_id"
        ),
        search_target=(
            str(data.get("search_target") or "subtree_title")
            if str(data.get("search_target") or "subtree_title")
            in ("subtree_title", "map_title", "subtree_all", "map_all")
            else "subtree_title"
        ),
        search_sort=(
            str(data.get("search_sort") or "default")
            if str(data.get("search_sort") or "default")
            in ("default", "created", "edited", "name")
            else "default"
        ),
        search_history=[
            str(s) for s in (data.get("search_history") or [])
            if isinstance(s, str) and s.strip()
        ],
        show_trash_widget=bool(data.get("show_trash_widget", True)),
        editable=(_edit_mode == "editable"),
        edit_mode=_edit_mode,
        sketch_finger_input_enabled=bool(
            data.get("sketch_finger_input_enabled", True)
        ),
        sketch_palm_rejection_enabled=bool(
            data.get("sketch_palm_rejection_enabled", True)
        ),
        review_show_mode=(
            str(data.get("review_show_mode", "relationships") or "relationships")
            if str(data.get("review_show_mode", "relationships") or "relationships")
            in ("relationships", "review_only")
            else "relationships"
        ),
        show_topic_label_on_descendants=bool(
            data.get("show_topic_label_on_descendants", False)
        ),
        search_panel_auto_close=bool(
            data.get("search_panel_auto_close", False)
        ),
        search_panel_auto_close_tabs={
            str(k): bool(v)
            for k, v in (data.get("search_panel_auto_close_tabs") or {}).items()
        },
        todo_panel_auto_close_tabs={
            str(k): bool(v)
            for k, v in (data.get("todo_panel_auto_close_tabs") or {}).items()
        },
        panel_auto_close={
            str(k): bool(v)
            for k, v in (data.get("panel_auto_close") or {}).items()
        },
        panel_sort_order={
            str(k): str(v)
            for k, v in (data.get("panel_sort_order") or {}).items()
            if isinstance(v, str)
        },
        todo_panel_filter=(
            data.get("todo_panel_filter")
            if data.get("todo_panel_filter")
            in ("all", "overdue", "recurring", "completed")
            else "all"
        ),
        panel_last_tab={
            str(k): str(v)
            for k, v in (data.get("panel_last_tab") or {}).items()
            if isinstance(v, str)
        },
        # "individual" (opt in one node at a time from its R bullet) was
        # retired in favour of a single map-wide switch. A map saved with
        # it wanted remembered layouts to load, so it becomes "whole"
        # rather than "off" — silently switching the feature off on load
        # would look like the map had lost a setting.
        remembered_display_mode=_clean_remembered_mode(
            data.get("remembered_display_mode")
        ),
        auto_layers_on_select=bool(data.get("auto_layers_on_select", True)),
        trash=_load_trash(data.get("trash")),
        navigation_history=(
            dict(data["navigation_history"])
            if isinstance(data.get("navigation_history"), dict)
            else {}
        ),
        root=_dict_to_node(data["root"]),
    )
    # Wipe any phantom empty-note wrappers left behind by the Info
    # Page commit bug. Real notes (with at least one printable
    # character after tag-strip) are untouched. Also covers trashed
    # subtrees so a restore later doesn't bring the phantom note back.
    _cleanup_empty_note_wrappers(mm.root)
    for te in (mm.trash or []):
        _cleanup_empty_note_wrappers(getattr(te, "node", None))
    return mm


def _load_trash(raw) -> list:
    """Rebuild MindMap.trash from saved JSON. Tolerant of missing /
    malformed entries — drops anything we can't reconstruct rather
    than failing the whole load. Returns a fresh list (empty when
    the field is absent, which is the case for legacy files)."""
    from synmind.core.model import TrashEntry

    if not isinstance(raw, list):
        return []
    out: list = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        node_data = entry.get("node")
        if not isinstance(node_data, dict):
            continue
        try:
            node = _dict_to_node(node_data)
        except Exception:
            continue
        out.append(
            TrashEntry(
                node=node,
                parent_id=str(entry.get("parent_id", "") or ""),
                child_index=int(entry.get("child_index", -1) or -1),
                deleted_at=str(entry.get("deleted_at", "") or ""),
                display_text=str(entry.get("display_text", "") or ""),
            )
        )
    return out
