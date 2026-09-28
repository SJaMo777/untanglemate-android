"""Map-wide color resolution + contrast math. Pure data; no Qt dependency.

Two jobs live here:

1. **Resolution order.** `effective_fill` / `effective_text` are the single
   source of truth for "what color does this node actually paint?". The
   canvas painter, the inline editor's readable-ink fallback, and the
   optimization pass all call these — if they each re-derived the order,
   the optimizer would end up scoring contrast against a background the
   painter never draws.
2. **Optimization.** `plan_text_color_optimization` finds text that has
   become unreadable (typically right after a theme or map-wide color
   change) and proposes the minimum set of writes that fixes it.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from synmind.core.model import MindMap, Node
from synmind.core.theme import Theme

# The same pair the inline editor has always used for its own contrast
# fallback. Sharing it means a node the optimizer touched and a node
# being edited never disagree about what "readable" looks like.
DARK_INK = "#12151c"
LIGHT_INK = "#f6f8fc"

# WCAG AA for normal-size body text. Node titles are often bold/large, so
# this is a slightly conservative floor rather than a strict standard.
DEFAULT_MIN_CONTRAST = 4.5

MIN_CONTRAST_FLOOR = 1.0
MIN_CONTRAST_CEILING = 21.0


def parse_hex(color: str | None) -> tuple[int, int, int] | None:
    """Accepts `#rgb`, `#rrggbb`, and Qt's `#aarrggbb` (alpha stripped).
    Returns None for anything unparseable so callers can fall through to
    a theme default instead of raising on a hand-edited .smmap."""
    if not color:
        return None
    s = str(color).strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    elif len(s) == 8:
        s = s[2:]
    if len(s) != 6:
        return None
    try:
        return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    except ValueError:
        return None


def _linearize(channel: int) -> float:
    c = channel / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(color: str | None) -> float | None:
    rgb = parse_hex(color)
    if rgb is None:
        return None
    r, g, b = (_linearize(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a: str | None, b: str | None) -> float | None:
    """WCAG contrast ratio, 1.0 (identical) .. 21.0 (black on white).
    None when either color is unparseable."""
    la = relative_luminance(a)
    lb = relative_luminance(b)
    if la is None or lb is None:
        return None
    hi, lo = (la, lb) if la >= lb else (lb, la)
    return (hi + 0.05) / (lo + 0.05)


def readable_ink(background: str | None) -> str:
    """Whichever of DARK_INK / LIGHT_INK contrasts more with `background`.
    Defaults to LIGHT_INK when the background can't be parsed, matching the
    app's dark-first themes."""
    dark = contrast_ratio(DARK_INK, background)
    light = contrast_ratio(LIGHT_INK, background)
    if dark is None or light is None:
        return LIGHT_INK
    return DARK_INK if dark >= light else LIGHT_INK


def clamp_min_contrast(value: float | None) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return DEFAULT_MIN_CONTRAST
    return max(MIN_CONTRAST_FLOOR, min(MIN_CONTRAST_CEILING, v))


# --- priority colouring -----------------------------------------------

# Fill per priority level, 1 (highest) to 5 (lowest). A heat ramp, so
# the ordering is legible without reading the number.
#
# Every one is dark enough that readable_ink() returns the LIGHT ink, so
# the text colour holds steady all the way down the scale. Text that
# flipped from white to black partway along would read as two different
# styles rather than one gradient.
#
# That constraint is why these are 700-weight rather than the more
# obvious 600s: at 600, levels 2, 3 and 4 are light enough that the dark
# ink wins and the ramp breaks in the middle. Worst contrast here is
# 4.63 against the light ink - above the 4.5 WCAG AA floor the rest of
# this module is written to. Re-check with contrast_ratio() before
# changing any of them.
PRIORITY_FILLS = {
    1: "#b91c1c",   # red     - highest
    2: "#c2410c",   # orange
    3: "#a16207",   # amber
    4: "#15803d",   # green
    5: "#475569",   # slate   - lowest
}


def shade(color: str | None, factor: float) -> str | None:
    """`color` scaled toward black (factor < 1) or white (factor > 1).

    Used to derive a frame from a fill rather than maintaining a second
    hand-picked palette that could drift out of step with the first.
    """
    rgb = parse_hex(color)
    if rgb is None:
        return None
    if factor >= 1.0:
        out = [int(round(c + (255 - c) * (factor - 1.0))) for c in rgb]
    else:
        out = [int(round(c * factor)) for c in rgb]
    return "#%02x%02x%02x" % tuple(max(0, min(255, c)) for c in out)


def priority_of(node) -> int | None:
    """The node's priority level as 1-5, or None."""
    try:
        lvl = int(getattr(node, "priority_level", None))
    except (TypeError, ValueError):
        return None
    return lvl if lvl in PRIORITY_FILLS else None


