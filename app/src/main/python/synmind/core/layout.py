"""Layout algorithms for mind maps.

All algorithms are **visibility-aware**: subtree sizing and child-iteration
stop at collapsed nodes, so the layout compacts when branches are hidden.

They are also **image-aware**: a node displaying an image band (above or
below its text) reports a larger leaf size to the layout, so siblings
get enough room and fit-to-view doesn't have to zoom way out to keep
image-heavy outliers visible.

`apply_layout(mind_map)` dispatches to the algorithm named by
`mind_map.layout_style`. Pure data; no Qt dependency.
"""
from __future__ import annotations

import math
import unicodedata
from pathlib import Path

from synmind.core.model import MindMap, Node

# Horizontal layouts (left/right branching)
H_STEP = 260  # minimum step; actual step accounts for parent's text width
V_LEAF = 60
V_PAD = 12          # between two adjacent leaf siblings
V_PAD_SUBTREE = 40  # between siblings when at least one has children; the
                    # subtree fills its slot edge-to-edge, so adjacent
                    # subtrees crowd if the pad doesn't account for that

# Vertical layouts (down/up branching)
V_STEP = 140
H_LEAF = 160
H_PAD = 32          # between two adjacent leaf siblings
H_PAD_SUBTREE = 72  # between siblings when at least one has children

# Minimalist / compact mode — MapCanvas flips this via
# `set_minimalist_layout(True/False)` when the user toggles the
# Minimalist Display option. The base values above are captured at
# import time so `set_minimalist_layout(False)` can restore them
# exactly (float multiplication can introduce drift on re-toggle).
_BASE_CONSTANTS = {
    "H_STEP": H_STEP,
    "V_LEAF": V_LEAF,
    "V_PAD": V_PAD,
    "V_PAD_SUBTREE": V_PAD_SUBTREE,
    "V_STEP": V_STEP,
    "H_LEAF": H_LEAF,
    "H_PAD": H_PAD,
    "H_PAD_SUBTREE": H_PAD_SUBTREE,
}
# Per-axis compact scales. The between-subtree pads (V_PAD_SUBTREE /
# H_PAD_SUBTREE) drop the most aggressively because those are the
# biggest source of "leaves far apart" when siblings have differently-
# shaped children — the layout reserves the tallest subtree's height
# for every branch. Squeezing them harder is what actually pulls the
# deepest visible nodes close together, which is the user-visible
# effect they asked for. Node-to-node steps (V_STEP / H_STEP) also
# shrink so parent-child chains stack tighter without overlapping.
_MINIMALIST_SCALE_SUBTREE = 0.30  # between-subtree pads
_MINIMALIST_SCALE_STEP = 0.55     # parent-child step
_MINIMALIST_SCALE_LEAF = 0.55     # leaf-to-leaf pads


def set_minimalist_layout(on: bool) -> None:
    """Toggle compact spacing across every layout algorithm. Uses
    per-axis scales so the SUBTREE pads (the biggest source of
    "leaves far apart" between siblings whose subtrees have unequal
    shapes) drop harder than the direct parent-child steps.

    When off, exact original values are restored from
    `_BASE_CONSTANTS` so repeated toggles don't drift."""
    global H_STEP, V_LEAF, V_PAD, V_PAD_SUBTREE
    global V_STEP, H_LEAF, H_PAD, H_PAD_SUBTREE
    if on:
        s_step = _MINIMALIST_SCALE_STEP
        s_leaf = _MINIMALIST_SCALE_LEAF
        s_sub = _MINIMALIST_SCALE_SUBTREE
        H_STEP = int(_BASE_CONSTANTS["H_STEP"] * s_step)
        V_LEAF = int(_BASE_CONSTANTS["V_LEAF"] * s_leaf)
        V_PAD = int(_BASE_CONSTANTS["V_PAD"] * s_leaf)
        V_PAD_SUBTREE = int(_BASE_CONSTANTS["V_PAD_SUBTREE"] * s_sub)
        V_STEP = int(_BASE_CONSTANTS["V_STEP"] * s_step)
        H_LEAF = int(_BASE_CONSTANTS["H_LEAF"] * s_leaf)
        H_PAD = int(_BASE_CONSTANTS["H_PAD"] * s_leaf)
        H_PAD_SUBTREE = int(_BASE_CONSTANTS["H_PAD_SUBTREE"] * s_sub)
    else:
        H_STEP = _BASE_CONSTANTS["H_STEP"]
        V_LEAF = _BASE_CONSTANTS["V_LEAF"]
        V_PAD = _BASE_CONSTANTS["V_PAD"]
        V_PAD_SUBTREE = _BASE_CONSTANTS["V_PAD_SUBTREE"]
        V_STEP = _BASE_CONSTANTS["V_STEP"]
        H_LEAF = _BASE_CONSTANTS["H_LEAF"]
        H_PAD = _BASE_CONSTANTS["H_PAD"]
        H_PAD_SUBTREE = _BASE_CONSTANTS["H_PAD_SUBTREE"]

# Bubble (radial)
BUBBLE_RADIUS = 240
BUBBLE_SUB_STEP = 200
BUBBLE_FAN = math.pi / 2.4

# Width / height estimation for layout (pure Python — no Qt font metrics
# available). Slightly generous so wide-text parents don't pack into
# their children.
_CHAR_WIDTH = 9.0
_NODE_PADDING_X = 32.0
_NODE_PADDING_Y = 20.0
_MIN_NODE_WIDTH = 100.0
# Max body width before text wraps. Must match NodeItem.EDIT_MAX_BODY_W;
# keep them in sync or the layout estimator will reserve too much
# horizontal room for long-text nodes that actually wrap.
_MAX_BODY_W = 520.0
_TEXT_H = 30.0  # single-line text height ballpark including descenders
_H_GAP = 60.0  # min visual gap between parent's right edge and child's left edge
# Sizes for the per-node topic bubble (mirror NodeItem.TOPIC_LABEL_*).
# When the map-level show_topic_label_on_descendants is ON and a node
# has any is_topic ancestor, the body grows by this much so the bubble
# has its own slot. The estimator can't know whether the ancestor is
# currently on-screen (a UI concept), so it reserves room as long as
# the ancestor exists — slightly over-reserves but never under-reserves.
_TOPIC_LABEL_HEIGHT = 16.0
_TOPIC_LABEL_INSET = 6.0
_TOPIC_LABEL_H_PAD = 8.0
_TOPIC_LABEL_MAX_CHARS = 28

# Image dimensions mirror NodeItem.MAX_IMAGE_W / MAX_IMAGE_H. A node
# in the current image mode might render up to one band above (its
# attached image) and one band below (first note image / PDF page),
# both capped at these sizes.
_IMG_W = 200.0
_IMG_H = 140.0
_IMG_PAD = 6.0

# Extensions that produce a thumbnail in note-image mode. PDFs render
# their first page; the rest load directly.
_NOTE_IMG_EXTS = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".pdf"}
)


def _display_source(node: Node, mind_map: MindMap) -> Node:
    """Return the node whose image / note content this node will *show*.
    For a regular node, that's itself. For an alias, it's the resolved
    master — matches NodeItem._display_node()'s render-time behavior so
    layout sizes the slot for what will actually appear on screen."""
    if node.alias_of is None:
        return node
    try:
        return mind_map.resolve_alias(node)
    except Exception:
        return node


def _shows_node_image(node: Node, mind_map: MindMap) -> bool:
    """Will this node render its attached node-image (above the text)
    under the map's current image-display mode? Cheap predicate — the
    actual decode happens at render time. Aliases inherit the master's
    image_data, so we resolve before checking."""
    src = _display_source(node, mind_map)
    if not src.image_data:
        return False
    mode = getattr(mind_map, "node_image_mode", "node")
    if mode == "none":
        return False
    if mode == "obey" and src.hide_node_image:
        return False
    return True


def _shows_note_image(node: Node, mind_map: MindMap) -> bool:
    """Will this node render a note image (below the text)? True when
    the mode shows note images AND the note has either an embedded
    `<img>` or an image / PDF attachment. Heuristic — overestimates by
    matching on extension and the presence of an `<img>` tag, which is
    safer for layout than underestimating (extra spacing is harmless;
    overlap is not)."""
    mode = getattr(mind_map, "node_image_mode", "node")
    if mode not in ("note", "obey"):
        return False
    src = _display_source(node, mind_map)
    if mode == "obey" and src.hide_note_image:
        return False
    if src.note_html and "<img" in src.note_html.lower():
        return True
    # Any attachment now renders SOMETHING in the note-image slot:
    # images / PDF first page as before, Office thumbnails from
    # docProps/thumbnail.*, and the OS's stock file icon as a
    # fallback for everything else. So the layout must reserve the
    # preview strip whenever there's any attachment, not just for
    # the image/PDF subset — otherwise adding a .docx/.xlsx/.pptx/
    # etc. grows the node's rendered height without the sibling
    # layout knowing, and neighbors overlap.
    if src.attachments:
        return True
    return False


