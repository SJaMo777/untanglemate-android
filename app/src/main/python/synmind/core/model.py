"""Data model for mind maps. UI-agnostic; pure Python."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterator
from uuid import uuid4


def _new_id() -> str:
    return uuid4().hex


def _now_iso() -> str:
    """Current UTC time as ISO-8601 with seconds precision."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def current_machine_id() -> str:
    """Stable identifier for the computer the app is running on. Used
    to scope per-machine settings (currently just backup config) so
    the same .smmap behaves correctly when synced across multiple
    machines via Dropbox / OneDrive / git. Falls back to "unknown"
    if hostname lookup fails."""
    import platform
    name = platform.node() or ""
    return name.strip() or "unknown"


def _default_backup_entry() -> dict:
    """Fresh per-machine backup settings. Mirrors the old flat
    `backup_*` fields on MindMap; folder defaults to "next to the map
    file", every cadence is off, attachments are copied, nothing is
    auto-deleted, and no cadence has fired yet."""
    return {
        "folder": None,
        "hourly": False,
        "daily": False,
        "weekly": False,
        "monthly": False,
        "copy_files": True,
        "retention": "never",
        "last_hourly_at": None,
        "last_daily_at": None,
        "last_weekly_at": None,
        "last_monthly_at": None,
    }