def priority_colors_on(mind_map) -> bool:
    return bool(getattr(mind_map, "priority_node_colors", False))


def priority_fill_for(node, mind_map) -> str | None:
    """The priority fill for `node`, or None when priority colouring is
    off, the node has no priority, or the node carries its OWN fill.

    A hand-set colour wins: an explicit choice should beat an automatic
    rule, and otherwise there would be no way to make one node stand out
    while the scheme is on.

    Nothing here is stored on the node. Turning the setting off restores
    whatever the user had, because their colours were never overwritten.
    """
    if node is None or not priority_colors_on(mind_map):
        return None
    if getattr(node, "fill_color", None):
        return None
    lvl = priority_of(node)
    return PRIORITY_FILLS.get(lvl) if lvl else None


def priority_indicator_color(node) -> str | None:
    """The priority color to show for `node` in an export, when that
    export's own "Show Priorities" option is on.

    Deliberately takes no `mind_map` and does not consult
    `priority_node_colors` — unlike `priority_fill_for`, this is a
    per-export choice (`GeneralExportOpts.show_priorities`, see
    canvas.py), independent of whether the CANVAS is showing priority
    colors at all. A map can export priority colors without ever
    turning the on-screen scheme on, and vice versa.

    A hand-set fill still wins, same reasoning as `priority_fill_for`:
    an explicit color is a stronger statement than an automatic rule,
    and exporting a color the map itself doesn't show would be
    surprising.
    """
    if getattr(node, "fill_color", None):
        return None
    lvl = priority_of(node)
    return PRIORITY_FILLS.get(lvl) if lvl else None


def priority_border_for(node, mind_map) -> str | None:
    """The frame that goes with the priority fill - the same hue, darker,
    so the node reads as one object rather than two."""
    if getattr(node, "border_color", None):
        return None
    fill = priority_fill_for(node, mind_map)
    return shade(fill, 0.62) if fill else None


# --- resolution order -------------------------------------------------


def effective_fill(
    node: Node,
    mind_map: MindMap,
    theme: Theme,
    *,
    is_root: bool = False,
    is_selected: bool = False,
) -> str:
    """Per-node override > selection > map-wide > theme.

    The map-wide fill deliberately sits BELOW the selection fill: applying
    it to the selected node too would make selection invisible on every
    node at once. A per-node fill still wins while selected — that has
    always been the behavior, and it only ever affects a few nodes.
    """
    if node is not None and node.fill_color:
        return node.fill_color
    if is_selected:
        return theme.selected_fill
    # Priority colouring sits BELOW selection for the same reason the
    # map-wide fill does: colouring the selected node too would make
    # selection invisible on every prioritised node at once.
    pri = priority_fill_for(node, mind_map)
    if pri:
        return pri
    map_fill = getattr(mind_map, "map_node_fill_color", None)
    if map_fill:
        return map_fill
    return theme.root_fill if is_root else theme.node_fill


def effective_text(
    node: Node,
    mind_map: MindMap,
    theme: Theme,
    *,
    is_root: bool = False,
    is_selected: bool = False,
) -> str:
    """Selection > per-node override > map-wide > theme.

    Selection outranks the per-node color here (unlike fill) because
    readability against the selection fill matters more than honoring a
    foreground choice for the moment a node is selected.
    """
    if is_selected:
        return theme.selected_text
    if node is not None and node.text_color:
        return node.text_color
    # A COLOURED node picks its own ink.
    #
    # Both a hand-set fill and a priority fill are chosen for what they
    # signal, not for what text will sit on them, so the theme's default
    # ink lands on them at whatever contrast happens to result - which
    # is how dark-on-dark and white-on-yellow happen. Deciding the ink
    # from the fill makes the node readable by construction.
    #
    # Below node.text_color: an explicit choice is still honoured, even
    # an unreadable one. Above map-wide, because a per-node fill is the
    # more specific statement about THIS node.
    own_fill = getattr(node, "fill_color", None) if node is not None else None
    fill = own_fill or priority_fill_for(node, mind_map)
    if fill:
        return readable_ink(fill)
    map_text = getattr(mind_map, "map_node_text_color", None)
    if map_text:
        return map_text
    return theme.root_text if is_root else theme.node_text


# --- optimization -----------------------------------------------------