def _char_visual_width(ch: str) -> float:
    """Per-character display width estimate for the layout's text-width
    sum. CJK ideographs, fullwidth ASCII, and other "wide" Unicode
    classes are roughly twice the width of narrow ASCII at the same
    point size — using a single `len(text) * _CHAR_WIDTH` formula
    catastrophically undercounts Japanese / Chinese / Korean node
    titles, which is what causes children to render on top of the
    parent's badge column."""
    eaw = unicodedata.east_asian_width(ch)
    # F = Fullwidth (e.g. ＡＢＣ), W = Wide (most CJK).
    # A = Ambiguous — usually narrow in Western fonts but rendered
    # wide in CJK contexts; treat as narrow here, since the safety
    # margin in _H_GAP covers the occasional miss.
    if eaw in ("F", "W"):
        return _CHAR_WIDTH * 2.0
    return _CHAR_WIDTH


_MAX_TEXT_W = _MAX_BODY_W - _NODE_PADDING_X


def _estimated_text_width(text: str, font_scale: float = 1.0) -> float:
    if not text:
        return _CHAR_WIDTH * font_scale
    # Multi-line aware: width = widest \n-split line. Summing every
    # character would treat 'line1\nline2' as if it rendered on one
    # row (twice as wide as either line), inflating the layout step
    # for short multi-line nodes. Capped at _MAX_TEXT_W to mirror the
    # node renderer's wrap-at-EDIT_MAX_BODY_W behavior — without the
    # cap, long-text nodes would reserve hundreds of pixels of layout
    # room that the actual rendered (wrapped) node doesn't use.
    #
    # `font_scale` multiplies per-character widths so a per-node
    # text_font_size override gets the right horizontal reservation.
    # The wrap cap stays in absolute pixels (the renderer wraps at
    # _MAX_TEXT_W regardless of font size).
    lines = text.split("\n") or [text]
    natural = max(
        sum(_char_visual_width(ch) * font_scale for ch in (line if line else " "))
        for line in lines
    )
    return min(natural, _MAX_TEXT_W)