@dataclass
class Node:
    text: str = "New Node"
    id: str = field(default_factory=_new_id)
    x: float = 0.0
    y: float = 0.0
    image_data: str | None = None
    image_format: str | None = None
    fill_color: str | None = None
    # The node's FRAME. Separate from fill_color so the outline can be
    # coloured independently of the inside - a light node with a strong
    # border reads very differently from a filled one. None means the
    # theme's stroke, exactly as None fill_color means the theme's fill.
    #
    # Overridden at paint time by the states that already commandeer the
    # stroke to mean something (drop target, "working", export badge);
    # those are transient signals and outrank a stored preference.
    border_color: str | None = None
    collapsed: bool = False
    edge_thickness: float | None = None
    link_target_id: str | None = None
    # Cross-map link reference. When not None, this node is a link to a node
    # in a different map file. Format: {"map_path": str, "node_id": str}.
    # When set, link_target_id should be None (internal link takes precedence).
    # Clicking this node opens the target map + selects the target node.
    cross_map_link: dict | None = None
    tags: list[str] = field(default_factory=list)
    review_marked: bool = False
    review_step: int = 0
    review_due_at: str | None = None
    # Sibling of google_event_id (further below, next to todo_due_at) —
    # this node's REVIEW due date is a separate sync source from its
    # TODO due date (the Calendar panel already treats them
    # independently — calendar_show_todos/calendar_show_reviews mute
    # either one on its own), so a node with both gets two independent
    # Google events, each tracked by its own id.
    google_review_event_id: str | None = None
    # A short hash of (title, due date) as of the last successful push
    # of the REVIEW source above — lets the sync engine tell "unchanged,
    # do nothing" apart from "changed, needs an update" without an
    # extra Calendar API round-trip per node on every sync. See
    # synmind/integrations/google_calendar/sync.py's _content_hash.
    google_review_event_synced_hash: str | None = None
    # Historic grading counters for the Results tab. Bumped on every
    # Y / N answer through apply_review_answer; persisted with the
    # node. % correct = correct / (correct + wrong) when (correct +
    # wrong) > 0 — see SortKey in style_panel.
    review_correct_count: int = 0
    review_wrong_count: int = 0
    # ISO timestamp of the most recent Y / N grade on the NODE
    # review (notes use note_review_due_at on the same schema). None
    # means the node has never been tested.
    review_last_tested_at: str | None = None
    # Independent review-spaced-repetition state for the node's NOTE.
    # A node can have its own review mark (children get redacted) AND
    # a note review mark (highlights in the note get redacted) running
    # on parallel schedules. Fields mirror the node-level ones above.
    note_review_marked: bool = False
    note_review_step: int = 0
    note_review_due_at: str | None = None
    # ...including the grading counters. These were missing while the
    # node-level ones above existed, so apply_note_review_answer
    # rescheduled the card and recorded nothing — and the Results tab,
    # which filters on a non-zero correct+wrong, could never show a note
    # test. Absent fields, not a lost write: history before this change
    # does not exist to recover.
    note_review_correct_count: int = 0
    note_review_wrong_count: int = 0
    note_review_last_tested_at: str | None = None
    todo_marked: bool = False
    todo_due_at: str | None = None
    # Recurrence rule. None = one-shot (current default — marking
    # complete unmarks the todo entirely). Set to a dict to make the
    # todo repeat: completing it advances todo_due_at to the next
    # scheduled occurrence instead of unmarking.
    #
    # Schema (see synmind/core/todo_recurrence.py for details):
    #   {"kind": "weekly",        "every": int, "weekday": 0..6}
    #   {"kind": "monthly",       "every": int, "day": 1..31}
    #   {"kind": "yearly",        "month": 1..12, "day": 1..31}
    #   {"kind": "interval_days", "days": int}  # anchored on completion
    todo_recurrence: dict | None = None
    # Google Calendar's own id for the event this node's TODO due date
    # last pushed to the dedicated "UnTangleMate" calendar (see
    # synmind/integrations/google_calendar/). None until the first
    # successful sync creates one. Also the id the sync engine embeds
    # back into the Google event's extendedProperties.private so the
    # two sides can be matched even if this field were ever lost.
    google_event_id: str | None = None
    # A short hash of (title, due date) as of the last successful push
    # of the TODO source above — see google_review_event_synced_hash's
    # comment (next to review_due_at) for why this exists.
    google_event_synced_hash: str | None = None
    # Priority bucket for this todo. Defaults to MEDIUM when None,
    # matching the user's "unmarked = medium" rule — keeps legacy
    # maps + new todos in the same bucket without forcing a
    # migration. Sort order is URGENT < HIGH < MEDIUM < LOW (lower
    # number = more urgent). Only meaningful when todo_marked.
    todo_priority: str | None = None
    # General priority label 1–5 (independent of todo_priority) — shown as a
    # numbered bullet on the node. None = no priority set.
    priority_level: int | None = None
    # Knowledge-maturity level of this node's content, 0 = unset, then
    # 1 Seed, 2 Growing, 3 Reference, 4 Expert, 5 Master. Shown as a
    # colour-graded bullet. Independent of priority / completion.
    maturity: int = 0
    # Evidence basis of this node's content, 0 = unset, then
    # 1 Guideline-supported, 2 High-quality literature, 3 Personal
    # experience, 4 Hypothesis/opinion, 5 Needs verification. Shown as a
    # distinct square bullet, independent of maturity.
    evidence: int = 0
    # Marks this node as the root of a "medical" branch. Every node in the
    # subtree counts as medical: new nodes added under it default their
    # evidence to 5 (Needs verification) when unset.
    is_medical_root: bool = False
    # Id of the note node whose sketch this node was dragged out of. Set on
    # the TOP alias created by dragging a sketch's chip hierarchy to the map;
    # drives the "S" badge whose click re-opens that host note's sketch.
    sketch_host_id: str | None = None
    # ISO timestamp when the node was marked "done" / "completed". None
    # means not completed. Distinct from `todo_marked` — a node can be
    # completed WITHOUT ever having been a ToDo, and completing a ToDo
    # sets this timestamp (in addition to unmarking `todo_marked` for
    # one-shot todos). User-settable via right-click; hover on the C
    # badge reveals the timestamp.
    completed_at: str | None = None
    # Manual completion-rate "bullet": one of 0/20/40/60/80/100 (percent),
    # or None for "no bullet". Independent of `todo_marked`, but todo nodes
    # always surface the bullet (defaulting the shown value to 0% when this
    # is None) so a rate can be picked; non-todo nodes only show it once a
    # rate is explicitly added. Marking a node Completed forces this to 100.
    completion_rate: int | None = None
    note_html: str = ""
    # Per-note editing lock (independent of the map-wide edit_mode).
    # When True the note editor opens read-only — text can still be
    # selected and copied, but not edited — to prevent accidental edits
    # (e.g. stray taps on a tablet). Toggled by the note editor's own
    # Lock button; each note carries its own state.
    note_locked: bool = False
    # Collapsible sections in the note. Boundaries live in the HTML as
    # `<!--syn-sec-start:UUID-->` / `<!--syn-sec-end:UUID-->` comments so
    # they survive edits above them. Keys here are the section UUIDs;
    # values are True when the section is currently collapsed (only its
    # first line shows). Sections whose markers no longer exist in the
    # HTML are pruned on next save. Empty dict on legacy notes.
    note_sections_collapsed: dict[str, bool] = field(default_factory=dict)
    # Snapshot of `note_sections_collapsed` captured right before the
    # user hits "Show all" or "Hide all", so the "Recall" toolbar button
    # can restore the previous mixed layout. Empty dict = nothing to
    # recall yet.
    note_sections_recall: dict[str, bool] = field(default_factory=dict)
    # Comments attached to highlighted spans inside the note. Qt strips
    # every custom span marker (UserProperty, anchorNames, attributes,
    # toolTip) on the toHtml/setHtml roundtrip, so a comment can't ride
    # inside the char format — it lives here instead, anchored to the
    # span by character offset with a `quote` fallback for re-anchoring
    # after edits. Each entry:
    #   {"id": str, "start": int, "end": int, "text": str, "quote": str}
    # `start`/`end` are document character offsets (end exclusive);
    # `quote` is the highlighted text at save time; `text` is the
    # comment body. Comment content is folded into the search haystack
    # (see advanced_search) so it's findable in the map search. Empty
    # list on legacy notes. Editable even when the note/map is locked.
    note_comments: list[dict] = field(default_factory=list)
    # Auto-export settings for this node's subtree. Empty dict = not
    # configured. When enabled, the Map Style → Exports tab and the
    # node's right-click "Export → Sync Now" write the node + all its
    # descendants to `path` (a folder) in `format` (html / pdf / word).
    # `overwrite` clears the folder's contents first so a re-sync fully
    # replaces stale content (an update). Fields:
    # `sync_on_close` re-runs THIS export automatically as the map closes.
    #   {"enabled": bool, "path": str, "format": "html"|"pdf"|"word",
    #    "overwrite": bool, "sync_on_close": bool,
    #    "last_synced_at": str|None}
    auto_export: dict = field(default_factory=dict)
    # When True, this node AND its descendants are omitted from any auto-export
    # / sync of an ancestor's subtree — they still show on the map, but not in
    # the exported document. Shown on the node as a crossed-out "E" badge.
    export_excluded: bool = False
    # PowerPoint export only (see synmind/core/pptx_export.py). By
    # default a node only gets its own slide when it has children (it
    # is a "branch"/topic); this forces ANY node — including a
    # childless leaf — to be promoted to its own slide too. Set from
    # the node's right-click PowerPoint submenu.
    ppt_slide_topic: bool = False
    # PowerPoint export only. When this node becomes a slide (either
    # because it has children or because `ppt_slide_topic` is set),
    # embed its own file attachments (images) on that slide. Off by
    # default — attachments are otherwise skipped in PPTX export, since
    # unlike Word/PDF a slide has limited room and most attachments
    # would just overflow it.
    ppt_include_attachments: bool = False
    # Last cursor position inside the note editor, persisted across
    # close → reopen so the user lands where they were last typing.
    # None = no record (new note or never opened) → cursor lands at
    # the start of the document.
    note_cursor_position: int | None = None
    # Timestamp of the last note edit specifically. Separate from
    # `updated_at` (which fires for any node mutation) so the History
    # panel can list note edits as their own entries.
    note_updated_at: str | None = None
    # Timestamp of the last time the user dwelt on this node for more
    # than 5 seconds while it was selected. Drives the History panel's
    # "Recent Views" tab. Stamped by `MapCanvas._record_view_dwell`
    # when a per-selection 5-second QTimer fires AND the same node is
    # still selected — quick clicks while panning around aren't
    # counted. None means the node has never been dwelt on.
    last_viewed_at: str | None = None
    # Per-note editor background color override. None = use the theme's
    # editor_bg. Set via the note editor's right-click menu so the user
    # can switch to e.g. white when pasted text has hard-coded dark
    # colors that don't read against the dark theme background.
    note_background_color: str | None = None
    # OCR text cache for inline images in this note. Keys are SHA-256
    # hex digests of the raw (decoded) image bytes; values are the
    # extracted text (newline-joined detected blocks). Populated lazily
    # by the OCR worker. SearchPanel's text-mode search appends every
    # value to the note's plaintext so OCR'd content becomes
    # discoverable via Ctrl+F. Hash-based keys mean an image pasted
    # twice is OCR'd once and re-inserts of the same image hit the
    # cache instantly.
    image_ocr_text: dict[str, str] = field(default_factory=dict)
    # Maps an embedded sketch image's SHA-256 digest → the persistent
    # first-class sketch id it was flattened from, so re-opening the image
    # loads the EDITABLE sketch document (strokes, node chips, connections)
    # instead of annotating a static picture.
    image_sketch_ids: dict[str, str] = field(default_factory=dict)
    # Native-text cache for PDFs inserted as card+viewer entries. Keys
    # are the PDF's basename in the attachments folder (the same key
    # the synmind-pdf: link uses); values are the page-joined plain
    # text extracted via QPdfDocument.getAllText. Image-only PDFs
    # extract as empty — for those, OCR is the only path (future
    # work). Searchable through the same plaintext aggregation as
    # image_ocr_text.
    pdf_text_cache: dict[str, str] = field(default_factory=dict)
    # Extracted text from FILES attached to this node (Alt+I / drag-and-
    # drop / right-click → Attach File…). Keyed by attachment basename
    # (same key the `attachments` list stores). Values are: native PDF
    # text via QPdfDocument.getAllText for .pdf, OCR engine output for
    # image extensions, empty string for other types. Populated by
    # `extract_text_for_attachment` when a file is attached; consumed
    # by SearchPanel so Ctrl+F finds nodes whose attached docs contain
    # the query string. Note: pdf_text_cache covers PDFs embedded INTO
    # notes via the editor; attachment_text covers PDFs/images in the
    # node's attachments list. They overlap conceptually but have
    # different lifecycles, so they're kept separate.
    attachment_text: dict[str, str] = field(default_factory=dict)
    # basename -> "<mtime_ns>:<size>" of the attached file as it was when
    # its text was last extracted. Lets the on-close auto-OCR (and the
    # "pending" count) notice that the file has been edited since, and
    # read it again. Missing entry = no baseline yet (never treated as
    # changed).
    attachment_stamps: dict[str, str] = field(default_factory=dict)
    # Per-image recall cover regions. Keyed by sha256(image bytes);
    # value is a list of {x, y, w, h} dicts in source-bitmap pixel
    # coordinates (so the regions stay aligned even when the user
    # resizes the image in the editor). Only images that have at
    # least one region defined participate in recall tests — those
    # rectangles get painted gray during recall, the rest of the
    # image stays visible. Images with no regions stay fully
    # visible. Edit via right-click → "Edit recall regions…".
    image_recall_regions: dict[str, list[dict]] = field(
        default_factory=dict
    )
    # Character ranges in node.text that get masked during a Recall
    # test. Each entry is [start, end] (end-exclusive, 0-indexed into
    # the title string). Nodes with at least one range AND a Review
    # mark (R badge) feed into the recall queue alongside note / image
    # recall. Edit via right-click → "Edit title recall regions…".
    title_recall_regions: list[list[int]] = field(default_factory=list)
    # External URL / file / folder attached to this node. Double-clicking
    # the node opens it via QDesktopServices (or os.startfile on Windows
    # for local paths). None means no link attached.
    external_link: str | None = None
    # If set, this node is an ALIAS of another node (the "master") with the
    # given id. The alias has its own id and position, but its displayed
    # text / note / children are the master's. Editing the alias routes
    # mutations to the master. None means this is a regular node.
    alias_of: str | None = None
    # FUNCTIONS. When set, this node IS a function — the id of the
    # registered function it runs (see synmind/core/functions). Its child
    # nodes are the function's settings and their child nodes are the
    # values, so the map itself is the configuration; there is no
    # separate store to keep in step with it.
    function_id: str | None = None
    # On a SETTING node, the key of the setting it holds. Matched before
    # the node's text so renaming "Source files" to something friendlier
    # doesn't detach it from what it configures.
    function_setting: str | None = None
    # A function node's settings that are NOT nodes: {key: text}. Only
    # LIST settings (the source and object paths) stay on the map, where
    # having one node per entry is what makes them readable and editable.
    # Everything else — a direction, a yes/no, an interval — is one value
    # with a fixed set of possibilities, and a node per value buried the
    # function under two dozen children that only ever got set from a
    # menu anyway. Stored as text for the same reason the value nodes
    # were: the .smmap stays readable, and a renumbered choice list can
    # never silently change what a function does.
    function_values: dict = field(default_factory=dict)
    # If this node was moved here via Alt+Z Archive, stores the id of
    # its previous parent so a later "Return to original parent" can
    # restore it. Tracking is by id, not position — if the original
    # parent gets moved elsewhere in the map, the return still finds
    # it. None means the node has never been archived (or was already
    # returned / re-archived from somewhere new).
    archived_from_parent_id: str | None = None
    # Backup copies. Set on the COPY that lives under the map's backup
    # node, never on the original — a backup is a copy, so the original
    # is untouched and carries no mark.
    #
    # `backed_up_from_parent_id` is where the original sat when the copy
    # was taken, and is what Recover puts the restored node back under.
    # By id rather than position, like `archived_from_parent_id`, so a
    # parent that has since moved is still found.
    backed_up_from_parent_id: str | None = None
    # When the copy was taken, ISO format. Doubles as the "this IS a
    # backup entry" flag, since a backup taken at an unknown time is not
    # a thing that can happen — both are written together.
    backed_up_at: str | None = None
    # True when the node was auto-moved to the archive because it was
    # marked completed AND the map's `completed_display_mode` was
    # "archive". Distinguishes an automatic completion-archive from a
    # manual Alt+Z archive so uncompleting can restore the auto-moved
    # node without disturbing user-archived items.
    auto_archived_on_completion: bool = False
    # Filenames (basenames only) of files attached to this node. Files
    # live in the map's attachment folder — see MindMap.attachments_folder
    # for how that resolves. Stored as basenames so renaming / moving the
    # whole attachment folder doesn't break references.
    attachments: list[str] = field(default_factory=list)
    # Manual body width override, in scene pixels. None means "auto"
    # (compute from content). Set via right-click "Set node width…" or
    # drag on the node's right edge — the node stays at that width
    # across sessions until the user clears it.
    manual_width: float | None = None
    # Per-node text styling. None / False means "use the theme default".
    text_bold: bool = False
    text_italic: bool = False
    text_underline: bool = False
    text_strikethrough: bool = False
    text_font_size: int | None = None
    # Highlight color = background fill applied to the text glyphs only
    # (not the whole node body — that's `fill_color`). Hex string.
    text_highlight: str | None = None
    # Foreground (font) color. When None, the theme's text color is used.
    # Hex string. Only applies to plain-text nodes; rich-text (text_html)
    # nodes carry their own per-span colors via the HTML.
    text_color: str | None = None
    # Paragraph alignment for the node's title text. "center" is the
    # historical default (and what unset nodes used before this field
    # existed); "left" and "right" are the new options surfaced via
    # the right-click Text Style menu. Plain-text nodes apply this
    # directly; rich-text (text_html) nodes ignore it because their
    # alignment lives in the HTML.
    text_alignment: str = "center"
    # Optional rich-text representation of the body text. When None, the
    # node renders `text` as plain text with the per-node text_* flags
    # (bold / italic / etc.) applied uniformly. When set (HTML fragment
    # produced by the inline editor's QTextEdit), `text` stays as the
    # plain-text fallback for search / OCR / exports while the renderer
    # paints the rich version via QTextDocument. Legacy maps load with
    # this None and behave exactly as before.
    text_html: str | None = None
    # Per-node overrides for the "Obey Node Rules" Node-Image-Display
    # mode. In any other mode these flags are ignored — the map-level
    # mode dictates what shows on every node uniformly. In Obey mode,
    # setting True hides the corresponding image just for this node.
    hide_node_image: bool = False
    hide_note_image: bool = False
    # First-class sketch attached to this node. When non-None, points
    # to a sketch document on disk at
    #     <map-dir>/attachments/sketches/<sketch_id>/sketch.json
    # (see synmind.core.sketch.sketch_dir_for_map). The .smmap file
    # only stores this id — the strokes / images / PDF backgrounds
    # live in the sketch dir, keeping the map file small. None on
    # legacy nodes whose sketches are still embedded as PNG inside
    # the note HTML.
    sketch_id: str | None = None
    # OCR text extracted from this node's attached sketch, mirrored
    # from the sketch document's per-page `ocr_text` on save so the
    # Ctrl+F search index can find it without resolving sketch_dir.
    # Keyed by page id, value is the page's OCR text. Empty dict
    # when no sketch is attached or OCR hasn't been run.
    sketch_ocr_text: dict[str, str] = field(default_factory=dict)
    # "Topic" mark. When True the node carries a small T badge and
    # every descendant of this node is considered "under" this topic.
    # The canvas shows a floating topic banner (with this node's text)
    # whenever the selected / focused node is a descendant AND the
    # topic node itself isn't in the current visible set — so the user
    # always knows which topic they're working in even when the
    # ancestor scrolled off-screen / got hidden by a follow / recall
    # depth cap. Multiple topics in an ancestor chain → the CLOSEST
    # ancestor wins (the most specific topic).
    is_topic: bool = False
    # This node IS a procedure: its children are its steps, in order.
    # Set with "Make Node a Procedure". Steps are normally ALIASES of
    # nodes living elsewhere in the map (dragged into the Procedures
    # panel), so a procedure gathers existing knowledge into an order
    # without moving or copying any of it. The order in the map and the
    # order in the panel are the same thing — there is no second store.
    is_procedure: bool = False
    # Per-node "display in remembered mode" opt-in. Only consulted when
    # the map's remembered_display_mode is "individual": selecting a node
    # that has BOTH a remembered layout AND this flag set re-applies that
    # layout. Ignored in "off" / "whole" modes.
    remembered_auto: bool = False
    # "Working" mark — this node / process is still being worked on.
    # Rendered with a thick, high-contrast border so open parents show
    # at a glance which children still need attention. Listed in the
    # Working panel. Toggled by the toolbar W button and the right-click
    # menu.
    working: bool = False
    # "Forget until" date (YYYY-MM-DD) for a working node: while today is
    # BEFORE this date, the node is hidden from the date-aware Working Map
    # view (Work display mode 1). None means no snooze — always shown.
    working_forget_until: str | None = None
    # "Do after completion" list: ids of other nodes that should be turned
    # into Working nodes the moment THIS node is marked completed. Populated
    # by pasting copied nodes into the right-click Work menu's list; entries
    # can be removed there too. Stale ids (deleted nodes) are ignored.
    do_after_completion: list[str] = field(default_factory=list)
    # Work-flow membership — SEPARATE from `working` (the work status).
    # `working` says "show in the Working Map / actively being worked on";
    # `in_work_flow` says "this node is part of a Work Flow" so it appears in
    # the Work Flow Map (with a completion bullet) even before it's activated
    # as a work node. Set when a node is dragged/added into a flow or made a
    # flow top; the completion cascade still flips `working` independently.
    in_work_flow: bool = False
    # Work-flow START/FINISHED wiring. On the TOP (start) node of a flow:
    #   `workflow_name`      — the flow's name (for the START:/FINISHED: labels)
    #   `workflow_finish_id` — id of this flow's FINISHED sentinel node
    # On the FINISHED sentinel node:
    #   `workflow_finish_for` — id of the start node to auto-complete when the
    #                           finish node's incoming AND-gate is satisfied.
    workflow_name: str = ""
    workflow_finish_id: str | None = None
    workflow_finish_for: str | None = None
    # Free-form position of this node inside the Work Flow Map (Phase 2
    # editor). None = auto-placed. Stored separately from the main-map x/y.
    workflow_pos: "tuple | None" = None
    # Which work flow this node belongs to, = the START node's id. Lets a
    # node that's been dropped into the flow but not yet wired with an arrow
    # still render as a member. START tags itself; FINISHED tags its START.
    workflow_group_id: str | None = None
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)
    # Per-node child sort mode. "remembered" means the user-managed
    # order (the order `children` is stored in by default). Other
    # values reorder children at apply-mode time; `child_remembered_order`
    # snapshots the manual order so switching BACK to "remembered"
    # restores it instead of leaving the user stuck with a sort-driven
    # arrangement.
    child_sort_mode: str = "remembered"
    child_remembered_order: list[str] | None = None
    # When True, this node AND its descendants have their content / status
    # changes recorded to the map's node-history store (see
    # `core.node_history`). Surfaced as an "H" badge on every node in the
    # recorded subtree; toggled from the right-click menu. Recording scope is
    # inherited: a descendant is recorded if it OR any ancestor has this set.
    history_recording: bool = False
    children: list["Node"] = field(default_factory=list)

    def add_child(self, node: "Node") -> None:
        self.children.append(node)

    def insert_child(self, index: int, node: "Node") -> None:
        self.children.insert(index, node)

    def remove_child(self, node_id: str) -> bool:
        for i, child in enumerate(self.children):
            if child.id == node_id:
                del self.children[i]
                return True
            if child.remove_child(node_id):
                return True
        return False

    def find(self, node_id: str) -> "Node | None":
        if self.id == node_id:
            return self
        for child in self.children:
            result = child.find(node_id)
            if result is not None:
                return result
        return None

    def walk(self) -> Iterator["Node"]:
        yield self
        for child in self.children:
            yield from child.walk()

    def walk_visible(self) -> Iterator["Node"]:
        yield self
        if not self.collapsed:
            for child in self.children:
                yield from child.walk_visible()