@dataclass
class ColorOptimization:
    """A proposed set of writes. Nothing is applied until the command runs.

    `node_changes` is [(node_id, old_text_color, new_text_color)] so the
    command can undo without re-deriving anything.
    """
    old_map_text_color: str | None = None
    new_map_text_color: str | None = None
    old_map_text_auto: bool = False
    new_map_text_auto: bool = False
    node_changes: list[tuple[str, str | None, str | None]] = field(
        default_factory=list
    )
    skipped_rich_text: int = 0
    min_ratio: float = DEFAULT_MIN_CONTRAST

    @property
    def map_text_changed(self) -> bool:
        return (
            self.new_map_text_color != self.old_map_text_color
            or self.new_map_text_auto != self.old_map_text_auto
        )

    @property
    def is_empty(self) -> bool:
        return not self.map_text_changed and not self.node_changes

    def summary(self) -> str:
        if self.is_empty:
            bits = ["Colors already readable — nothing to optimize"]
        else:
            bits = []
            if self.map_text_changed:
                bits.append(
                    f"map text → {self.new_map_text_color}"
                    if self.new_map_text_color
                    else "map text released to theme"
                )
            if self.node_changes:
                n = len(self.node_changes)
                bits.append(f"{n} node{'s' if n != 1 else ''} recolored")
        if self.skipped_rich_text:
            n = self.skipped_rich_text
            bits.append(f"{n} rich-text node{'s' if n != 1 else ''} skipped")
        return "; ".join(bits)


def plan_text_color_optimization(
    mind_map: MindMap,
    theme: Theme,
    *,
    min_ratio: float | None = None,
) -> ColorOptimization:
    """Find text that fails `min_ratio` against the fill behind it and
    propose the smallest set of writes that fixes it.

    Deliberately conservative, because this runs automatically after a
    theme change and must never feel like it ransacked the user's map:

    * Stage 1 fixes the shared case with ONE write — if the map-wide (or
      theme) text color fails against the map-wide fill, replace the
      map-wide text color. That covers every node inheriting defaults
      without stamping a per-node color onto thousands of nodes.
    * Stage 2 only touches nodes that already carry an explicit
      `fill_color` or `text_color`. A node inheriting both defaults is
      stage 1's business; if it still fails there, the theme itself is at
      fault and rewriting the whole map is the wrong remedy.
    * Text that already passes is left alone, even when the user picked
      an unusual color. Passing contrast means it was a choice, not a
      casualty of the style change.
    * Rich-text nodes (`text_html`) are skipped and counted: their color
      lives in per-span HTML, so writing `text_color` would change
      nothing on screen and silently desync the two.
    """
    ratio_floor = clamp_min_contrast(
        min_ratio
        if min_ratio is not None
        else getattr(mind_map, "color_contrast_min_ratio", DEFAULT_MIN_CONTRAST)
    )

    old_map_text = getattr(mind_map, "map_node_text_color", None)
    map_fill = getattr(mind_map, "map_node_fill_color", None)
    was_auto = bool(getattr(mind_map, "map_text_color_auto", False))

    plan = ColorOptimization(
        old_map_text_color=old_map_text,
        new_map_text_color=old_map_text,
        old_map_text_auto=was_auto,
        new_map_text_auto=was_auto,
        min_ratio=ratio_floor,
    )

    # Stage 1 — the map-wide pair.
    #
    # Recomputed from scratch every pass rather than patched incrementally.
    # `map_text_color_auto` marks a value THIS pass wrote, so a previous
    # auto-fix is ignored when deciding what the map would look like on its
    # own. That makes the stamp self-healing: switch to a theme that needs
    # no help and it's released back to the theme, instead of a one-off
    # correction outliving the palette that caused it.
    #
    # A theme whose own node_fill/node_text pairing fails IS fixed here —
    # inherited text is the common case, and refusing to touch it would
    # leave the map unreadable with no remedy. One map-level write handles
    # every uncustomized node; the min-contrast spin is the escape hatch
    # for palettes that are low-contrast by design.
    user_map_text = None if was_auto else old_map_text
    shared_fill = map_fill or theme.node_fill
    unassisted_text = user_map_text or theme.node_text
    shared_ratio = contrast_ratio(unassisted_text, shared_fill)
    if shared_ratio is None or shared_ratio < ratio_floor:
        plan.new_map_text_color = readable_ink(shared_fill)
        plan.new_map_text_auto = True
    else:
        # Passes unaided — drop any stamp we own, keep any the user chose.
        plan.new_map_text_color = user_map_text
        plan.new_map_text_auto = False

    effective_map_text = plan.new_map_text_color

    # Stage 2 — nodes with their own overrides, scored against the
    # post-stage-1 world so we don't "fix" something stage 1 just fixed.
    root_id = mind_map.root.id if mind_map.root is not None else None
    for node in mind_map.all_nodes():
        if node.text_html:
            plan.skipped_rich_text += 1
            continue
        if not node.fill_color and not node.text_color:
            continue

        is_root = node.id == root_id
        fill = node.fill_color or map_fill or (
            theme.root_fill if is_root else theme.node_fill
        )
        text = node.text_color or effective_map_text or (
            theme.root_text if is_root else theme.node_text
        )
        ratio = contrast_ratio(text, fill)
        if ratio is not None and ratio >= ratio_floor:
            continue

        new_text = readable_ink(fill)
        if new_text == node.text_color:
            continue
        plan.node_changes.append((node.id, node.text_color, new_text))

    return plan