def _estimated_line_count(text: str, font_scale: float = 1.0) -> int:
    """Lines the node renderer will draw, counting explicit \\n
    breaks PLUS wrap-induced line breaks. Mirrors the renderer's
    QTextDocument wrap-at-_MAX_TEXT_W behavior so tall wrapped nodes
    get the vertical layout room they need.

    `font_scale` multiplies the per-character width before the wrap
    check so a per-node `text_font_size` override produces the
    correct wrapped-line count. A node with a 1.6× font scale that
    fills _MAX_TEXT_W at base size needs roughly 2 lines at the
    enlarged size — without scaling, the layout would under-reserve
    vertical room and the next sibling would overlap the wrapped
    second line.
    """
    if not text:
        return 1
    line_count = 0
    for line in text.split("\n"):
        # Empty \n-separated entry still occupies one rendered row.
        width = sum(_char_visual_width(ch) * font_scale for ch in (line if line else " "))
        if width <= _MAX_TEXT_W:
            line_count += 1
        else:
            # Ceiling-divide so a line that's 1.x wraps to 2 rows.
            line_count += int((width + _MAX_TEXT_W - 1) // _MAX_TEXT_W)
    return max(1, line_count)


def _node_layout_size(node: Node, mind_map: MindMap) -> tuple[float, float]:
    """Estimated (width, height) for layout. Wider / taller when the
    node displays one or both image bands. The text width is summed
    per-character so CJK / fullwidth text gets the wider estimate it
    needs. In below-badge mode, the height also includes the badge
    row beneath the body so vertical layouts leave room for it.

    Memoized for the duration of an `apply_layout` call via the cache
    dict that `apply_layout` stashes on `mind_map`. The tidy-tree
    recursion calls this for the same node multiple times — once in
    `_h_subtree_height` and again in `_layout_h_children` for both
    width and height, repeated at every depth level — so for a deep
    map the same per-node text/badge/topic walk was running 5–10x
    over. Per-call cache turns those into dict lookups. The cache
    keys on `node.id`; tidy-tree never mutates layout-relevant Node
    fields mid-pass, so a single key remains valid across the whole
    call. `apply_layout` clears the cache on exit so subsequent
    calls don't see stale entries from a different model state.
    """
    cache = getattr(mind_map, "_layout_size_cache", None)
    if cache is not None:
        cached = cache.get(node.id)
        if cached is not None:
            return cached
    # Per-node font scaling. `_CHAR_WIDTH` and `_TEXT_H` are calibrated
    # for the default 11pt theme font. When the user overrides a
    # node's font size via Text Style → Font Size…, the rendered
    # body grows proportionally; without this scale, the layout
    # reserves 11pt-worth of slot for what's actually painted at
    # (say) 18pt, and siblings end up overlapping the larger node.
    # User-reported: nodes stacking on top of each other after
    # bumping a node's font size. We keep the wrap point in absolute
    # pixels (the renderer wraps at _MAX_TEXT_W regardless of font
    # size) but scale the per-character width and per-line height to
    # match what's actually being painted.
    base_font_size = 11
    node_font_size = (
        getattr(node, "text_font_size", None) or base_font_size
    )
    font_scale = (
        node_font_size / base_font_size if base_font_size > 0 else 1.0
    )
    text_w = max(
        _MIN_NODE_WIDTH,
        _estimated_text_width(node.text or " ", font_scale),
    )
    w = text_w + _NODE_PADDING_X
    # Multi-line text grows the node vertically — one _TEXT_H per
    # \n-separated line. Without this, sibling nodes overlap the
    # extra rows of any node with embedded newlines. font_scale also
    # threads through `_estimated_line_count` so a big-font node's
    # wrapped line count is computed correctly — without that, the
    # height under-reserves for a node that's wider after scaling and
    # therefore wraps onto extra rows the layout doesn't know about.
    h = (
        _TEXT_H * font_scale * _estimated_line_count(node.text or " ", font_scale)
        + _NODE_PADDING_Y
    )
    if _shows_node_image(node, mind_map):
        w = max(w, _IMG_W + _NODE_PADDING_X)
        h += _IMG_H + _IMG_PAD
    if _shows_note_image(node, mind_map):
        w = max(w, _IMG_W + _NODE_PADDING_X)
        h += _IMG_H + _IMG_PAD
    # Below-mode badge row eats vertical space. Without this, two
    # siblings with badges sit so close their badges overlap with
    # the next node's body.
    h += _estimated_badge_extra_height(node, mind_map)
    # The under-node M / #N badges add their own row regardless of
    # badge_position. Mirrors NodeItem._under_node_badge_extra_height.
    h += _estimated_under_node_badge_extra_height(node, mind_map)
    # Last-edited pill, which sits above the body.
    h += _estimated_edited_date_extra_height(node, mind_map)
    # The shortcut pill ("Shift+Alt+N") is wider than the smallest
    # nodes — siblings of a shortcut node would crowd it without
    # reserving the extra horizontal room.
    w = max(w, _estimated_under_node_badge_extra_width(node, mind_map))
    # Per-node topic bubble — reserves extra height + width when the
    # map-level toggle is on AND a topic ancestor exists. Conservative
    # over-estimate (assumes the ancestor is always off-screen) since
    # the actual visibility is a runtime UI concept the layout can't
    # see. Without this reservation, sibling nodes pack right up
    # against a node whose body has just grown to fit a bubble.
    tb_w, tb_h = _estimated_topic_label_extra(node, mind_map)
    h += tb_h
    w = max(w, tb_w)
    # A manual width override (drag the node's edge, or Set Width…) is
    # what the RENDERER draws — it replaces the computed body width
    # outright. The estimator knew nothing about it, so a node widened
    # to 600px was still laid out as if it were 130 and its child column
    # landed on top of it.
    try:
        manual = getattr(node, "manual_width", None)
        if manual is not None:
            w = max(w, float(manual))
    except (TypeError, ValueError):
        pass
    # MEASURED sizes win over every estimate above. The estimator is
    # pure Python with no font metrics, so it can only approximate what
    # Qt will draw — and it approximates LOW for ordinary Latin text,
    # which is how nodes ended up overlapping. When the canvas has
    # actually rendered a node it publishes the real footprint (body +
    # badges + pills) in `mind_map._layout_measured_sizes`, and that is
    # used instead. `max` rather than a straight swap: the estimator
    # reserves for things that may not be on screen right now (a topic
    # bubble whose ancestor is scrolled away), and under-reserving is
    # the failure that matters.
    measured = getattr(mind_map, "_layout_measured_sizes", None)
    if measured:
        got = measured.get(node.id)
        if got:
            w = max(w, float(got[0]))
            h = max(h, float(got[1]))
    result = (w, h)
    if cache is not None:
        cache[node.id] = result
    return result


# A topic name at or under this length shows whole on the bullet;
# anything longer collapses to just its first word to stay compact.
_TOPIC_BULLET_LONG_AT = 14


def topic_bullet_text(
    full_text: str,
    long_at: int = _TOPIC_BULLET_LONG_AT,
    max_chars: int = _TOPIC_LABEL_MAX_CHARS,
) -> str:
    """The label shown on a descendant's "under topic X" bullet: the
    topic's name when it's short, else just its FIRST word so the bullet
    stays compact. A single over-long word is ellipsis-truncated. Shared
    by the layout reservation here and the NodeItem paint so the reserved
    width matches what's drawn."""
    text = (full_text or "").replace("\n", " ").strip()
    if not text or len(text) <= long_at:
        return text
    first = text.split(" ", 1)[0]
    if len(first) > max_chars:
        first = first[: max_chars - 1] + "…"
    return first


_TOPIC_STACK_GAP = 2  # vertical gap between stacked topic bullets


def _alias_index(mind_map):
    """{master_id: [alias Node, …]}, built once per apply_layout call and
    stashed on the map so topic-bullet sizing can find a node's alias
    siblings without re-scanning the whole tree per node."""
    idx = getattr(mind_map, "_alias_index", None)
    if idx is None:
        idx = {}
        for n in mind_map.all_nodes():
            m = getattr(n, "alias_of", None)
            if m:
                idx.setdefault(m, []).append(n)
        mind_map._alias_index = idx
    return idx


def _alias_group_topic_texts(node: Node, mind_map: MindMap) -> list:
    """First-word bullet texts for the DISTINCT topics of `node`'s alias
    group (the master and every alias), the node's own topic first.
    Mirrors MapCanvas.topic_labels_for_node so the reserved layout space
    matches what NodeItem draws."""
    instances = [node]
    master = node
    if getattr(node, "alias_of", None):
        master = mind_map.find(node.alias_of) or node
    group = _alias_index(mind_map).get(master.id)
    if getattr(node, "alias_of", None) or group:
        for inst in [master] + list(group or []):
            if inst.id != node.id:
                instances.append(inst)
    seen: set = set()
    texts: list = []
    for inst in instances:
        t = _find_topic_ancestor(inst, mind_map)
        if t is not None and t.id not in seen:
            seen.add(t.id)
            txt = topic_bullet_text(t.text)
            if txt:
                texts.append(txt)
    return texts


def _estimated_topic_label_extra(
    node: Node, mind_map: MindMap,
) -> tuple[float, float]:
    """Extra (width, height) reserved for the per-node topic-name
    bullet(s), or (0, 0) when none apply. A node can carry SEVERAL topic
    bullets (its alias group's distinct topics) stacked vertically — this
    reserves room for the whole stack. A node that is itself a topic shows
    the "T" circle instead. Mirrors NodeItem's bubble sizing."""
    if bool(getattr(node, "is_topic", False)):
        return 0.0, 0.0
    texts = _alias_group_topic_texts(node, mind_map)
    if not texts:
        return 0.0, 0.0
    max_w = max(
        sum(_char_visual_width(ch) for ch in t) + 2 * _TOPIC_LABEL_H_PAD
        for t in texts
    )
    n = len(texts)
    extra_w = max_w + 2 * _TOPIC_LABEL_INSET
    extra_h = (
        n * _TOPIC_LABEL_HEIGHT
        + (n - 1) * _TOPIC_STACK_GAP
        + _TOPIC_LABEL_INSET
    )
    return extra_w, extra_h


def _find_topic_ancestor(node: Node, mind_map: MindMap):
    cur = mind_map.parent_of(node.id)
    while cur is not None:
        if bool(getattr(cur, "is_topic", False)):
            return cur
        cur = mind_map.parent_of(cur.id)
    return None


def _estimated_node_width(node: Node, mind_map: MindMap) -> float:
    return _node_layout_size(node, mind_map)[0]


def _estimated_node_height(node: Node, mind_map: MindMap) -> float:
    return _node_layout_size(node, mind_map)[1]


# Per-badge dimensions, mirroring NodeItem.BADGE_RADIUS / BADGE_GAP.
# Each badge takes 2*radius + gap = 22 + 6 horizontal pixels to the
# right of the node body. The layout has to reserve this column or
# children land on top of the indicators.
_BADGE_SLOT_W = 28.0


def _estimated_badge_count(node: Node, mind_map: MindMap) -> int:
    """Number of badges NodeItem will draw to the right of `node`.

    Mirrors NodeItem._badge_area_width(). Pure data — bookmark and
    backlink badges depend on canvas state we don't have here, so they
    aren't counted; in practice they're rare and the SAFETY in
    _h_step_for absorbs the small undercount."""
    count = 0
    if node.collapsed and node.children:
        count += 1                                  # collapse indicator
    if node.link_target_id:
        count += 1                                  # outgoing link
    if node.tags:
        count += 1                                  # tag badge
    if node.review_marked:
        count += 1                                  # node review (R yellow)
    if node.note_html:
        count += 1                                  # note (N)
    if node.note_review_marked:
        count += 1                                  # note review (R teal)
    if node.todo_marked:
        count += 1                                  # to-do (D)
    if node.alias_of:
        count += 1                                  # alias (A)
    if node.attachments:
        count += 1                                  # attachment
    if node.external_link:
        count += 1                                  # external link
    return count


def _estimated_badge_area_width(node: Node, mind_map: MindMap) -> float:
    """Horizontal column the badges occupy. Zero in 'below' mode —
    the badges sit underneath the body in that layout, so no
    horizontal column needs reserving."""
    if (
        getattr(mind_map, "badge_position", "right") or "right"
    ) == "below":
        return 0.0
    n = _estimated_badge_count(node, mind_map)
    return n * _BADGE_SLOT_W


def _estimated_under_node_badge_extra_height(
    node: Node, mind_map: MindMap,
) -> float:
    """Vertical room the M (display memory) + #N (shortcut slot)
    strip takes UNDER the body. These badges sit below the body
    regardless of badge_position so the node text is never blocked.
    Returns 0 when neither badge would show. Must mirror
    NodeItem._under_node_badge_extra_height (constants kept in sync
    by inspection — UNDER_NODE_BADGE_HEIGHT=14, GAP=4)."""
    has_memory = node.id in (mind_map.node_display_memories or {})
    has_shortcut = any(
        v == node.id
        for v in (mind_map.node_shortcuts or {}).values()
    )
    if not (has_memory or has_shortcut):
        return 0.0
    # 4 (top gap) + 14 (badge) + 4 (bottom gap)
    return 22.0


def _estimated_edited_date_extra_height(
    node: Node, mind_map: MindMap,
) -> float:
    """Vertical room the last-edited pill takes ABOVE the body. Must
    mirror NodeItem._edited_date_extra_height_above (14 + 3). Without
    reserving it here the pill lands in the gap between two nodes and
    reads as belonging to the one below."""
    if not getattr(mind_map, "show_edited_date", False):
        return 0.0
    if not getattr(node, "updated_at", None):
        return 0.0
    return 17.0


# Approximate width of the "Shift+Alt+N" pill at the default bold
# 9-10pt font. Estimated rather than measured (this module is Qt-free)
# — chosen to comfortably fit the widest single-slot label. If the
# user customizes their theme to a much larger font, the pill may
# extend a few pixels past this estimate; that's a visual overlap
# only, doesn't break layout.
_SHORTCUT_PILL_W = 82.0


def _estimated_under_node_badge_extra_width(
    node: Node, mind_map: MindMap,
) -> float:
    """Minimum horizontal room the under-body strip needs. The
    Shift+Alt+N pill is wider than _MIN_NODE_WIDTH, so without this
    siblings of a small shortcut node would crowd it (the pill paints
    fine, but neighboring nodes get drawn on top in dense layouts).
    Returns 0 when this node has no under-strip badges."""
    has_memory = node.id in (mind_map.node_display_memories or {})
    has_shortcut = any(
        v == node.id
        for v in (mind_map.node_shortcuts or {}).values()
    )
    if not (has_shortcut or has_memory):
        return 0.0
    w = 0.0
    if has_shortcut:
        w += _SHORTCUT_PILL_W + 2.0   # pill + left margin
    if has_memory:
        # gap (4) + M square (14) + right margin (2)
        w += 4.0 + 14.0 + 2.0
    return w


def _estimated_badge_extra_height(node: Node, mind_map: MindMap) -> float:
    """Vertical room the badge row takes UNDER the body when
    `badge_position == "below"`. Mirrors NodeItem.boundingRect()'s
    below-mode growth: gap + diameter + gap when at least one
    badge is present, zero otherwise. Returns 0 in 'right' mode
    (badges grow width there, handled by _estimated_badge_area_width).
    Without this, a node with a D / R badge in below-mode collides
    with its next sibling because the layout sees only body height."""
    if (
        getattr(mind_map, "badge_position", "right") or "right"
    ) != "below":
        return 0.0
    if _estimated_badge_count(node, mind_map) <= 0:
        return 0.0
    # BADGE_RADIUS = 11, BADGE_GAP = 6 in NodeItem.
    return 6.0 + 22.0 + 6.0


def _h_step_for(parent: Node, mind_map: MindMap) -> float:
    """Horizontal step from parent.x to child.x that keeps the child's
    left edge at least _H_GAP past the parent's RIGHTMOST visible
    element. That includes the badge column — without this, a node
    with several badges (R, N, R-teal, etc.) ends up with its
    children rendered on top of the indicators in follow / depth=1
    views."""
    body_w = _estimated_node_width(parent, mind_map)
    badge_w = _estimated_badge_area_width(parent, mind_map)
    return max(H_STEP, body_w + badge_w + _H_GAP)


# --- horizontal: shared helpers ------------------------------------------

def _h_pad_between(a: Node, b: Node, mind_map: MindMap | None = None) -> float:
    """Pad between two adjacent siblings. Subtree-vs-anything gets the
    bigger pad; leaf-vs-leaf keeps the tight pad. Without this two-tier
    scheme, sibling subtrees crowd because each fills its slot fully and
    only V_PAD separates them at the boundary.

    Aliases-with-master count as branches even when `.children` is
    empty — `_render_alias_ghosts` populates ghost children under the
    alias at render time, so adjacent siblings need the larger pad to
    clear those ghosts."""
    def _is_branch(node: Node) -> bool:
        if node.collapsed:
            return False
        if node.children:
            return True
        if mind_map is not None and getattr(node, "alias_of", None):
            master = mind_map.find(node.alias_of)
            if master is not None and master.id != node.id and master.children:
                return True
        return False
    return V_PAD_SUBTREE if (_is_branch(a) or _is_branch(b)) else V_PAD


def _h_subtree_height(
    node: Node, mind_map: MindMap, _alias_seen: set[str] | None = None,
) -> float:
    # Alias-with-master: this node renders the master's subtree as
    # ghosts at translated coordinates. The tidy-tree must reserve
    # the same vertical room here that the master's subtree takes,
    # otherwise adjacent siblings land underneath those ghosts —
    # which is what the user sees as overlap between e.g. EXPENSES's
    # children and a TRAVEL alias's ghost subtree at the same column.
    # `_alias_seen` guards against cyclic alias graphs (already
    # capped at the resolve_alias level but defended again here).
    #
    # Exception: in follow / follow+ / recall modes the depth limit
    # hides the alias's ghost descendants, so reserving their height
    # here leaves a meaningless vertical gap between this node and
    # its next sibling. Treat the alias as a leaf for height
    # purposes in those modes. Standard / Free modes still reserve
    # the master's full subtree height (the ghosts ARE drawn).
    _follow_like_modes = ("follow", "follow_plus", "recall", "recall_seq")
    if not node.collapsed and getattr(node, "alias_of", None):
        if getattr(mind_map, "display_mode", "standard") not in _follow_like_modes:
            seen = _alias_seen if _alias_seen is not None else set()
            if node.id not in seen:
                master = mind_map.find(node.alias_of)
                if (
                    master is not None
                    and master.id != node.id
                    and master.id not in seen
                    and master.children
                ):
                    seen = seen | {node.id}
                    # Sum the master's CHILDREN rather than recursing on
                    # the master itself, because the master's own
                    # `.collapsed` flag doesn't apply here. Whether an
                    # alias shows its ghosts is decided by the ALIAS's
                    # flag alone (`_render_alias_ghosts` ignores the
                    # master's at the first level, deliberately — see the
                    # comment there). Recursing on the master reserved a
                    # single leaf's worth of room whenever the master
                    # happened to be collapsed somewhere else in the map,
                    # while the ghosts still drew in full — so they
                    # landed on top of the alias's siblings.
                    kids = master.children
                    h = sum(
                        _h_subtree_height(c, mind_map, seen) for c in kids
                    )
                    for i in range(len(kids) - 1):
                        h += _h_pad_between(kids[i], kids[i + 1], mind_map)
                    # Floor at the ALIAS's own body — that is the node
                    # actually drawn in this slot.
                    return max(h, _estimated_node_height(node, mind_map))
    if node.collapsed or not node.children:
        # Image-bearing leaves are much taller than the V_LEAF baseline;
        # using the larger of the two prevents adjacent siblings from
        # overlapping when one of them displays a PDF preview.
        return max(V_LEAF, _estimated_node_height(node, mind_map))
    h = sum(_h_subtree_height(c, mind_map, _alias_seen) for c in node.children)
    for i in range(len(node.children) - 1):
        h += _h_pad_between(node.children[i], node.children[i + 1], mind_map)
    # The parent itself may be taller than its children's combined
    # subtree slot (single-child branches in particular). Make sure
    # the slot is at least as tall as the parent so siblings of this
    # subtree don't crash into the parent's image.
    return max(h, _estimated_node_height(node, mind_map))


def _layout_h_children(
    anchor: Node, children: list[Node], direction: int, mind_map: MindMap
) -> None:
    """Common positioning loop for one branch (single side of a parent).
    Used by both the root-level alternating layout and per-node recursion.

    `anchor.x` / `anchor.y` are the anchor node's TOP-LEFT (which is how
    NodeItem renders — it puts its boundingRect's origin at setPos). We
    derive the anchor's visual center from its estimated size, distribute
    children's slots around that center, and write each child's top-left
    so the rendered box sits centered within its allocated slot. Without
    this, image-bearing nodes (whose slot equals their actual size)
    would render with their top at the slot center — overflowing into
    the next sibling's slot.
    """
    if not children:
        return
    anchor_h = _estimated_node_height(anchor, mind_map)
    anchor_w = _estimated_node_width(anchor, mind_map)
    anchor_badge_w = _estimated_badge_area_width(anchor, mind_map)
    anchor_center_y = anchor.y + anchor_h / 2

    heights = [_h_subtree_height(c, mind_map) for c in children]
    pads = [
        _h_pad_between(children[i], children[i + 1], mind_map)
        for i in range(len(children) - 1)
    ]
    total = sum(heights) + sum(pads)
    y_cursor = anchor_center_y - total / 2
    step = _h_step_for(anchor, mind_map)
    # User-adjustable per map (Display Settings → Map & Layout →
    # "Horizontal line length"); falls back to the original hardcoded
    # _H_GAP for old maps / test contexts that never set the field.
    h_gap = float(
        getattr(mind_map, "horizontal_line_length", _H_GAP) or _H_GAP
    )
    for i, (child, h) in enumerate(zip(children, heights)):
        child_h = _estimated_node_height(child, mind_map)
        child_w = _estimated_node_width(child, mind_map)
        # X: place child so the gap between parent's far edge and
        # child's near edge is preserved regardless of relative widths.
        # For direction>0 the parent's badge column lives between body
        # and child, so the gap is measured from the BADGE area's right
        # edge. For direction<0 badges sit on the opposite side and
        # don't enter the equation.
        if direction > 0:
            child.x = anchor.x + anchor_w + anchor_badge_w + h_gap
        else:
            child.x = anchor.x - h_gap - child_w
        # Y: top-left of the node, vertically centered inside its slot.
        child.y = y_cursor + (h - child_h) / 2
        _layout_h_subtree(child, direction, mind_map)
        y_cursor += h
        if i < len(children) - 1:
            y_cursor += pads[i]


def _layout_h_side(
    parent: Node, children: list[Node], direction: int, mind_map: MindMap
) -> None:
    _layout_h_children(parent, children, direction, mind_map)


def _layout_h_subtree(node: Node, direction: int, mind_map: MindMap) -> None:
    if not node.children:
        return
    # Reposition children even when `node` is collapsed. Collapsed
    # subtrees are hidden in normal views, but an ALIAS elsewhere in the
    # tree can still expose this subtree as ghosts — and the ghost
    # positions come from these stored x/y. Skipping collapsed nodes
    # leaves stale positions behind, causing ghosts to land far from
    # their alias. `_h_subtree_height` still respects collapse for
    # sibling sizing, so layout dimensions are unchanged.
    _layout_h_children(node, node.children, direction, mind_map)


def apply_tidy_branched(mind_map: MindMap) -> None:
    root = mind_map.root
    root.x = 0
    root.y = 0
    if root.collapsed:
        return
    _layout_h_side(root, root.children[::2], direction=1, mind_map=mind_map)
    _layout_h_side(root, root.children[1::2], direction=-1, mind_map=mind_map)


def apply_tidy_right(mind_map: MindMap) -> None:
    root = mind_map.root
    root.x = 0
    root.y = 0
    if root.collapsed:
        return
    _layout_h_side(root, root.children, direction=1, mind_map=mind_map)


def apply_tidy_left(mind_map: MindMap) -> None:
    root = mind_map.root
    root.x = 0
    root.y = 0
    if root.collapsed:
        return
    _layout_h_side(root, root.children, direction=-1, mind_map=mind_map)


# --- vertical: shared helpers --------------------------------------------

def _v_pad_between(a: Node, b: Node) -> float:
    a_branch = (not a.collapsed) and bool(a.children)
    b_branch = (not b.collapsed) and bool(b.children)
    return H_PAD_SUBTREE if (a_branch or b_branch) else H_PAD


def _v_subtree_width(node: Node, mind_map: MindMap) -> float:
    if node.collapsed or not node.children:
        return max(H_LEAF, _estimated_node_width(node, mind_map))
    w = sum(_v_subtree_width(c, mind_map) for c in node.children)
    for i in range(len(node.children) - 1):
        w += _v_pad_between(node.children[i], node.children[i + 1])
    return max(w, _estimated_node_width(node, mind_map))


def _v_step_for(parent: Node, mind_map: MindMap) -> float:
    """Vertical step that clears the parent's full height (text + image
    bands) plus the configured V_STEP padding."""
    return max(V_STEP, _estimated_node_height(parent, mind_map) + _IMG_PAD * 2 + 30.0)


def _layout_v_subtree(node: Node, direction: int, mind_map: MindMap) -> None:
    if not node.children:
        return
    # Same reasoning as `_layout_h_subtree`: keep positioning descendants
    # of collapsed nodes so any alias that exposes this subtree as
    # ghosts has fresh, sensible coordinates to translate from. Same
    # top-left-vs-slot-center fix as `_layout_h_children` applies here.
    node_h = _estimated_node_height(node, mind_map)
    node_w = _estimated_node_width(node, mind_map)
    node_center_x = node.x + node_w / 2

    widths = [_v_subtree_width(c, mind_map) for c in node.children]
    pads = [
        _v_pad_between(node.children[i], node.children[i + 1])
        for i in range(len(node.children) - 1)
    ]
    total = sum(widths) + sum(pads)
    x_cursor = node_center_x - total / 2
    if direction > 0:
        child_y = node.y + node_h + (V_STEP - node_h) / 2 if V_STEP > node_h else node.y + node_h + 20
    else:
        # When stacking upwards, the child's bottom should clear the
        # parent's top with comparable padding.
        child_y_placeholder = 0  # filled per-child below since we need child_h
    for i, (child, w) in enumerate(zip(node.children, widths)):
        child_h = _estimated_node_height(child, mind_map)
        child_w = _estimated_node_width(child, mind_map)
        if direction > 0:
            child.y = node.y + node_h + 30  # 30px vertical gap below parent
        else:
            child.y = node.y - child_h - 30  # 30px above parent's top
        # X: top-left, centered horizontally in slot.
        child.x = x_cursor + (w - child_w) / 2
        _layout_v_subtree(child, direction, mind_map)
        x_cursor += w
        if i < len(node.children) - 1:
            x_cursor += pads[i]


def apply_tidy_down(mind_map: MindMap) -> None:
    root = mind_map.root
    root.x = 0
    root.y = 0
    _layout_v_subtree(root, direction=1, mind_map=mind_map)


def apply_tidy_up(mind_map: MindMap) -> None:
    root = mind_map.root
    root.x = 0
    root.y = 0
    _layout_v_subtree(root, direction=-1, mind_map=mind_map)


# --- bubble (radial) -----------------------------------------------------

def apply_bubble(mind_map: MindMap) -> None:
    root = mind_map.root
    root.x = 0
    root.y = 0
    if root.collapsed:
        return
    n = len(root.children)
    if n == 0:
        return
    # Inflate the bubble's first-ring radius when images are in play so
    # the children don't intersect the root's image band. The radius is
    # measured from the visual centre of the root to the visual centre
    # of each child, then we offset by half each child's size to write
    # top-left coords.
    root_w = _estimated_node_width(root, mind_map)
    root_h = _estimated_node_height(root, mind_map)
    root_cx = root.x + root_w / 2
    root_cy = root.y + root_h / 2
    radius = max(
        BUBBLE_RADIUS,
        max(root_w, root_h) + BUBBLE_RADIUS / 2,
    )
    for i, child in enumerate(root.children):
        angle = 2 * math.pi * i / n - math.pi / 2
        child_w = _estimated_node_width(child, mind_map)
        child_h = _estimated_node_height(child, mind_map)
        cx = root_cx + radius * math.cos(angle)
        cy = root_cy + radius * math.sin(angle)
        child.x = cx - child_w / 2
        child.y = cy - child_h / 2
        _bubble_subtree(child, angle, radius, mind_map, root_cx, root_cy)


def _bubble_subtree(
    node: Node, parent_angle: float, parent_radius: float,
    mind_map: MindMap, origin_cx: float, origin_cy: float,
) -> None:
    if node.collapsed or not node.children:
        return
    node_w = _estimated_node_width(node, mind_map)
    node_h = _estimated_node_height(node, mind_map)
    sub_step = max(
        BUBBLE_SUB_STEP,
        max(node_w, node_h) + BUBBLE_SUB_STEP / 2,
    )
    r = parent_radius + sub_step
    n = len(node.children)
    if n == 1:
        c = node.children[0]
        c_w = _estimated_node_width(c, mind_map)
        c_h = _estimated_node_height(c, mind_map)
        cx = origin_cx + r * math.cos(parent_angle)
        cy = origin_cy + r * math.sin(parent_angle)
        c.x = cx - c_w / 2
        c.y = cy - c_h / 2
        _bubble_subtree(c, parent_angle, r, mind_map, origin_cx, origin_cy)
        return
    span = BUBBLE_FAN
    step = span / (n - 1)
    start = parent_angle - span / 2
    for i, c in enumerate(node.children):
        a = start + i * step
        c_w = _estimated_node_width(c, mind_map)
        c_h = _estimated_node_height(c, mind_map)
        cx = origin_cx + r * math.cos(a)
        cy = origin_cy + r * math.sin(a)
        c.x = cx - c_w / 2
        c.y = cy - c_h / 2
        _bubble_subtree(c, a, r, mind_map, origin_cx, origin_cy)


# --- dispatcher ----------------------------------------------------------

# --- newly-activated layouts (formerly deferred) -------------------------
# These started life as "v0.5 deferred" placeholders that wanted their
# own data model (cause/effect roles, dates, etc). The activated forms
# below derive a reasonable VISUAL interpretation from the existing
# tree structure, so users can pick the style today without authoring
# extra metadata — later versions can layer real semantics on top.

def _walk_h_subtree(node: "Node", mind_map: "MindMap", direction: int) -> float:
    """Lay out `node`'s subtree to one side (direction = +1 right, -1
    left), returning the vertical span the subtree occupied. Used by
    the Double Bubble + Multi-Flow style layouts so each child's
    descendants stack neatly without overlapping siblings."""
    if node.collapsed or not node.children:
        nh = _estimated_node_height(node, mind_map)
        return nh + V_PAD
    total_h = 0.0
    child_sizes: list[tuple["Node", float]] = []
    for c in node.children:
        sub_h = _walk_h_subtree_size(c, mind_map)
        child_sizes.append((c, sub_h))
        total_h += sub_h
    nw = _estimated_node_width(node, mind_map)
    parent_cx = node.x + nw / 2
    parent_cy = node.y + _estimated_node_height(node, mind_map) / 2
    cur_y = parent_cy - total_h / 2
    for c, sub_h in child_sizes:
        cw = _estimated_node_width(c, mind_map)
        ch = _estimated_node_height(c, mind_map)
        if direction > 0:
            c.x = parent_cx + 160 + nw / 2
        else:
            c.x = parent_cx - 160 - nw / 2 - cw
        c.y = cur_y + sub_h / 2 - ch / 2
        _walk_h_subtree(c, mind_map, direction)
        cur_y += sub_h
    return max(total_h, _estimated_node_height(node, mind_map) + V_PAD)


def _walk_h_subtree_size(node: "Node", mind_map: "MindMap") -> float:
    """Tree-walk that just measures the vertical span `node`'s subtree
    will need. Mirror of `_walk_h_subtree` minus the position writes."""
    if node.collapsed or not node.children:
        return _estimated_node_height(node, mind_map) + V_PAD
    return sum(
        _walk_h_subtree_size(c, mind_map) for c in node.children
    )


def apply_double_bubble(mind_map: "MindMap") -> None:
    """Compare/contrast layout. Root and its FIRST child act as the
    two subject nodes (drawn side by side). All other root children
    are placed between them as 'shared attributes', stacked vertically.
    Subjects' OWN subtrees radiate outward on opposite sides."""
    root = mind_map.root
    root.x = 0
    root.y = 0
    if root.collapsed or not root.children:
        return
    rw = _estimated_node_width(root, mind_map)
    rh = _estimated_node_height(root, mind_map)
    # Subject A = root (already at 0). Subject B = first child placed
    # to the right; remaining children stack between as shared traits.
    subject_b = root.children[0]
    shared = root.children[1:]
    sb_w = _estimated_node_width(subject_b, mind_map)
    sb_h = _estimated_node_height(subject_b, mind_map)
    # Place B far enough right to leave room for shared traits column
    # in the middle. The column needs ~280 px.
    column_x = rw + 200
    subject_b.x = column_x + 280
    subject_b.y = (rh - sb_h) / 2
    # Shared traits stack vertically between A and B.
    shared_total = sum(
        _estimated_node_height(c, mind_map) + V_PAD for c in shared
    )
    cur_y = rh / 2 - shared_total / 2
    for c in shared:
        cw = _estimated_node_width(c, mind_map)
        ch = _estimated_node_height(c, mind_map)
        c.x = column_x + (280 - cw) / 2
        c.y = cur_y
        cur_y += ch + V_PAD
    # Each subject's subtree radiates outward (A left, B right).
    _walk_h_subtree(root, mind_map, -1)
    _walk_h_subtree(subject_b, mind_map, +1)


def apply_multi_flow(mind_map: "MindMap") -> None:
    """Cause-and-effect layout. Root sits in the middle; the first
    half of its children are 'causes' radiating left, the second
    half are 'effects' radiating right. Subtrees keep growing in
    the direction their root child sits on."""
    root = mind_map.root
    root.x = 0
    root.y = 0
    if root.collapsed or not root.children:
        return
    rh = _estimated_node_height(root, mind_map)
    rw = _estimated_node_width(root, mind_map)
    n = len(root.children)
    half = (n + 1) // 2
    causes = root.children[:half]
    effects = root.children[half:] if half < n else []
    # Lay causes (left).
    cause_total = sum(
        _walk_h_subtree_size(c, mind_map) for c in causes
    ) or V_PAD
    cur_y = rh / 2 - cause_total / 2
    for c in causes:
        cw = _estimated_node_width(c, mind_map)
        ch = _estimated_node_height(c, mind_map)
        sub_h = _walk_h_subtree_size(c, mind_map)
        c.x = -200 - cw
        c.y = cur_y + sub_h / 2 - ch / 2
        _walk_h_subtree(c, mind_map, -1)
        cur_y += sub_h
    # Lay effects (right).
    effect_total = sum(
        _walk_h_subtree_size(c, mind_map) for c in effects
    ) or V_PAD
    cur_y = rh / 2 - effect_total / 2
    for c in effects:
        ch = _estimated_node_height(c, mind_map)
        sub_h = _walk_h_subtree_size(c, mind_map)
        c.x = rw + 200
        c.y = cur_y + sub_h / 2 - ch / 2
        _walk_h_subtree(c, mind_map, +1)
        cur_y += sub_h


def apply_timeline(mind_map: "MindMap") -> None:
    """Sequential events along a horizontal line. Root sits at the
    far left; every direct child is placed to its right in document
    order, evenly spaced. Grandchildren (and deeper) drop BELOW each
    event with a small vertical step so the timeline's spine stays
    visually distinct."""
    root = mind_map.root
    root.x = 0
    root.y = 0
    if root.collapsed or not root.children:
        return
    rh = _estimated_node_height(root, mind_map)
    rw = _estimated_node_width(root, mind_map)
    cur_x = rw + 180
    spine_y = rh / 2
    for c in root.children:
        cw = _estimated_node_width(c, mind_map)
        ch = _estimated_node_height(c, mind_map)
        c.x = cur_x
        c.y = spine_y - ch / 2
        # Drop a child's own descendants vertically below it so the
        # timeline spine stays horizontal.
        _stack_down(c, mind_map)
        cur_x += cw + 80


def _stack_down(node: "Node", mind_map: "MindMap") -> None:
    """Recursively place `node`'s subtree directly underneath it,
    stepping down vertically. Used by timeline + flow layouts."""
    if node.collapsed or not node.children:
        return
    nh = _estimated_node_height(node, mind_map)
    nw = _estimated_node_width(node, mind_map)
    parent_cx = node.x + nw / 2
    cur_y = node.y + nh + 60
    for c in node.children:
        cw = _estimated_node_width(c, mind_map)
        c.x = parent_cx - cw / 2
        c.y = cur_y
        ch = _estimated_node_height(c, mind_map)
        _stack_down(c, mind_map)
        cur_y += ch + 60


def apply_brace_map(mind_map: "MindMap") -> None:
    """Whole-to-parts decomposition. Like a tidy-right tree but with
    LARGER horizontal gaps so each layer reads as a separate brace.
    The same `apply_tidy_right` machinery handles position math; the
    wider gap is the only meaningful change for the activated form."""
    # Tidy-right gives us the right tree shape — just nudge children
    # further out so a 'brace' character could fit between layers if
    # the user wanted to draw one separately later.
    apply_tidy_right(mind_map)
    # Bias children outward by an extra 60px per depth level.
    def _spread(node: "Node", depth: int) -> None:
        if node.collapsed:
            return
        for c in node.children:
            c.x += 60 * depth
            _spread(c, depth + 1)
    _spread(mind_map.root, 1)


def apply_flow_map(mind_map: "MindMap") -> None:
    """Sequential left-to-right chain. Same arrangement as Timeline —
    root → children → grandchildren each indexed step further right —
    so workflow / process diagrams can read as a single arrow path.
    Branches (multi-child nodes) fan out vertically at each step."""
    root = mind_map.root
    root.x = 0
    root.y = 0
    if root.collapsed or not root.children:
        return
    _flow_walk(root, mind_map, depth=1)


def _flow_walk(node: "Node", mind_map: "MindMap", depth: int) -> None:
    if node.collapsed or not node.children:
        return
    nw = _estimated_node_width(node, mind_map)
    nh = _estimated_node_height(node, mind_map)
    base_x = node.x + nw + 160
    n = len(node.children)
    # Vertical span the children + their subtrees will occupy.
    total_h = sum(
        _walk_h_subtree_size(c, mind_map) for c in node.children
    )
    cur_y = node.y + nh / 2 - total_h / 2
    for c in node.children:
        cw = _estimated_node_width(c, mind_map)
        ch = _estimated_node_height(c, mind_map)
        sub_h = _walk_h_subtree_size(c, mind_map)
        c.x = base_x
        c.y = cur_y + sub_h / 2 - ch / 2
        _flow_walk(c, mind_map, depth + 1)
        cur_y += sub_h


def apply_dialogue_map(mind_map: "MindMap") -> None:
    """Alternating-speaker layout — children placed alternately left
    and right of root with each successive child stepping DOWN, so
    the result reads like a transcript. Subtrees of each child
    follow the same alternation."""
    root = mind_map.root
    root.x = 0
    root.y = 0
    if root.collapsed or not root.children:
        return
    rw = _estimated_node_width(root, mind_map)
    rh = _estimated_node_height(root, mind_map)
    cur_y = root.y + rh + 80
    for i, c in enumerate(root.children):
        cw = _estimated_node_width(c, mind_map)
        ch = _estimated_node_height(c, mind_map)
        if i % 2 == 0:
            c.x = root.x - cw - 80
        else:
            c.x = root.x + rw + 80
        c.y = cur_y
        # Lay descendants downward, alternating left/right per depth.
        _dialogue_walk(c, mind_map, direction=-1 if i % 2 == 0 else 1)
        cur_y += ch + 80


def _dialogue_walk(node: "Node", mind_map: "MindMap", direction: int) -> None:
    if node.collapsed or not node.children:
        return
    nw = _estimated_node_width(node, mind_map)
    nh = _estimated_node_height(node, mind_map)
    cur_y = node.y + nh + 60
    for i, c in enumerate(node.children):
        cw = _estimated_node_width(c, mind_map)
        ch = _estimated_node_height(c, mind_map)
        dir_now = direction if i % 2 == 0 else -direction
        if dir_now < 0:
            c.x = node.x - cw - 60
        else:
            c.x = node.x + nw + 60
        c.y = cur_y
        _dialogue_walk(c, mind_map, dir_now)
        cur_y += ch + 60


LAYOUT_STYLES = {
    "tidy_branched": apply_tidy_branched,
    "tidy_right": apply_tidy_right,
    "tidy_left": apply_tidy_left,
    "tidy_down": apply_tidy_down,
    "tidy_up": apply_tidy_up,
    "bubble": apply_bubble,
    "double_bubble": apply_double_bubble,
    "multi_flow": apply_multi_flow,
    "timeline": apply_timeline,
    "brace": apply_brace_map,
    "flow": apply_flow_map,
    "dialogue": apply_dialogue_map,
}

LAYOUT_STYLE_LABELS = {
    "tidy_branched": "Tidy (Left & Right)",
    "tidy_right": "Tidy Right",
    "tidy_left": "Tidy Left",
    "tidy_down": "Tidy Down",
    "tidy_up": "Tidy Up",
    "bubble": "Bubble Map",
    "double_bubble": "Double Bubble",
    "multi_flow": "Multi-Flow",
    "timeline": "Timeline",
    "brace": "Brace Map",
    "flow": "Flow Map",
    "dialogue": "Dialogue Map",
}

# Now empty — every style is active. Kept as a name so any existing
# import sites stay valid.
DEFERRED_STYLES: dict[str, str] = {}


def apply_layout(mind_map: MindMap) -> None:
    """Apply the layout algorithm named by `mind_map.layout_style`.

    Collapsed nodes are treated as leaves: their hidden descendants don't
    contribute to subtree sizing, so visible siblings pack tightly.
    Image bands (per `node_image_mode` and per-node hide flags) inflate
    each node's leaf size so siblings get clearance.
    """
    # Sync the process-wide spacing globals (H_STEP / V_STEP / V_LEAF …)
    # to THIS map's minimalist flag before laying out. Those globals are
    # shared across every open map, and `set_minimalist_layout` is only
    # pushed by external callers on toggle / load — so with two maps
    # open at different settings (or a secondary-map window), the last
    # toggle could leave the globals scaled for the wrong map and lay
    # THIS one out with the other's spacing. Making apply_layout
    # authoritative from the map's own flag removes that cross-map
    # coupling; it's idempotent and only ~10 int ops, so cheap to redo
    # each call.
    set_minimalist_layout(bool(getattr(mind_map, "minimalist_layout", False)))
    style = str(getattr(mind_map, "layout_style", "") or "")
    # In follow-like modes the "Tidy (Left & Right)" split is confusing:
    # you're focused on ONE node, but its descendants fold left OR right
    # depending on which HALF of the whole map its branch sits in — so
    # navigating between branches flips the fold direction ("the child
    # nodes fold the wrong way"). Lay the followed view out in a single
    # consistent right-flowing direction instead. Only affects the
    # transient follow view; `layout_style` itself is untouched, so
    # Standard mode still shows the balanced left+right map.
    if style == "tidy_branched" and getattr(
        mind_map, "display_mode", ""
    ) in ("follow", "follow_plus", "recall", "recall_seq"):
        style = "tidy_right"
    fn = LAYOUT_STYLES.get(style)
    if fn is None:
        fn = LAYOUT_STYLES["tidy_branched"]
    # Per-call memoization scope for `_node_layout_size`. See docstring
    # note above — big perf win on large maps.
    mind_map._layout_size_cache = {}
    # Alias index used by topic-bullet sizing — rebuilt each call since
    # the tree (and its aliases) can change between layouts.
    mind_map._alias_index = None
    try:
        fn(mind_map)
        # Minimalist post-pass — rewrites every visible leaf into an
        # aligned outer column and re-centres ancestors on their
        # descendants so the "deepest visible nodes" cluster tightly
        # regardless of what the base layout algorithm produced.
        if bool(getattr(mind_map, "minimalist_layout", False)):
            try:
                _minimalist_leaf_align_pass(mind_map)
            except Exception:
                pass
    finally:
        mind_map._layout_size_cache = None


def _visible_node_extent(
    mind_map: MindMap, visible_ids: "set[str] | None"
) -> "tuple[float, float]":
    """Largest (width, height) among the currently-visible nodes,
    image-aware. The minimalist pass uses this to floor its per-layer
    column step so compact spacing never lets adjacent depth columns
    overlap. `_node_layout_size` is memoized for the apply_layout call,
    so this is a cheap dict-lookup walk."""
    max_w = max_h = 0.0
    if visible_ids is None:
        nodes = mind_map.all_nodes()
    else:
        nodes = (mind_map.find(i) for i in visible_ids)
    for n in nodes:
        if n is None:
            continue
        w, h = _node_layout_size(n, mind_map)
        if w > max_w:
            max_w = w
        if h > max_h:
            max_h = h
    return max_w, max_h


def _minimalist_leaf_align_pass(
    mind_map: MindMap,
    visible_ids: "set[str] | None" = None,
    view_root_id: "str | None" = None,
) -> None:
    """Post-processing pass invoked when `minimalist_layout` is on.

    Places every VISIBLE leaf (collapsed = leaf; hidden descendants
    are ignored) at the same "outer" coordinate — for horizontal
    layouts that's the same X, for vertical layouts the same Y.
    Ancestors then sit at their depth's column, aligned to the
    centre-of-mass of their visible descendants' outer coordinate.
    This produces the "one path back to root, leaves stacked" shape
    the user asked for.

    Detects orientation from the base layout style; branched styles
    (leaves on both sides of the root) run the pass once per side."""
    # `root` is the node the pass LAYS OUT AROUND — not necessarily
    # the map's real root. On subtree views (focus mode / list-map
    # clones / follow mode with a deep target), the caller passes
    # the topmost visible node here so leaves get stacked around it.
    # Falls back to the visible-set's topmost node if the caller
    # didn't pass one; falls back to mind_map.root if we have no
    # visible-set at all.
    root = None
    if view_root_id is not None:
        root = mind_map.find(view_root_id)
    if root is None and visible_ids is not None:
        # Pick the visible node whose parent is either not visible or
        # doesn't exist — that's the topmost visible node in the tree.
        for cand in mind_map.all_nodes():
            if cand.id not in visible_ids:
                continue
            parent = mind_map.parent_of(cand.id)
            if parent is None or parent.id not in visible_ids:
                root = cand
                break
    if root is None:
        root = mind_map.root

    style = str(getattr(mind_map, "layout_style", "") or "")
    # Column (layer) step: how far apart each depth's X (horizontal
    # layouts) or Y (vertical layouts) column sits. The minimalist-
    # scaled H_STEP / V_STEP are already ~55% of the base 260 / 140 —
    # that IS the compact layer spacing this mode promises, so use them
    # directly. (The previous `* 2` doubling pushed layers to ~286 px,
    # ~10% WIDER than a normal map, which defeated the whole point.)
    # Floor to the widest / tallest visible node, image-aware, so
    # adjacent depth columns still can't overlap — image nodes need the
    # clearance even when compact, so the step relaxes past 55% only as
    # far as the actual content forces it. The old row-step locals were
    # dead (leaf stacking now derives its own image-aware advances).
    #
    # The horizontal gap here used to be a separate hardcoded 24px,
    # completely blind to `mind_map.horizontal_line_length` (Display
    # Settings → Map & Layout → "Horizontal line length") — which
    # `_layout_h_children` reads for the normal, non-minimalist
    # layout. That disconnect meant dragging that control did nothing
    # while Minimalist was on, AND, since this pass floors on
    # node-width + gap regardless of the user's chosen value, a small
    # chosen gap could make the NORMAL layout more compact than
    # Minimalist's own fixed floor — i.e. Minimalist ending up WIDER
    # than normal, the opposite of what it promises. Reading the same
    # field here keeps both paths honoring one user setting.
    _h_gap = float(
        getattr(mind_map, "horizontal_line_length", _H_GAP) or _H_GAP
    )
    _v_col_gap = 24  # vertical layouts only — "Horizontal line length"
                      # is horizontal-only, per its own field comment.
    _max_w, _max_h = _visible_node_extent(mind_map, visible_ids)
    col_step_h = max(H_STEP, _max_w + _h_gap)
    col_step_v = max(V_STEP, _max_h + _v_col_gap)

    def side_leaves(children: list, direction_x: int, direction_y: int) -> None:
        """Layout a set of children (from root) that all flow in the
        same direction. `direction_x` is +1 for right-flowing (leaves
        further right than parents), -1 for left. If `direction_y`
        is non-zero we're in a vertical layout instead.

        Coordinates:
          horizontal → x by depth, y for the leaf-stack index
          vertical   → y by depth, x for the leaf-stack index"""
        if not children:
            return
        # DFS to gather VISIBLE leaves in visit order + record depths.
        # When `visible_ids` is supplied, we only consider nodes in it
        # — this is critical on large maps where the model has
        # hundreds of nodes but display_mode / collapse only surfaces
        # a handful. Without this filter, hidden nodes get treated as
        # leaves and inflate the vertical column, pushing the few
        # visible leaves hundreds of slots apart.
        leaves: list = []
        depth_by_id: dict = {}

        def visible(n) -> bool:
            if visible_ids is None:
                return True
            return n.id in visible_ids

        def walk(n, depth: int) -> None:
            if not visible(n):
                return
            depth_by_id[n.id] = depth
            kids = [
                k for k in (n.children if not n.collapsed else [])
                if visible(k)
            ]
            if not kids:
                leaves.append(n)
                return
            for k in kids:
                walk(k, depth + 1)

        for c in children:
            walk(c, 1)
        if not leaves:
            return
        max_depth = max(depth_by_id.values())

        # Each leaf sits at its OWN depth's column (X = depth * step).
        # Vertical (or horizontal for a v-layout) spacing between
        # adjacent leaves is capped at ~0.5 * min-neighbor-size — i.e.
        # bodies just clear each other by a small margin. This gives
        # the "leaves nearly touching" look the user asked for.
        #
        # Formula: gap between adjacent leaf CENTERS =
        #     max(h1, h2) / 2 + min(h1, h2) / 2 * (1 + margin_factor)
        # ≈ (h1 + h2) / 2 * (1 + margin) rounded to whole pixels.
        # `margin_factor` = 0.10 leaves ~10% breathing room and no
        # overlap even for wildly-different-sized siblings.
        # Compact leaf stacking, image-aware. Text-only leaves keep the
        # tight base step (110 px vertical / 160 px horizontal), so
        # non-image minimalist maps lay out exactly as before. But an
        # image or note-preview band inflates a leaf by _IMG_H+_IMG_PAD
        # (146 px each, up to two bands): a FIXED step would stack those
        # bodies right on top of each other, breaking minimalist's
        # stated "no overlaps" rule — there is no paint-time de-overlap,
        # so whatever the layout writes is what the user sees. Instead
        # each leaf advances by whichever is larger: the base step, or
        # its OWN estimated extent plus a small gap. node.x/node.y are
        # top-left, so advancing by the current leaf's full height (or
        # width, for vertical layouts) guarantees the next leaf clears
        # it. `_estimated_node_height/width` are image-aware and memoized
        # for this apply_layout pass, so the extra calls are cheap.
        BASE_STEP_H = 110   # vertical stack   (horizontal layouts)
        BASE_STEP_V = 160   # horizontal stack (vertical layouts)
        LEAF_GAP = 12       # breathing room so adjacent bodies don't kiss
        n = len(leaves)
        if direction_y == 0:
            advances = [
                max(BASE_STEP_H,
                    _estimated_node_height(leaf, mind_map) + LEAF_GAP)
                for leaf in leaves
            ]
            # Center the stack on root.y. The span is the distance from
            # the first leaf's top-left to the last's (advances[:-1]);
            # the trailing leaf's own advance is slack we don't count.
            y = root.y - sum(advances[:-1]) / 2.0
            for i, leaf in enumerate(leaves):
                d = depth_by_id[leaf.id]
                leaf.x = root.x + direction_x * (d * col_step_h)
                leaf.y = y
                y += advances[i]
        else:
            advances = [
                max(BASE_STEP_V,
                    _estimated_node_width(leaf, mind_map) + LEAF_GAP)
                for leaf in leaves
            ]
            x = root.x - sum(advances[:-1]) / 2.0
            for i, leaf in enumerate(leaves):
                d = depth_by_id[leaf.id]
                leaf.y = root.y + direction_y * (d * col_step_v)
                leaf.x = x
                x += advances[i]

        # Position ancestors post-order: X (or Y) by depth, other axis
        # = mean of VISIBLE children. Skips nodes that weren't in the
        # visible set walked above so we don't accidentally reposition
        # invisible-but-still-in-model nodes (which would ripple back
        # up through their visible ancestors).
        def repose(n) -> None:
            if not visible(n):
                return
            kids = [
                k for k in (n.children if not n.collapsed else [])
                if visible(k)
            ]
            if not kids:
                return
            for k in kids:
                repose(k)
            if n.id not in depth_by_id:
                return
            d = depth_by_id[n.id]
            # Align this ancestor's VISUAL CENTER to the mean of its
            # visible children's visual centers, then convert back to a
            # top-left coord (node.x/node.y are top-left). Averaging the
            # children's top-lefts alone left the parent off-center
            # whenever siblings differed in size — common now that image
            # leaves are much taller than text ones — so the parent's
            # connector met its children off the body centre.
            if direction_y == 0:
                n.x = root.x + direction_x * (d * col_step_h)
                mean_center_y = sum(
                    k.y + _estimated_node_height(k, mind_map) / 2.0
                    for k in kids
                ) / len(kids)
                n.y = mean_center_y - _estimated_node_height(n, mind_map) / 2.0
            else:
                n.y = root.y + direction_y * (d * col_step_v)
                mean_center_x = sum(
                    k.x + _estimated_node_width(k, mind_map) / 2.0
                    for k in kids
                ) / len(kids)
                n.x = mean_center_x - _estimated_node_width(n, mind_map) / 2.0

        for c in children:
            repose(c)

    def _root_children_visible() -> list:
        if visible_ids is None:
            return list(root.children)
        return [c for c in root.children if c.id in visible_ids]

    if style in ("tidy_right", "tidy_left", "tidy_branched", ""):
        # Horizontal layouts.
        if style == "tidy_right":
            side_leaves(_root_children_visible(), direction_x=+1, direction_y=0)
        elif style == "tidy_left":
            side_leaves(_root_children_visible(), direction_x=-1, direction_y=0)
        else:
            # Branched — separate by whichever side the base layout
            # left the child on.
            all_children = _root_children_visible()
            right = [c for c in all_children if c.x >= root.x]
            left = [c for c in all_children if c.x < root.x]
            side_leaves(right, direction_x=+1, direction_y=0)
            side_leaves(left, direction_x=-1, direction_y=0)
    elif style in ("tidy_down", "tidy_up"):
        d_y = +1 if style == "tidy_down" else -1
        side_leaves(_root_children_visible(), direction_x=0, direction_y=d_y)
    # Other layouts (bubble, brace, flow, timeline, etc.) have their
    # own geometry — leaf alignment doesn't apply cleanly, so leave
    # them alone.


apply_tidy_layout = apply_layout