@dataclass
class TrashEntry:
    """One node subtree that was deleted via the trash (UI-side or
    drag-to-trash). Stores enough to restore the node back to its
    original parent at its original child index. The subtree is held
    by reference — the Node tree is unattached (no parent in the
    map) once it's in the trash list."""
    node: "Node"
    # Original parent id and child index at the moment of deletion.
    # On restore we re-insert at `child_index` if it's still valid,
    # else append. If the parent is gone (also deleted / moved away),
    # the restore falls back to root.
    parent_id: str
    child_index: int
    # ISO-8601 UTC timestamp. Set by the deletion site so the trash
    # panel can sort entries by deletion order and show "X min ago"
    # style relative times if it wants to.
    deleted_at: str = field(default_factory=_now_iso)
    # Snapshot of the node's display text at the moment of deletion.
    # Cached so the trash list keeps showing a sensible label even if
    # later mutations / restores / re-deletes occur. Falls back to
    # "(empty)" when the node had no text.
    display_text: str = ""


@dataclass
class SavedSearch:
    """One persisted search definition (standard or advanced). Stored
    per-map in `MindMap.saved_searches` and surfaced in the search
    panel. Clicking re-runs the saved conditions; editing is allowed
    by re-saving over the same id.

    Two flavors share this class — discriminated by `kind`:
      - "standard": replays the legacy panel (mode + scope + text /
        tag / date range), so a saved standard search behaves like
        the user re-entering those widgets.
      - "advanced": stores the raw advanced-grammar query string
        (parsed at run time by core/advanced_search.py)."""
    id: str = field(default_factory=_new_id)
    # User-provided label. When empty, the panel shows the query
    # content as the row label instead.
    name: str = ""
    # "standard" | "advanced"
    kind: str = "standard"
    # Advanced-only: the raw query text. Reparsed on every run.
    query: str = ""
    # Standard-only fields (mirror the panel widgets):
    standard_mode: str = "text"   # "text" | "all" | "tag" | "created" | "edited"
    standard_scope: str = "map"   # "map" | "subtree"
    standard_text: str = ""
    standard_tag: str = ""
    standard_date_from: str | None = None  # ISO yyyy-mm-dd
    standard_date_to: str | None = None    # ISO yyyy-mm-dd
    # ISO timestamps for sort / "last used" hints in the panel.
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)


@dataclass
class MindMap:
    root: Node = field(default_factory=lambda: Node(text="Central Topic"))
    title: str = "Untitled"
    theme_name: str = "dark"
    layout_style: str = "tidy_branched"
    line_style: str = "curved"
    line_thickness: float = 2.0
    # "nearest" attaches each connector at whichever of the 4 side
    # midpoints of the two nodes are closest AND face each other;
    # "layout" keeps the older per-layout forced side. See
    # EdgeItem.nearest_side_anchors.
    edge_anchor_mode: str = "nearest"
    # Show each node's last-edited day on a small pill under the
    # body. Reads Node.updated_at, which every command already
    # maintains. Off by default so existing maps look unchanged.
    show_edited_date: bool = False
    # Tags the user created but hasn't applied to any node yet.
    # Tags are otherwise derived purely from node.tags, so a brand
    # new tag would vanish the instant it was created — it needs a
    # home until it's dragged onto its first node.
    custom_tags: list[str] = field(default_factory=list)
    # Map-wide node body fill / title text color. Hex strings; None means
    # "use the theme". These sit BETWEEN the per-node fill_color /
    # text_color overrides and the theme, so setting a map-wide color
    # recolors every node that hasn't been individually customized
    # without erasing the ones that have. Resolution order lives in
    # synmind/core/colors.py — don't re-derive it at call sites.
    map_node_fill_color: str | None = None
    map_node_text_color: str | None = None
    # True when the optimization pass (not the user) wrote
    # map_node_text_color. Lets a later pass release the stamp once
    # the theme no longer needs help, without ever discarding a
    # color the user picked deliberately.
    map_text_color_auto: bool = False
    # Colour every prioritised node by its priority level (1-5), fill
    # and frame together. Purely a VIEW: the colours are derived at
    # paint time by synmind/core/colors.py and never written onto the
    # nodes, so turning this off restores whatever the user had. A node
    # carrying its own fill_color keeps it - an explicit choice beats an
    # automatic rule.
    priority_node_colors: bool = False
    # Re-run the readability pass automatically after a theme or
    # map-wide color change. The pass only rewrites text that actually
    # fails the contrast floor, and it's bundled into the same undo step
    # as the change that triggered it.
    auto_optimize_colors_on_style_change: bool = True
    # WCAG contrast floor the optimization pass holds text to.
    color_contrast_min_ratio: float = 4.5
    # "standard" | "follow" | "recall" | "recall_seq"
    # | "tag_map" | "todo_map" | "bookmark_map" | "revise_map"
    display_mode: str = "standard"
    follow_depth: int = 2
    # Layers ABOVE the selected node also shown in follow mode. 0 = only
    # the selected node, 1 = parent + siblings (the traditional behavior
    # — matches the original implementation), 2 = grandparent's branch
    # leading down, etc. The walk stops at the root if depth runs out.
    follow_depth_above: int = 1
    # When True, ignore the corresponding follow_depth* cap entirely —
    # show ALL ancestors / ALL descendants in that direction. Lets the
    # user say "follow my selection but don't truncate above (or
    # below)" without needing a sentinel value on the spinner.
    follow_unbounded_above: bool = False
    follow_unbounded_below: bool = False
    # Recall mode (and recall_seq) get their OWN layer caps so the user
    # can configure how much context shows during a self-test
    # independently of their everyday Follow view. Defaults match the
    # historical Follow defaults so a map that's never touched these
    # behaves identically to before. _apply_follow_visibility reads
    # these instead of follow_depth* when display_mode is recall*.
    recall_depth: int = 2
    recall_depth_above: int = 1
    # When True, every selection change re-centers the viewport on the
    # newly-selected node — across all modes, including Standard. The
    # existing per-mode recentering (Follow re-anchors automatically)
    # still applies; this toggle just extends the same behavior to the
    # modes that normally let the user pan freely. UI lives at the top
    # of Map Style → Display.
    auto_center_on_selection: bool = True
    # When True, selecting a collapsed node with children un-collapses
    # it right there — no separate Space / Right-arrow press needed.
    # Deliberately just clears the node's OWN collapsed flag rather
    # than forcing any particular number of levels open: whatever
    # already governs how much of the subtree actually shows (Standard
    # mode's Layers Below cap, Follow's depth, etc.) still applies
    # exactly as configured, so this always opens "as far as the
    # presently set options allow" rather than overriding them. UI
    # lives in the Centre-mode dropdown (Node Display toolbar), as its
    # own checkable entry — independent of which of the five Centre
    # placements is active. Standard mode only for now, mirroring the
    # existing unconditional Free-mode auto-expand this was modeled on.
    open_on_select: bool = False
    # "Auto" master switch. When True, the display-toggle set (Auto Move,
    # Center on selection, Scale All, Scale Descendants only, Node Memory)
    # is driven automatically from the display mode instead of by the
    # user — Standard gets Auto Move + Center on, the rest off; Follow /
    # Follow+ get all of Auto Move / Center / Scale All / Scale Desc on
    # and Node Memory off. When False the user controls each toggle
    # directly (the historical behavior). Persisted per map; UI is the
    # top toggle of Map Style → Display. See canvas._apply_auto_toggle_state.
    auto_toggles: bool = False
    # Master toggle for "Move to Rules" — when True (default), all
    # auto-recentering paths (selection change, depth change, mode
    # entry, follow-mode re-anchor, scale-to-fit, auto_center_on_selection)
    # run as configured. When False, the viewport stays put unless the
    # user manually pans, zooms, or invokes an explicit recenter
    # (Shift+Alt+C / "Center map" menu / Scale-to-fit toggle). The flag
    # persists with the map and is shown in the toolbar next to the
    # display-mode indicator. Toggled from the Auto Move button
    # (Movement tab); Alt+G now belongs to Go To.
    auto_move_enabled: bool = True
    # When True, Scale-to-fit (and Shift+Alt+C / Shift+Alt+Z) fits ONLY
    # the selected node and its visible descendants rather than the
    # entire visible map. Lets the user zoom into a focused chunk
    # without losing the rest of the tree from the model. Falls back
    # to "all visible" when nothing is selected. Applies across every
    # display mode. UI is the second toggle at the top of the Display
    # tab, paired with auto_center_on_selection.
    fit_descendants_only: bool = False
    # How many levels BELOW the selected node the descendants fit has to
    # frame. 0 means every level, however deep — the original behaviour.
    # 1 frames the node and its children; 2 reaches the grandchildren.
    # Anything deeper than the limit is simply allowed off screen, which
    # is the point: on a big branch, framing everything zooms out until
    # the nodes you are actually reading are too small to read.
    #
    # A depth rather than more booleans, because these are one choice
    # with three answers. Two extra flags could be set at once and would
    # need a precedence rule nobody could see.
    fit_descendants_depth: int = 0
    # Which build last WROTE this file, e.g. "2.5.1". Read on load and
    # never written from here — `document.save` always stamps the version
    # doing the saving, so this only ever describes the file we came from.
    # "" for a map that has never been saved, or one written before the
    # stamp existed.
    #
    # It exists because the on-disk format is additive and the saver
    # writes only the fields it knows about: an older build that opens a
    # newer map and saves it back silently DROPS everything it has never
    # heard of. Functions did exactly that. See
    # `document.written_by_newer_build`, which turns this into the
    # warning the user actually sees.
    saved_by_version: str = ""
    # Where automatic centring puts the selected node: False = the middle
    # of the viewport, True = the middle of the LEFT edge, which leaves
    # the node's descendants the whole width of the screen to spread
    # into. The two placements contradict, so this is one flag rather
    # than two toggles that could both be on.
    auto_center_left: bool = False
    # Same settle-first idea as `scale_auto_delayed`, for centring.
    auto_center_delayed: bool = False
    # Leave the view alone when the selected node is an END node (has no
    # children). Automatic scaling has nothing to frame there but the one
    # node, so it zooms hard into it, and centring shoves the map across
    # for a node the user has usually just glanced at on their way past.
    # Applies to both, whatever they are set to. UI: Settings → Misc,
    # under Node activation delay.
    no_view_move_on_end_node: bool = False
    # When an automatic scale-to-fit is on (either scope), wait until the
    # selection has SETTLED on one node before re-framing, instead of
    # re-scaling on every selection change. Stops the view heaving about
    # while the user arrows through the tree looking for something. Set
    # from the Scale … Once buttons' "after 5 seconds" option.
    scale_auto_delayed: bool = False
    # Work mode never had a "Scale All" flag of its own - unlike its four
    # siblings below (tag/todo/bookmark/revise/alias each have one),
    # _list_map_fit_enabled fell through to a hardcoded False for it.
    # Added so Work can take part in the shared scale_mode engine (2026-09
    # display-mode consolidation, "Work ... should follow the scaling
    # rule") the same way every other mode already could.
    working_map_fit_to_view: bool = False

    # ================================================================
    # The 2026-09 "auto adjust" engine.
    #
    # Five fields that DRIVE the toggles above (auto_move_enabled,
    # auto_center_left, auto_center_delayed, fit_descendants_only,
    # fit_descendants_depth, scale_auto_delayed, and the per-mode
    # *_fit_to_view flags) rather than replacing them. The toggles are
    # what the rendering/centring code actually reads - untouched,
    # still doing exactly what they always did - so nothing about HOW a
    # fit or a re-centre happens changed. What changed is that one
    # coherent set of controls now sets all of them together, instead
    # of each toggle being an independent switch a user (or a mode
    # entry) could set inconsistently with the others - which is what
    # "the display system has conflicting parts" actually meant on
    # inspection: not that the parts were wrong, but that nothing kept
    # them in agreement.
    #
    # Applied by MapCanvas._apply_auto_adjust (canvas.py) whenever any
    # of the five below changes, or the display mode does.
    # ----------------------------------------------------------------

    # The master gate. False means neither auto-movement nor auto-scale
    # EVER fires, whatever movement_placement / scale_mode say - the
    # equivalent of pulling both toggles' plugs at once rather than
    # needing to remember to turn each off individually.
    auto_adjust_enabled: bool = True
    # Where a selection puts itself on screen: "off" (stays put),
    # "middle" (centre of the viewport), "left" (middle of the LEFT
    # edge, so descendants get the whole width to spread into).
    movement_placement: str = "middle"
    # How far the auto-fit zooms: "off" (never fits), "fit_map" (the
    # whole visible map), "fit_children" (selected node + 1 level),
    # "fit_grandchildren" (+ 1 more level). Whichever is chosen, the
    # actual fit never reaches deeper than what layers-below is
    # currently SHOWING - see MapCanvas._clamp_fit_depth_to_shown.
    scale_mode: str = "fit_map"
    # Temporary suspend that leaves movement_placement / scale_mode
    # untouched, so lifting it resumes with the SAME settings rather
    # than defaults. "off" | "movement" | "scale" | "both".
    pause_state: str = "off"
    # False = react instantly. True = wait for the shared "Node
    # activation delay" (Settings -> Misc) before moving/fitting, so the
    # view doesn't heave about while the user arrows past several nodes
    # looking for one. One shared delay rather than a separate number
    # per axis, matching auto_delay_ms's existing "one number, not
    # three that drift apart" reasoning.
    auto_adjust_delayed: bool = False
    # Cap on how deep the tree shows in Standard display mode (measured
    # from the root, or from the focus subtree's root when focus mode is
    # active). 0 = no cap (show everything, the original behavior).
    # 1 = root + 1 layer of children, 2 = + grandchildren, etc.
    standard_max_depth: int = 0
    # Standard display mode has two flavours that share all behaviour
    # except node-dragging: "Standard Free" (this flag False) lets nodes
    # be dragged freely, "Standard Lock" (True) blocks body drags unless
    # Ctrl is held. Both keep display_mode == "standard".
    standard_drag_locked: bool = False
    # Tag-map display mode state. `tag_map_tag` remembers the last tag the
    # user picked for this map so re-entering tag-map mode lands on the
    # same view. `tag_map_depth` is the descendant-depth cap shown under
    # each tagged node (0 = just the tagged nodes; 1 = + immediate
    # children; etc.).
    tag_map_tag: str = ""
    tag_map_depth: int = 1
    # Procedures: named, ORDERED sequences of nodes — "the steps for X",
    # gathered from wherever they live in the map.
    #
    #   {"Onboarding": [node_id, node_id, …], …}
    #
    # Membership lives here rather than on the node (the way `tags` does)
    # because a procedure is fundamentally an ORDER, and an order has to
    # be stored somewhere that owns the whole sequence. A node's
    # procedures are derived by asking which lists contain it, so a node
    # can be in as many as the user likes. Ids of deleted nodes are
    # dropped on load.
    procedures: dict[str, list[str]] = field(default_factory=dict)
    # Which procedure the procedure-map view is showing, and how many
    # descendant layers to render under each step.
    procedure_map_name: str = ""
    procedure_map_depth: int = 1
    # Independent "Layers below" caps for the sibling list-map modes.
    # Each controls how many descendant layers under each listed node are
    # rendered (0 = just the listed nodes themselves).
    todo_map_depth: int = 1
    bookmark_map_depth: int = 1
    # Alias map: how many descendant layers to clone under each alias
    # instance. 0 = just master + its aliases as direct children, which
    # is the lightest possible "what nodes are alias-linked to what" view.
    alias_map_depth: int = 0
    # How many ANCESTOR layers above each instance to render as a chain
    # leading down to it (the alias-map version of bookmark_map_depth_above).
    # Caps how far the parent chains extend leftward from each instance.
    # 0 = chains stop at each instance's immediate parent. Default 2 gives
    # most users enough context without runaway-wide chains.
    alias_map_depth_above: int = 2
    # Which node anchors the focused alias-map view. When alias_map mode
    # is active, the builder shows ONLY this node's alias group: the
    # resolved master in the middle, every instance's ancestor chain
    # coming in from the left, the master's descendants on the right.
    # None = no focus set; the builder shows an empty / placeholder view.
    # Set by the right-click "Show in Alias Map" action and by
    # Ctrl+Shift+A (which copies the current selection's id).
    alias_focus_id: str | None = None
    # How many ANCESTOR layers above each bookmark to render in the
    # bookmark map. 0 = current behavior (bookmark is the head of its
    # column; only descendants below). Each ancestor is rendered as a
    # single-child chain leading down to the bookmark — sibling
    # branches at each ancestor level are dropped so the column stays
    # focused on the bookmark's lineage.
    bookmark_map_depth_above: int = 0
    # When True, clicking a bookmark in the right-panel list jumps to
    # that node in the user's normal display mode (Standard / Follow)
    # via navigate_to_node, bypassing the single-bookmark focus view.
    # Defaults False so existing behavior (focus the bookmark map on
    # the clicked entry when levels_above==0) is preserved on upgrade.
    bookmark_panel_jump_on_click: bool = False
    # Shift+Alt+1..9 quick-jump assignments. Keys are "1".."9" (strings
    # so they're trivially JSON-serializable), values are node ids. A
    # missing key means that slot is unassigned. Per-map: each .smmap
    # carries its own set so two maps can both use Shift+Alt+1 without
    # colliding.
    node_shortcuts: dict[str, str] = field(default_factory=dict)
    # Tag quick-jump assignments. Keys are "1".."9", values are tag
    # names. Pressing Ctrl+Shift+<slot> switches the canvas straight
    # into tag-map mode for that tag — no need to open the Tag panel
    # first. Per-map so each .smmap carries its own set.
    tag_shortcuts: dict[str, str] = field(default_factory=dict)
    # Saved searches: persisted per-map so map-specific text / tag /
    # date queries travel with the .smmap. Surfaced in the search
    # panel as a clickable list. See `SavedSearch` for the field
    # shape. Order is insertion-order (newest at the bottom); the
    # panel can re-sort if desired.
    saved_searches: list[SavedSearch] = field(default_factory=list)
    # Slot binding for saved searches. Keys are "1".."9" (matching
    # Shift+Alt+<slot>), values are saved-search ids. Shares the
    # Shift+Alt+1-9 namespace with `tag_shortcuts` and
    # `node_shortcuts` — binding a saved search to a slot displaces
    # whichever was there. Lookup order at keypress: node → saved
    # search → tag (most specific to most general). See
    # canvas._jump_to_shortcut_slot for the resolution.
    saved_search_shortcuts: dict[str, str] = field(default_factory=dict)
    # Saved searches the user pinned as buttons in the Control Panel (under a
    # "Saved Searches" group). Ordered list of saved-search ids.
    control_panel_saved_searches: list[str] = field(default_factory=list)
    # Slot binding for SAVED remembered layouts. Keys are "1".."9"
    # (Shift+Alt+<slot>), values are saved-remembered-layout ids (the `id`
    # field of an entry in `saved_remembered_layouts`). Shares the
    # Shift+Alt+1-9 slot pool with node / tag / saved-search shortcuts — a
    # slot holds exactly one binding across all four pools. Per-map.
    saved_layout_shortcuts: dict[str, str] = field(default_factory=dict)
    # Per-slot LAYOUT snapshot taken when a node was bound to a Shift+Alt+
    # 1..9 slot, so the jump can put the tree back the way it looked when
    # the bookmark was set (display mode, collapse state, positions, zoom /
    # scroll). Keys are slot digits; values are the same JSON-safe dicts as
    # `remembered_layouts`. Only honoured while the slot still points at the
    # snapshot's `selected_id`, so a stale entry is inert.
    node_shortcut_layouts: dict[str, dict] = field(default_factory=dict)
    # Layout snapshot per BOOKMARKED node (keyed by node id): everything the
    # view looked like when the bookmark was made or last re-bookmarked -
    # display mode, collapse state and displayed levels, positions, zoom /
    # scroll, centring and scaling settings. Recalled by Shift+Alt+<slot>
    # and by clicking the bookmark. Same JSON-safe shape as
    # `remembered_layouts`.
    bookmark_layouts: dict[str, dict] = field(default_factory=dict)
    # Pause button hold-menu option "Auto Pause if on bottom N levels":
    # 0 = off, 1 = only an END node pauses, 2 = an end node or a node whose
    # children are all end nodes, 3 = one more level up again. Selecting a
    # node inside the bottom N levels of its branch turns Pause on by
    # itself; moving to a higher node turns it back off if it was this
    # option that turned it on. Replaces the earlier pair of bools
    # (auto_pause_bottom_level / auto_pause_bottom_levels), which
    # document.load still reads.
    auto_pause_levels: int = 0
    # Pause-button hold-menu option "Open On Click even when paused": while
    # Pause is on, a single click opens the selected node even if the
    # general Open On Click setting is off. (With it off, Pause changes
    # nothing about Open On Click - it follows `open_on_select`.)
    open_on_click_when_paused: bool = False
    # Node menu > Database > OCR > "Automatically OCR all un-OCR'd
    # attachments on map close": when the map closes, extract text from
    # every attachment that has none yet, silently (status bar only).
    auto_ocr_on_close: bool = False
    # Items shown in the Shortcut Keys manager, persisted so an item stays in
    # the list (as "unassigned") after its shortcut is Cleared — until the user
    # explicitly Deletes it. Each entry: {"kind": "Node"|"Tag"|"Saved search"|
    # "Saved layout", "target_id": <id/tag>}. Assigned bindings are auto-tracked
    # here on display; dead targets are pruned.
    shortcut_manager_items: list = field(default_factory=list)
    # Alt+L view-lock state. Persisted per-map so a workspace map that
    # the user habitually edits in locked layout reopens locked, while
    # a regular working map stays unlocked. Defaults False for new and
    # legacy maps.
    view_locked: bool = False
    # Working Map date filter (mode 2 of the 3-way Work display toggle). When
    # False, the Working Map hides nodes whose `working_forget_until` date is
    # still in the future; when True it shows ALL working nodes regardless.
    working_map_show_all: bool = False
    # Per-node display memories. Outer key is a "remembered root" node
    # id; inner dict maps descendant id (including the root itself) to
    # its collapsed state at memory time. When recall is enabled and a
    # remembered root is on screen, its subtree's collapse flags are
    # overridden to match the memory, letting the user pin a
    # particular layout for that branch regardless of the active
    # display mode. Nested memories: the highest visible remembered
    # ancestor's memory wins; descendants' memories are dormant under it.
    node_display_memories: dict[str, dict[str, bool]] = field(
        default_factory=dict
    )
    # Global toggle for the memory-override behavior. False = memories
    # exist but don't affect display; True = memories are applied on
    # every scene rebuild. Toggled via Shift+Alt+L or the Map Style
    # checkbox.
    recall_node_display_memories: bool = False
    # "Remembered" layouts — a full view snapshot keyed by the node that
    # was selected when the user pressed the toolbar R button. Each value
    # is a JSON-safe dict capturing the map's display mode, layout / line
    # style, focus subtree, collapse state (which descendants/ancestors
    # were showing), selection, viewport (scale + scene center), a small
    # PNG thumbnail (base64) for hover preview, and a timestamp. Surfaced
    # in the Search dock's Remembered tab and by an R badge on the node.
    # Restoring one is non-destructive — the map stays fully editable.
    remembered_layouts: dict[str, dict] = field(default_factory=dict)
    # Named, user-SAVED layout snapshots — independent of the one-per-node
    # `remembered_layouts` above, so a node can have several versions (e.g.
    # Focus on / off). Each entry: {"id", "name", "snapshot" (same shape a
    # remembered layout uses), "source_node_id", "created_at"}.
    saved_remembered_layouts: list = field(default_factory=list)
    # "Memorized" views — the M badge. A named BUNDLE OF SETTINGS captured
    # against a node: centring mode, scaling mode, display mode, focus,
    # depth cap, viewport (zoom + scroll) and collapse state. Recalling
    # one regenerates that whole state. Deliberately separate from
    # `remembered_layouts` (R), which is about how one node's own subtree
    # was arranged by hand: a node can carry several Ms, each with its own
    # user-given name, and the same node can carry an R as well.
    # Each entry: {"id", "name", "node_id", "created_at", "used_at",
    # "use_count", "snapshot"}. Node positions and thumbnails are NOT
    # captured — the snapshot stays a few hundred bytes so a map can hold
    # many without the file bloat that node_history once caused.
    memorized_views: list = field(default_factory=list)
    # When True, the tidy-tree layout (apply_layout / Auto Arrange /
    # Alt+Y) is re-run automatically on every scene rebuild — so any
    # structural edit (add / delete / move node, change visibility,
    # toggle display mode) immediately fixes overlaps and tidies
    # positions without the user having to press Alt+Y. Default off
    # because it overrides any manual repositioning the user has
    # done.
    auto_beautify: bool = False
    revise_map_depth: int = 1
    # Info Page dock: when True the right-side Info Page panel is
    # shown and auto-tracks the selected node, rendering its note +
    # every attachment inline. Edits to the note save back to the
    # node via the same EditNoteCommand path the popup note editor
    # uses. Per-map so a "reading map" can ship with the panel on by
    # default while editing-focused maps stay off.
    info_page_enabled: bool = False
    # Per-mode "Scale to fit" toggles. When on, entering the mode (or
    # rebuilding it after a depth change / source-set change) zooms the
    # view so every visible node fits in the viewport. List-map modes
    # default to True — they're auto-generated views that benefit from
    # always being readable at a glance — while Standard/Follow stay
    # opt-in so the user's curated view isn't disturbed unexpectedly.
    standard_fit_to_view: bool = False
    tag_map_fit_to_view: bool = True
    todo_map_fit_to_view: bool = True
    bookmark_map_fit_to_view: bool = True
    revise_map_fit_to_view: bool = True
    alias_map_fit_to_view: bool = True
    # When True, hovering a selected node shows a tooltip with its
    # last-edited timestamp. Defaults True so the feature is discoverable;
    # toggleable per-map from the Display tab for users who find it noisy.
    show_edited_date_on_hover: bool = True
    # Remembers the user's most recently chosen non-list / non-recall
    # base mode ("standard" or "follow"). When exiting a list-map mode
    # (tag/todo/bookmark/revise) or following a History / panel jump
    # out of one, the canvas returns to this mode so the user lands
    # back in their preferred everyday view rather than always being
    # forced into Standard. Recall modes count as Follow.
    last_base_mode: str = "standard"
    # Quick Input target: when set, Alt+Q (or the right-click "Create
    # Quick Input" entry) adds a new timestamped child under this node.
    # None means the feature is disabled until the user sets a parent
    # in Map Style → Misc.
    quick_input_target_id: str | None = None
    # Archive target: when set, Alt+Z reparents the selected node under
    # this node and keeps the user's viewport / selection on the moved
    # node's ORIGINAL parent — so a rapid "stash + carry on" flow doesn't
    # disturb where the user was working. None means the feature is
    # disabled until configured in Map Style → Misc.
    archive_node_id: str | None = None
    # Backup target: where "Backup Node" files its copies. Configured in
    # Map Style → Misc exactly like the archive node, and None until it
    # is. Distinct from the archive on purpose — archiving MOVES a node
    # out of the way, backing up COPIES it and leaves the original
    # working. The two want different destinations.
    backup_node_id: str | None = None
    # How completed nodes should appear on the map:
    #   "original" — completed nodes stay where they were (default).
    #   "archive"  — completed nodes are auto-moved under
    #                `archive_node_id` on completion, and restored
    #                to their original parent when un-completed.
    # Manual Alt+Z archives are always honored regardless of this
    # setting (they're tracked separately from auto-archives).
    completed_display_mode: str = "original"
    # When True, hovering over a node/button for ~0.7 s pops up a small
    # summary of its note / link / attachments. Off = no preview
    # (matches classic behavior). Setting lives at the map level so
    # each map remembers the user's preference.
    hover_preview_enabled: bool = False
    # Minimalist / compact layout — halves the spacing between nodes
    # and layers so more of the tree fits in one viewport. Toggled
    # from the right-panel Display Mode section; also auto-enabled
    # by the Todo filter (user can override).
    minimalist_layout: bool = False
    # Horizontal gap between a parent's right edge and its child's left
    # edge, in horizontal-branching layouts (tidy_branched / tidy_right /
    # tidy_left) — i.e. how long the connecting line between them runs.
    # Independent of `minimalist_layout`: a direct user choice, not a
    # scaled derivative. Matches `core.layout._H_GAP`'s original
    # hardcoded default, now user-adjustable per map. No effect on
    # vertical layouts (tidy_down / tidy_up), which use their own
    # V_STEP/H_PAD constants instead.
    horizontal_line_length: float = 60.0
    # When True, follow mode auto-fits the entire visible subtree to the
    # viewport after every selection change. Lets the user navigate
    # without ever having to manually zoom. Default off so existing
    # users see no change unless they opt in.
    follow_fit_to_view: bool = False
    # "none" | "node" | "note"
    #   none = no image rendered on any node
    #   node = current behavior: the node's own attached image (above text)
    #   note = first image found in the node's note (HTML-embedded image,
    #          or the first image attachment, or the first page of the
    #          first PDF attachment), rendered below the text.
    node_image_mode: str = "node"
    open_at: str = "root"  # "root" | "last_selected" | "specific"
    last_selected_id: str | None = None
    # Id of the node to land on at file open when open_at == "specific".
    # If the node has been deleted by the time the file reopens, the
    # canvas falls back to the root.
    open_at_node_id: str | None = None
    # If the user closed the file while focused on a subtree (Alt+C), this
    # holds the id of that focus root. Restored on next open so the file
    # opens to the same view the user left.
    focus_id: str | None = None
    # Viewport state captured at save time so the map reopens to the exact
    # same zoom and scroll position. view_scale is the uniform transform
    # scale (1.0 = no zoom). view_center_x/y are scene coordinates of the
    # viewport center. None means no saved view — caller falls back to the
    # default focus/selection centering.
    view_scale: float = 1.0
    view_center_x: float | None = None
    view_center_y: float | None = None
    # Ordered list of node ids the user has bookmarked. Order is meaningful
    # — the bookmark panel renders in this order and the user can drag to
    # rearrange. Presence in this list IS the bookmark; there's no separate
    # per-node flag.
    bookmarked_ids: list[str] = field(default_factory=list)
    # Bookmarked node ids that should ALSO center/fit the whole map when jumped
    # to from the Bookmarks panel (the ◎ Center behaviour), rather than just
    # landing on the node. Subset of bookmarked_ids; per-bookmark opt-in.
    bookmark_center_ids: list[str] = field(default_factory=list)
    # Folder where node attachments are stored. Two cases:
    #   - Absolute path (`C:/...` / `/...`): a fixed location anywhere on disk.
    #   - Relative path (`foo_files` / `./attachments`): resolved against the
    #     `.smmap`'s parent dir at runtime. Survives the map being moved or
    #     synced via Dropbox as long as the relative folder moves with it.
    #   - None: default, equivalent to `"<mapname>_files"` next to the file.
    attachments_folder: str | None = None

    # --- Map backup settings (per-machine) ----------------------------
    # The same .smmap may be opened on multiple computers (Dropbox /
    # OneDrive / git sync). Backup paths on one computer don't exist
    # on another, so the settings are stored PER MACHINE — keyed by
    # the hostname (`platform.node()`). The UI only ever shows the
    # current machine's entry; other machines' entries are preserved
    # in the file untouched.
    #
    # Each entry is a dict with the following keys (see
    # `_default_backup_entry` for the schema and defaults):
    #   folder, hourly, daily, weekly, monthly, copy_files,
    #   retention, last_hourly_at, last_daily_at, last_weekly_at,
    #   last_monthly_at
    backup_settings_per_machine: dict[str, dict] = field(
        default_factory=dict
    )
    # OCR language codes (e.g. ["en", "ja"]) used when extracting text
    # from inline note images. Defaults to English only. Adding "ja",
    # "ko" etc. triggers a one-time download of the matching RapidOCR
    # rec model on the next OCR call — see synmind/core/ocr.py.
    ocr_languages: list[str] = field(
        default_factory=lambda: ["en"]
    )
    # Which OCR backend to use. "rapidocr" (default) is the bundled
    # printed-text engine — fast and offline, but poor on handwriting.
    # "easyocr" handles handwriting + a wider variety of scripts but
    # is slower (~1-4s per image on CPU) and pulls model files on
    # first use of each language. Set via Map Style → Misc → Image OCR.
    ocr_engine: str = "rapidocr"
    # Timed review mode: when > 0, "Start Timed Test" arms a per-question
    # countdown of this many seconds. If the user doesn't grade Y before
    # the timer expires the entry is auto-marked N and the test advances.
    # 0 means the timer feature is off (the regular Start Test path).
    # Stored per-map so a deck of e.g. recognition flashcards can keep
    # its 5-second cadence between sessions without re-entering the value
    # in the Review panel.
    review_timer_seconds: int = 0
    # Remembers which review-test variant the user last ran:
    #   "untimed" — plain self-paced review
    #   "timed"   — timed test with the per-question countdown
    #   "auto"    — Auto Review (no scoring, countdown-driven)
    # The Shift+Alt+R shortcut (and the equivalent menu entries)
    # re-uses this so the user doesn't have to re-pick the same
    # variant every session. Per-map so different maps can carry
    # different preferred review styles.
    last_review_test_mode: str = "untimed"
    # Review Queue filter persistence — remember which radio buttons
    # the user had selected on the Test tab so the queue restores to
    # the same view next session. Previously these always reset to
    # "all" + "both" on launch.
    #   review_filter_overdue: False = "All marked", True = "Overdue only"
    #   review_kind_filter:    "both" | "nodes" | "notes"
    review_filter_overdue: bool = False
    review_kind_filter: str = "both"
    # "% correct" review-queue filter. When enabled, only review
    # entries whose historical grading is STRICTLY LESS THAN
    # `review_correct_threshold_pct` percent correct pass. Nodes with
    # no grades yet count as 0% (always included). Composes with the
    # overdue + kind filters. Off by default so existing users see
    # no change unless they opt in.
    review_correct_threshold_enabled: bool = False
    review_correct_threshold_pct: int = 80
    # When True, the per-question countdown is multiplied by the
    # number of masked items on the current card (recall_seq's
    # `_recall_masked_ids` count, plus the card's title-recall
    # region count). A card with 3 masked children gets 3× the base
    # timer; a card with no masks falls back to the base value. When
    # False, every card gets exactly `review_timer_seconds`. Per-map
    # so a flashcard deck with usually-single-blank cards can stay
    # on the flat timer while a long-form study map gives more time
    # for multi-blank entries.
    review_timer_multiply_by_masks: bool = False
    # Spaced-repetition interval ladder. Stored as a list of day counts;
    # `apply_review_answer` looks up the interval by `node.review_step`.
    # Empty list / None means "use the hardcoded default ladder" in
    # commands.REVIEW_INTERVALS_DAYS — that's the historical behavior.
    # When the user customizes intervals via the SR settings tab, the
    # list is populated and persists per-map. Lengths can differ from
    # the default; `review_step` is clamped to len-1 at lookup time so
    # an existing card whose step exceeds a shrunk ladder still
    # resolves to the longest defined interval.
    sr_intervals_days: list = field(default_factory=list)
    # Multiplier applied to the looked-up interval on a CORRECT answer
    # after a streak of correct answers (the "ease" knob in SM-style
    # systems). 1.0 = use the ladder value as-is; > 1.0 spaces
    # successive correct answers further apart than the ladder
    # suggests. Applied on top of the ladder lookup, not as a
    # replacement.
    sr_correct_multiplier: float = 1.0
    # Hours-not-days mode. When True, `sr_intervals_days` is interpreted
    # as hours instead — useful for short-cycle learning of fresh
    # material in the first few days. Persists per-map so a flashcard
    # deck can stay on the daily cadence while a study-this-week map
    # uses hourly intervals.
    sr_use_hours: bool = False
    # Scope filter — when set, every panel / search / review queue /
    # list-map mode treats only this node and its descendants as the
    # live map. The rest of the tree is excluded from results but
    # remains untouched in the data; clearing the filter (None)
    # restores whole-map behavior. Per-map so a long-form notes map
    # can stay focused on a subtree while a flashcard map runs
    # whole-map by default.
    filter_node_id: str | None = None
    # Todo scope filter — orthogonal to filter_node_id (they compose).
    # Values:
    #   "off"      : no todo filter, every node passes through.
    #   "all"      : show only nodes marked as a todo (any state) plus
    #                every ancestor + descendant of each match so the
    #                map's tree structure is preserved.
    #   "overdue"  : same as "all" but only nodes whose todo is
    #                currently overdue (no due date, or due date passed).
    todo_filter_mode: str = "off"
    # Last 20 node ids used as scope-filter targets, most recent first.
    # Feeds the Filter chip's dropdown so the user can jump straight to
    # a recent filter without re-selecting a node first.
    recent_filter_ids: list[str] = field(default_factory=list)
    # Shortcut palette state — per-map memory of whether the touch
    # shortcut palette (2-finger triple tap on the viewport) was open
    # when the map last saved, plus its layout (compact / docked /
    # geometry). Used to restore the same window on the next map
    # open so the user doesn't have to re-configure it every session.
    # Keys: "open" (bool), "compact" (bool), "docked_left" (bool),
    #       "x" / "y" / "w" / "h" (int).
    shortcut_palette_state: dict = field(default_factory=dict)
    # Control Panel state — per-map memory of whether the big-screen
    # Control Panel window (Ctrl+Shift+C) was open when the map last saved,
    # and its minimal-view (compact) mode. Keys: "open" (bool),
    # "compact" (bool). NOTE: the window's position + size are deliberately
    # NOT stored here — they're machine-local (QSettings), so a map opened
    # on a different computer / monitor uses that machine's own layout.
    control_panel_state: dict = field(default_factory=dict)
    # Control Panel Favourites — the user-arranged favourites layout (rows
    # of button ids + separators) travels with the map so a shared map keeps
    # its curated quick-access set. Row format:
    #   [{"type":"buttons","ids":[...]}, {"type":"separator"}, ...]
    control_panel_favorites: list = field(default_factory=list)
    # Custom Menu Bar — the user-built icon bar on the map window, populated
    # from Control Panel actions ("Add to menu bar"). Stored with the map.
    # Item format: {"type":"button","key":"<action-key>"} (groups/frames are
    # added in a later phase).
    menu_bar_items: list = field(default_factory=list)
    # The STATE those buttons are in — display mode, the automatic move /
    # scale / centre flags, the lock level, which bullets show. Written on
    # save, applied on open, so a map reopens looking exactly as it was
    # left. Machine-independent on purpose: the same map on a second
    # computer opens the same way. See core/view_state.py.
    button_states: dict = field(default_factory=dict)
    # Per-machine UI-settings bundles, keyed by AppSettings.machine_id. Each
    # value is a JSON-safe dict of that computer's Control Panel + menu-bar +
    # quick-toggle config (size, layout, scale, favourites, …) so the same map
    # can carry a different layout on each machine. See core/ui_settings.py.
    machine_ui_settings: dict = field(default_factory=dict)
    # Search inclusion toggle — when True, nodes under the configured
    # archive node still show up in Search results. Default False so
    # archived items don't clutter routine searches. Per-map so each
    # map can remember its own preference.
    search_include_archives: bool = False
    # Geometry blob (base64-encoded QByteArray) capturing the review
    # toolbar's docked/floating position so reopening the map restores
    # it where the user parked it. Empty string = default docked
    # position under the nav toolbar.
    review_toolbar_geometry: str = ""
    # Note editor window state — restored on the next open of any
    # note in this map. `note_editor_geometry` is a base64-encoded
    # QByteArray from QWidget.saveGeometry() (mirrors the pattern
    # `review_toolbar_geometry` uses). `note_editor_maximized`
    # records the OS-level maximized/full-screen state so a note
    # opened maximized last session reopens maximized. Empty string
    # / False means "no memory yet"; the editor falls back to its
    # default 1000×580 layout.
    note_editor_geometry: str = ""
    note_editor_maximized: bool = False
    # Calendar panel display mode: "month" (grid, default), "week"
    # (single-week list), or "day" (single-day list). Persisted per
    # map so users who prefer the list view don't have to flip the
    # selector every time they open the file.
    calendar_view_mode: str = "month"
    # Calendar item-filter flags. Lets the user mute categories of
    # items from the calendar without losing the underlying marks on
    # the nodes. Tied to checkable entries in the calendar panel's
    # filter menu (the gear button at the top-right).
    calendar_show_overdue: bool = True
    calendar_show_today_due: bool = True
    calendar_show_upcoming: bool = True
    # Where node badges (R/D/etc) render relative to the node body.
    #   "right" (default) — badges sit in a horizontal row to the
    #     right of the body, growing the node's bounding rect width.
    #   "below" — badges sit in a horizontal row below the body,
    #     growing the bounding rect height instead. Useful on dense
    #     maps where extra width pushes siblings apart and breaks
    #     the visual rhythm.
    badge_position: str = "right"
    # Per-map badge (bullet) visibility. Maps a badge kind (see
    # NodeItem.TOGGLEABLE_BADGES) -> shown. A missing key means shown, so
    # existing maps keep every badge until the user hides one via the
    # Control Panel -> Bullets tab. Only kinds the user has turned OFF are
    # stored (value False), keeping the map file lean.
    badge_visibility: dict = field(default_factory=dict)
    # Node activation delay: how long (milliseconds) a single node must stay
    # selected before it counts as "activated" — i.e. its `last_viewed_at` is
    # stamped and it appears in the History panel's Recent Views. Default 5 s;
    # settable per map in Map Style → Misc. Quick click-throughs while
    # navigating don't count, which is the point.
    view_dwell_ms: int = 5000
    # Follow-mode re-anchor delay: how long (milliseconds) after the
    # selection settles before Follow "opens" (re-anchors on) the new node.
    # Independent of `view_dwell_ms` so Follow can feel snappier (or slower)
    # than the activation timer. Also debounces rapid arrow traversal.
    # Default 700 ms; settable per map in Map Style → Misc.
    follow_reapply_ms: int = 700
    # Calendar panel inclusion flags. Toggled in Map Style → Misc.
    # The calendar walks every node with a todo_due_at or
    # review_due_at and renders the node text in the matching day
    # cell; these flags let the user mute either source independently
    # (e.g. show only review schedule, hide todos).
    calendar_show_todos: bool = True
    calendar_show_reviews: bool = True
    # Which day the calendar grid starts each week on. "monday"
    # (ISO 8601 default) or "sunday" (US convention). Stored as a
    # string so it round-trips through JSON cleanly and so new
    # values (e.g. "saturday" for some locales) can be added later
    # without a schema migration.
    calendar_week_start: str = "monday"
    # Google Calendar sync (see synmind/integrations/google_calendar/).
    # What gets pushed is everything the Calendar panel already shows
    # (todo_due_at / review_due_at, gated by calendar_show_todos /
    # calendar_show_reviews above), further narrowed by these two
    # independent, AND-combined filters:
    #   google_sync_scope: "all" every upcoming item, or "overdue"
    #     restricts to items already past their due date.
    #   google_sync_priority_filter (+ _max_level): when enabled, only
    #     nodes with priority_level <= max_level sync (1 = highest
    #     priority, per colors.PRIORITY_FILLS — so max_level=2 sends
    #     levels 1 and 2). A node with no priority_level set is
    #     excluded once this filter is on, same as any other node
    #     that fails a filter.
    # The OAuth connection itself (tokens, chosen calendar id) is
    # per-machine, not per-map — see AppSettings.google_calendar_id —
    # but WHAT to sync is a property of the map's own content, same
    # precedent as calendar_show_todos/_reviews just above.
    google_sync_scope: str = "all"
    google_sync_priority_filter: bool = False
    google_sync_priority_max_level: int = 5
    # When on, MainWindow._run_exports_on_close runs one more Google
    # Calendar sync — synchronously, same reasoning as the per-node
    # auto_export "sync_on_close" flag (CLAUDE.md's "Export on close")
    # — right before this map actually closes, so the last few minutes
    # of edits reach the calendar without the user having to remember
    # to click Sync Now themselves.
    google_sync_on_close: bool = False
    # Every google_event_id / google_review_event_id that existed on a
    # live node right after the last successful sync — NOT a per-node
    # field, because a locally-deleted node's id would be gone right
    # along with the node by the time the next sync runs, with nothing
    # left to read it off of.
    #
    # Deletion detection works by RECONCILIATION rather than hooking
    # every place a node can disappear (Delete, Trash, cut without
    # paste, merge-away, alias removal, undo variations…) — missing
    # even one such path would leak an orphaned Google event forever.
    # Instead, each sync compares this set against every id CURRENTLY
    # attached to a live node; whatever is in this set but no longer
    # attached to anything is exactly what should no longer exist on
    # Google, regardless of how it disappeared. See sync.py's
    # build_sync_job. Updated to the new live set after every
    # successful sync (see the panel wiring that applies SyncOutcomes).
    google_calendar_known_event_ids: list[str] = field(default_factory=list)
    # Which Google calendar id google_event_id / google_review_event_id
    # / google_calendar_known_event_ids above actually refer to, as of
    # the last successful sync. An event id is only meaningful WITHIN
    # the calendar it was created on — if this no longer matches the
    # calendar a sync is about to target (the user deleted and
    # recreated the "UnTangleMate" calendar, or reconnected a
    # different Google account), every stored id on this map is stale
    # and must be treated as if it never existed, regardless of
    # whether its content hash still matches. Without this, "Disconnect
    # and delete the calendar too" followed by reconnecting silently
    # sync'd nothing at all — the hash comparison correctly saw no
    # CONTENT change and reported "already uploaded", never noticing
    # the events themselves were gone along with the deleted calendar.
    # See sync.py's build_sync_job.
    google_calendar_last_synced_calendar_id: str | None = None
    # Per-map last-used Search target (the combined scope+surface
    # picker on the Standard search panel). Persisted on the map so
    # switching between maps restores each one's last choice instead
    # of resetting to the default — the user kept hitting that
    # ("the search target had changed back to node only") when their
    # actual workflow was wide-net OCR / attachment search. Values
    # mirror the SEARCH_TARGETS keys in search_panel.py: one of
    # "subtree_title" / "map_title" / "subtree_all" / "map_all".
    search_target: str = "subtree_title"
    # Per-map last-used Search RESULT ORDER (the Standard panel's
    # "Search result order" combo) — same reasoning/persistence
    # pattern as `search_target` right above: the user kept seeing it
    # revert to "Default (tree order)" instead of staying on whatever
    # they'd picked. One of "default" / "created" / "edited" / "name",
    # matching the SEARCH_SORTS keys in search_panel.py.
    search_sort: str = "default"
    # Per-map recently-typed search terms (most-recent-first). Drives
    # the Search panel's text input dropdown so the user can pick a
    # past query instead of retyping it — Tab in the input accepts
    # the currently-highlighted completion. Capped to keep the
    # `.smmap` file from accumulating stale searches forever.
    search_history: list[str] = field(default_factory=list)
    # Node-history store (see `core.node_history`): dated field-level change
    # log for nodes under recording, plus the last-recorded snapshot per node
    # used to diff. JSON-able dict of the form
    #   {"version": int, "entries": {node_id: [entry,...]}, "snapshots": {...}}
    #
    # Stored NOT in the .smmap but in a `<name>.smhist` sidecar, because on a
    # long-lived map it grew to be the biggest thing in the file while nothing
    # read it until the user opened a History dialog. `None` means "not read
    # from the sidecar yet" — the UI loads it on first use, so a session that
    # never touches history never pays to parse or write it. See
    # `core.document.load_node_history` / `save_node_history`.
    node_history: dict | None = None
    # Set when the store has been changed in memory and the sidecar needs
    # rewriting. Not persisted — it describes this session, not the map.
    node_history_dirty: bool = False
    # Remembered time-range filter for the History viewer, shared for the
    # whole map. None = All time; an int is the number of days (presets or a
    # user-defined custom value). Persisted so every History dialog opens
    # with the same window.
    history_filter_days: int | None = None

    # ---- History settings (the Settings tab in the History dialog) ----
    #
    # `history_filter_days` above is a VIEW filter — it hides entries in
    # the dialog without deleting them. These three actually shrink the
    # store: the ".smhist sidecar has become very big" complaint that
    # motivated them. All applied by core.node_history.prune_store,
    # called from MapCanvas._run_history_capture on the same coalesced
    # pass that already records new changes.

    # Master switch. False stops ALL new recording, map-wide, without
    # touching a single node's own `history_recording` flag — those are
    # left exactly as the user set them, so turning this back on resumes
    # recording the same nodes it always did, with no per-node work to
    # redo.
    history_recording_enabled: bool = True
    # Per-node entry cap. Was a hardcoded constant
    # (node_history.MAX_ENTRIES_PER_NODE); now a map setting so a map
    # that wants tighter or looser retention doesn't need a code change.
    # The oldest non-baseline entries are dropped first - same rule the
    # constant always used.
    history_max_entries_per_node: int = 30
    # None = no age limit. Otherwise the number of DAYS an entry is kept
    # before pruning — weeks/months are just days at the UI layer
    # (matches how the History dialog's own "Last 6 months" filter is
    # already stored as 182 days). Unlike the count cap, age-based
    # pruning does NOT spare the baseline entry: "younger than X" is
    # an explicit request to drop everything before a date, baseline
    # included.
    history_max_age_days: int | None = None
    # None = no auto-delete. Otherwise the number of DAYS after which a
    # node's `last_viewed_at` is cleared automatically — the History
    # panel's Recent Views tab, not the per-node edit-diff history above.
    # Deliberately separate from history_max_age_days: unlike a real
    # growing log, clearing this ONE field is safe to automate because
    # nothing outside "was this node recently viewed" reads it (see
    # history_panel.py's own note on why Recent Edits / Recent Creations
    # do NOT get the same treatment — their timestamps are read by
    # search/sort code elsewhere that has nothing to do with history).
    views_auto_delete_days: int | None = None
    # When to actually run OCR on inserted images. "immediate" (default)
    # fires the moment an image is pasted/dropped — text is searchable
    # right away but credits get spent on throwaway pastes. "manual"
    # only runs when the user clicks the button. "on_close" batches
    # every uncached image when a note window closes. "daily" runs a
    # cross-map sweep once every 24h while the app is open.
    ocr_trigger_mode: str = "immediate"
    # When True, the synchronous OCR paths (manual sweep, on-close,
    # the "OCR pending images now" button) run on a worker thread so
    # the UI stays responsive. The progress overlay still shows; it
    # just hovers non-modally over the dialog/window while OCR
    # proceeds. Default off matches the historical blocking
    # behavior — flip it on under Map Style → Misc → Image OCR for
    # large maps where the freeze becomes painful.
    ocr_run_in_background: bool = False
    # Epoch-seconds timestamp of the last successful daily OCR sweep.
    # Used by the daily-mode startup/hourly check to decide whether to
    # fire. Zero means "never run."
    ocr_last_daily_run: float = 0.0

    # Cross-map navigation history. Persisted dict containing back/forward
    # stacks for navigating across maps. Serialized form of
    # synmind.core.navigation_history.NavigationHistory:
    #   {"back_stack": [...], "forward_stack": [...], "current": {...}}
    # Empty dict on new maps or after history is cleared.
    navigation_history: dict = field(default_factory=dict)

    # Trash — nodes that were deleted but can be restored. Newest
    # entries appended at the end (deletion order). Drag-to-trash and
    # confirmation-prompted delete both route here; only "Empty Trash"
    # / per-row "Delete Permanently" actually drop the data.
    trash: list[TrashEntry] = field(default_factory=list)
    # Whether the bottom-left trash overlay widget is rendered. The
    # trash list itself stays accessible via undo + the saved data
    # regardless of this flag — the toggle only hides the on-canvas
    # icon for users who prefer a clean viewport. UI lives in Map
    # Style → Display next to the other global display toggles.
    show_trash_widget: bool = True

    # Read-only / editable mode for the whole map. `editable` is the
    # legacy boolean — kept in sync as "fully editable" (True only in
    # the "editable" edit_mode) so every existing reader keeps working.
    # `edit_mode` is the tri-state source of truth:
    #   "editable"       — fully editable.
    #   "locked_weak"    — no structural/content edits or node movement,
    #                      but bullet/metadata edits ARE allowed (todo
    #                      due dates, unmark/remove todos, completion
    #                      rate, recording review/test results, marking
    #                      completed).
    #   "locked_strong"  — nothing editable at all, including bullet data.
    #                      An attempted edit offers to unlock.
    #   "locked_sealed"  — as locked_strong, but it never OFFERS to
    #                      unlock, and the map is not written to disk
    #                      while it's on. Reading mode: navigate, open
    #                      nodes and notes, change nothing. The one save
    #                      that does happen is the one on entering the
    #                      mode, so the setting itself persists and no
    #                      earlier work is stranded unsaved.
    # Toggleable via the lock button in the nav toolbar; defaults to
    # editable on legacy maps.
    editable: bool = True
    edit_mode: str = "editable"

    # Sketch dialog input toggles, remembered as part of the map so a
    # user's preferred input setup carries from one sketch to the next
    # within the same .smmap. Defaults match the dialog's own out-of-
    # box defaults so legacy maps load with the friendliest settings.
    # `sketch_finger_input_enabled` is the master switch for finger
    # drawing (False = pen / mouse only). `sketch_palm_rejection_enabled`
    # controls the "drop touches while pen is active" behavior (True
    # by default; greyed out when finger input is off because it has
    # nothing to gate).
    sketch_finger_input_enabled: bool = True
    sketch_palm_rejection_enabled: bool = True

    # During a Review test, controls how much of the map surrounds the
    # node being tested. "relationships" keeps the normal recall view
    # (selected node + ancestors / siblings per follow / recall depth),
    # giving spatial context. "review_only" hides everything else so the
    # user sees ONLY the target node on a clean canvas — useful when the
    # surrounding nodes would prime / give away the answer.
    review_show_mode: str = "relationships"

    # When True, every node painted by the canvas checks whether it has
    # an is_topic ancestor that is NOT currently visible in the scene
    # (e.g. hidden by a Follow / Recall depth cap) and, if so, paints a
    # small amber bubble at the node's bottom-left naming that topic.
    # Lets the user see the topic context for every descendant at a
    # glance — useful in deep maps where the topic header scrolled off
    # screen. Default off so legacy maps look exactly the same.
    show_topic_label_on_descendants: bool = False

    # When True, the Search dock closes itself the moment the user picks
    # an item from any of its tabs (result, topic, filter, tag, comment,
    # or remembered layout). Off by default so the panel stays put.
    # Legacy global flag — retained for back-compat; the live control is
    # now the per-tab map below.
    search_panel_auto_close: bool = False
    # Per-tab auto-hide opt-in for the Search dock. Keyed by tab id
    # ("search" / "comments" / "topics" / "filters" / "tags" /
    # "remembered"); each tab's toggle is independent, so clicking an
    # item only closes the panel when THAT tab's entry is True.
    search_panel_auto_close_tabs: dict[str, bool] = field(default_factory=dict)
    # Same idea for the ToDo dock. Keyed by tab id ("todo" /
    # "completion"); clicking a row closes the dock only when that tab's
    # entry is True.
    todo_panel_auto_close_tabs: dict[str, bool] = field(default_factory=dict)
    # Per-dock auto-hide for the standalone single-list node docks. Keyed
    # by panel id ("topics" / "bookmarks" / "history" / "tags" /
    # "calendar"); clicking a row closes that dock only when its entry is
    # True. See synmind.ui.panel_auto_close.
    panel_auto_close: dict[str, bool] = field(default_factory=dict)

    # Per-panel row ordering for the node-list docks. Keyed by panel id
    # ("topics" / "tags" / "bookmarks"); values are
    # "alpha" | "edited" | "manual". Missing key = that panel's own
    # default. See synmind.ui.panel_sort.
    panel_sort_order: dict[str, str] = field(default_factory=dict)

    # Which filter radio the To Do dock is on: "all" | "overdue" |
    # "recurring" | "completed". Per map, so it survives closing and
    # reopening. See synmind.ui.todo_panel.
    todo_panel_filter: str = "all"

    # Which tab a multi-tab dock reopens on, keyed by panel id
    # ("history"). The value is the tab's NAME, not its index, so adding
    # or reordering tabs later can't silently reopen on the wrong one.
    # Per map rather than per computer: which list you want in front is
    # a property of the map you're working in.
    panel_last_tab: dict[str, str] = field(default_factory=dict)

    # When True, reaching a node deeper than the current Standard-mode
    # depth cap (e.g. via a panel jump) automatically RAISES "Layers
    # Below" to reveal it. Turn it OFF (the toolbar tick box next to the
    # Layers spinners) to keep the visible chain length fixed at whatever
    # you set manually — useful in Standard Lock where you don't want the
    # depth to change as you click around. Default True (legacy behavior).
    auto_layers_on_select: bool = True

    # Auto-apply remembered layouts on selection. One of:
    #   "off"        — never auto-apply (default; R layouts only load
    #                  when clicked in the Remembered tab).
    #   "individual" — selecting a node that has a remembered layout AND
    #                  its own `remembered_auto` flag re-applies it.
    #   "whole"      — selecting ANY node that has a remembered layout
    #                  re-applies it (map-wide).
    remembered_display_mode: str = "off"

    def all_nodes(self) -> Iterator[Node]:
        return self.root.walk()

    def visible_nodes(self) -> Iterator[Node]:
        return self.root.walk_visible()

    def refresh_lookup_cache(self) -> None:
        """(Re)build O(1) id→node, child→parent, back-link and alias indexes
        so the thousands of find() / parent_of() / find_backlinkers() /
        find_aliases_of() calls made while rendering + PAINTING nodes stop
        being O(n) each — the dominant cost of opening a node on a large map
        (was O(n^2) overall). Rebuilt from the current tree, so it reflects
        the latest structure. Callers MUST invalidate_lookup_cache() before
        mutating the tree structure / links / aliases so a stale cache is
        never read during an edit; collapse / position / text changes don't
        affect the indexes and need no invalidation."""
        nodes: dict[str, Node] = {}
        parents: dict[str, Node] = {}
        # Built in root.walk() order so the badge lists match the ordering
        # the old all_nodes() scans produced.
        backlinks: dict[str, list[Node]] = {}
        aliases: dict[str, list[Node]] = {}
        for node in self.root.walk():
            nodes[node.id] = node
            tgt = getattr(node, "link_target_id", None)
            if tgt:
                backlinks.setdefault(tgt, []).append(node)
            am = getattr(node, "alias_of", None)
            if am:
                aliases.setdefault(am, []).append(node)
            for ch in node.children:
                parents[ch.id] = node
        self._lookup_nodes = nodes
        self._lookup_parents = parents
        self._lookup_backlinks = backlinks
        self._lookup_aliases = aliases

    def invalidate_lookup_cache(self) -> None:
        """Drop the lookup indexes so subsequent find()/parent_of()/… fall
        back to a fresh O(n) scan. Call before ANY structural / link / alias
        mutation; the next refresh_lookup_cache() (at the start of a scene
        rebuild) repopulates them."""
        self._lookup_nodes = None
        self._lookup_parents = None
        self._lookup_backlinks = None
        self._lookup_aliases = None

    def find(self, node_id: str) -> Node | None:
        cache = getattr(self, "_lookup_nodes", None)
        if cache is None:
            # Cache was invalidated by a mutation. Rebuild it once now
            # rather than doing an O(n) tree walk on every call — a layout
            # pass calls find()/parent_of() tens of thousands of times, so
            # the lazy rebuild turns O(n^2) back into O(n).
            self.refresh_lookup_cache()
            cache = self._lookup_nodes
        return cache.get(node_id)

    def backup_settings_for_current_machine(self) -> dict:
        """Return the backup settings entry for the computer this
        process is running on, creating it (with defaults) if no
        entry exists yet. Mutating the returned dict updates the map;
        callers don't need to write it back."""
        mid = current_machine_id()
        entry = self.backup_settings_per_machine.get(mid)
        if entry is None:
            entry = _default_backup_entry()
            self.backup_settings_per_machine[mid] = entry
        else:
            # Forward-compat: if a key is missing (older file format
            # got a new field added), backfill with the default so
            # callers always see the full schema.
            for k, v in _default_backup_entry().items():
                entry.setdefault(k, v)
        return entry

    def resolve_alias(self, node: Node) -> Node:
        """If `node` is an alias, return the master it points to (recursively
        in case of chained aliases). If the master is missing or there's a
        loop, returns `node` itself so callers never get None.

        Caps the chain at 32 hops to defend against cyclic alias graphs that
        could otherwise loop infinitely."""
        seen: set[str] = set()
        current = node
        for _ in range(32):
            if current.alias_of is None:
                return current
            if current.id in seen:
                return current  # cycle — bail
            seen.add(current.id)
            target = self.find(current.alias_of)
            if target is None:
                return current  # broken alias — render the placeholder
            current = target
        return current

    def parent_of(self, node_id: str) -> Node | None:
        cache = getattr(self, "_lookup_parents", None)
        if cache is None:
            # See find(): rebuild the O(1) cache once instead of scanning
            # the whole tree on every call.
            self.refresh_lookup_cache()
            cache = self._lookup_parents
        return cache.get(node_id)

    def is_in_medical_branch(self, node_id: str) -> bool:
        """True when `node_id` is (or descends from) a node flagged
        `is_medical_root`. Walks up the parent chain; cycle-guarded."""
        seen: set = set()
        cur = self.find(node_id)
        while cur is not None and cur.id not in seen:
            if bool(getattr(cur, "is_medical_root", False)):
                return True
            seen.add(cur.id)
            cur = self.parent_of(cur.id)
        return False

    def index_of_child(self, parent_id: str, child_id: str) -> int:
        parent = self.find(parent_id)
        if parent is None:
            return -1
        for i, c in enumerate(parent.children):
            if c.id == child_id:
                return i
        return -1

    def depth_of(self, node_id: str) -> int:
        """Returns 0 for root, 1 for root's children, etc. Returns -1 if not found."""
        return _depth_recursive(self.root, node_id, 0)

    def collapsed_changes_for_map_levels(self, n_levels: int) -> dict[str, bool]:
        """Return {node_id: collapsed} so that exactly the first `n_levels` levels are visible
        (1 = root only, 2 = root + children, ...). Only includes nodes whose state changes."""
        if n_levels < 1:
            n_levels = 1
        changes: dict[str, bool] = {}
        _collect_level_changes(self.root, 0, n_levels - 1, changes)
        return changes

    def collapsed_changes_for_subtree_levels(
        self, root_id: str, n_levels: int
    ) -> dict[str, bool]:
        """Like the above but limited to the subtree rooted at `root_id`."""
        start = self.find(root_id)
        if start is None:
            return {}
        if n_levels < 1:
            n_levels = 1
        changes: dict[str, bool] = {}
        _collect_level_changes(start, 0, n_levels - 1, changes)
        return changes

    def collapsed_changes_expand_all(self) -> dict[str, bool]:
        return {n.id: False for n in self.all_nodes() if n.collapsed}


def _depth_recursive(node: Node, target_id: str, current: int) -> int:
    if node.id == target_id:
        return current
    for child in node.children:
        d = _depth_recursive(child, target_id, current + 1)
        if d >= 0:
            return d
    return -1


def _collect_level_changes(
    node: Node, depth: int, max_depth: int, out: dict[str, bool]
) -> None:
    """Walks `node`'s subtree. Nodes at depth == max_depth (deepest visible) should be
    collapsed (their children hidden). Nodes at shallower depths should be expanded.
    """
    if depth >= max_depth:
        if not node.collapsed:
            out[node.id] = True
    else:
        if node.collapsed:
            out[node.id] = False
    for child in node.children:
        _collect_level_changes(child, depth + 1, max_depth, out)
