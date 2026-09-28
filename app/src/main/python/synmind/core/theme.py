"""Themes for mind maps. Pure data; no Qt dependency."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Theme:
    name: str
    display_name: str
    background: str
    root_fill: str
    root_stroke: str
    root_text: str
    node_fill: str
    node_stroke: str
    node_text: str
    selected_fill: str
    selected_stroke: str
    selected_text: str
    edge_color: str
    font_family: str = "Segoe UI"
    font_size: int = 11


THEMES: dict[str, Theme] = {
    "dark": Theme(
        name="dark",
        display_name="Standard",
        background="#1e1e22",
        root_fill="#4a4a58",
        root_stroke="#7a7a8a",
        root_text="#ffffff",
        node_fill="#3a3a44",
        node_stroke="#54545e",
        node_text="#e8e8ec",
        selected_fill="#2d7df6",
        selected_stroke="#ffffff",
        selected_text="#ffffff",
        edge_color="#6c6c78",
    ),
    "light": Theme(
        name="light",
        display_name="Light",
        background="#fafafa",
        root_fill="#3a6df0",
        root_stroke="#2c54c2",
        root_text="#ffffff",
        node_fill="#ffffff",
        node_stroke="#d1d1d6",
        node_text="#1c1c1e",
        selected_fill="#2d7df6",
        selected_stroke="#ffffff",
        selected_text="#ffffff",
        edge_color="#8a8a92",
    ),
    "forest": Theme(
        name="forest",
        display_name="Forest",
        background="#1c2a23",
        root_fill="#3a7a52",
        root_stroke="#5fa97a",
        root_text="#ffffff",
        node_fill="#2c4036",
        node_stroke="#456c5b",
        node_text="#d8e8df",
        selected_fill="#62c08a",
        selected_stroke="#ffffff",
        selected_text="#0c1a13",
        edge_color="#5a7a6c",
    ),
    "sunset": Theme(
        name="sunset",
        display_name="Sunset",
        background="#2a1c2a",
        root_fill="#c75a8f",
        root_stroke="#e87aa9",
        root_text="#ffffff",
        node_fill="#3a2436",
        node_stroke="#62445c",
        node_text="#f0d8e5",
        selected_fill="#ff9966",
        selected_stroke="#ffffff",
        selected_text="#2a1c2a",
        edge_color="#8a6a7c",
    ),
    "ocean": Theme(
        name="ocean",
        display_name="Ocean",
        background="#0d1b2a",
        root_fill="#1b4965",
        root_stroke="#62b6cb",
        root_text="#ffffff",
        node_fill="#1b263b",
        node_stroke="#415a77",
        node_text="#e0fbfc",
        selected_fill="#00b4d8",
        selected_stroke="#ffffff",
        selected_text="#03045e",
        edge_color="#5e8fa3",
    ),
    "mocha": Theme(
        name="mocha",
        display_name="Mocha",
        background="#2a1f1a",
        root_fill="#5c4033",
        root_stroke="#c19a6b",
        root_text="#fdf3e3",
        node_fill="#3d2f25",
        node_stroke="#6b4e3a",
        node_text="#f4e3cf",
        selected_fill="#e6a55e",
        selected_stroke="#fdf3e3",
        selected_text="#2a1f1a",
        edge_color="#7a5d44",
    ),
    "neon": Theme(
        name="neon",
        display_name="Neon",
        background="#0a0a14",
        root_fill="#1f0a2e",
        root_stroke="#d946ef",
        root_text="#e0f7fa",
        node_fill="#14141f",
        node_stroke="#3f1d52",
        node_text="#06d6a0",
        selected_fill="#d946ef",
        selected_stroke="#06d6a0",
        selected_text="#0a0a14",
        edge_color="#4a2e6c",
    ),
    "solarized": Theme(
        name="solarized",
        display_name="Solarized",
        background="#fdf6e3",
        root_fill="#268bd2",
        root_stroke="#073642",
        root_text="#fdf6e3",
        node_fill="#eee8d5",
        node_stroke="#93a1a1",
        node_text="#586e75",
        selected_fill="#cb4b16",
        selected_stroke="#fdf6e3",
        selected_text="#fdf6e3",
        edge_color="#93a1a1",
    ),
    "slate": Theme(
        name="slate",
        display_name="Slate",
        background="#1e293b",
        root_fill="#475569",
        root_stroke="#94a3b8",
        root_text="#f1f5f9",
        node_fill="#334155",
        node_stroke="#64748b",
        node_text="#f1f5f9",
        selected_fill="#38bdf8",
        selected_stroke="#f1f5f9",
        selected_text="#0c4a6e",
        edge_color="#64748b",
    ),
    "old_fashion": Theme(
        name="old_fashion",
        display_name="Old Fashion",
        background="#f1e7c8",
        root_fill="#8b5a2b",
        root_stroke="#5e3a1a",
        root_text="#fdf6e3",
        node_fill="#e6d5a8",
        node_stroke="#a0794a",
        node_text="#3b2a14",
        selected_fill="#c08e3a",
        selected_stroke="#3b2a14",
        selected_text="#fdf6e3",
        edge_color="#9c7b4a",
        font_family="Georgia",
    ),
    "futuristic": Theme(
        name="futuristic",
        display_name="Futuristic",
        background="#04060c",
        root_fill="#0b1e3a",
        root_stroke="#00e5ff",
        root_text="#7df9ff",
        node_fill="#0a1626",
        node_stroke="#1d4d80",
        node_text="#a7f3ff",
        selected_fill="#00e5ff",
        selected_stroke="#ffffff",
        selected_text="#03101c",
        edge_color="#1d4d80",
        font_family="Consolas",
    ),
    "phycodelic": Theme(
        name="phycodelic",
        display_name="Phycodelic",
        background="#1a002b",
        root_fill="#ff2d95",
        root_stroke="#ffe600",
        root_text="#00ffea",
        node_fill="#3d0066",
        node_stroke="#ff2d95",
        node_text="#ffe600",
        selected_fill="#00ffea",
        selected_stroke="#ff2d95",
        selected_text="#1a002b",
        edge_color="#ff2d95",
    ),
    "bluish": Theme(
        name="bluish",
        display_name="Bluish",
        background="#0f1d3a",
        root_fill="#1d3a78",
        root_stroke="#3b82f6",
        root_text="#dbeafe",
        node_fill="#172a55",
        node_stroke="#2c5fc1",
        node_text="#dbeafe",
        selected_fill="#3b82f6",
        selected_stroke="#ffffff",
        selected_text="#0f1d3a",
        edge_color="#476cb0",
    ),
    "light_grey": Theme(
        name="light_grey",
        display_name="Light Grey",
        background="#e5e7eb",
        root_fill="#4b5563",
        root_stroke="#1f2937",
        root_text="#ffffff",
        node_fill="#f9fafb",
        node_stroke="#9ca3af",
        node_text="#111827",
        selected_fill="#3b82f6",
        selected_stroke="#ffffff",
        selected_text="#ffffff",
        edge_color="#6b7280",
    ),
    "banana": Theme(
        name="banana",
        display_name="Banana",
        background="#fff7c2",
        root_fill="#facc15",
        root_stroke="#a16207",
        root_text="#3f2f02",
        node_fill="#fffae0",
        node_stroke="#ca8a04",
        node_text="#3f2f02",
        selected_fill="#eab308",
        selected_stroke="#422006",
        selected_text="#3f2f02",
        edge_color="#a16207",
    ),
    "crazy": Theme(
        name="crazy",
        display_name="Crazy",
        background="#10002b",
        root_fill="#ff006e",
        root_stroke="#ffbe0b",
        root_text="#ffffff",
        node_fill="#240046",
        node_stroke="#8338ec",
        node_text="#ffbe0b",
        selected_fill="#fb5607",
        selected_stroke="#ffbe0b",
        selected_text="#10002b",
        edge_color="#3a86ff",
    ),
    "classy": Theme(
        name="classy",
        display_name="Classy",
        background="#0a0a0a",
        root_fill="#1a1a1a",
        root_stroke="#d4af37",
        root_text="#f5e6b3",
        node_fill="#141414",
        node_stroke="#7a6532",
        node_text="#f5e6b3",
        selected_fill="#d4af37",
        selected_stroke="#f5e6b3",
        selected_text="#0a0a0a",
        edge_color="#7a6532",
        font_family="Georgia",
    ),
    "simple": Theme(
        name="simple",
        display_name="Simple",
        background="#ffffff",
        root_fill="#111111",
        root_stroke="#000000",
        root_text="#ffffff",
        node_fill="#ffffff",
        node_stroke="#cccccc",
        node_text="#111111",
        selected_fill="#000000",
        selected_stroke="#000000",
        selected_text="#ffffff",
        edge_color="#cccccc",
    ),
    "metal": Theme(
        name="metal",
        display_name="Metal",
        background="#2b2f33",
        root_fill="#4f555c",
        root_stroke="#c5cbd2",
        root_text="#f4f6f8",
        node_fill="#3a3f44",
        node_stroke="#7c8389",
        node_text="#e6e9ec",
        selected_fill="#a3aab1",
        selected_stroke="#1a1d20",
        selected_text="#1a1d20",
        edge_color="#7c8389",
    ),
}


def get_theme(name: str) -> Theme:
    return THEMES.get(name, THEMES["dark"])


# How far the note editor's text area is lifted off the canvas background.
# One constant because four places need the same answer — the editor's
# stylesheet, its contrast fixer, the background-colour picker's starting
# value, and the HTML export, which now draws each note on the background
# it was written on. They drifted apart once already.
NOTE_EDITOR_LIGHTEN = 0.18


def note_editor_colors(name: str) -> tuple[str, str]:
    """(background, ink) of the note editor's text area for a theme.

    The pair matters more than either half: the editor rewrites text
    colours that don't read against this background, so anything showing
    a note elsewhere has to know both to reproduce what the writer saw.
    """
    theme = get_theme(name)
    return lighten_hex(theme.background, NOTE_EDITOR_LIGHTEN), theme.node_text


def lighten_hex(color: str, amount: float = 0.15) -> str:
    """Shift a hex color toward white by `amount` (0..1). For already-light
    inputs (luminance > 200) the shift inverts and goes toward black by
    the same amount — purely-light themes have nowhere to go "lighter"
    visually, so a slight darken keeps the derived color distinct from
    the source. Used to build right-panel backgrounds that read as
    elevated siblings of the canvas background.

    Falls back to the input string on malformed hex."""
    s = color.lstrip("#")
    if len(s) != 6:
        return color
    try:
        r = int(s[0:2], 16)
        g = int(s[2:4], 16)
        b = int(s[4:6], 16)
    except ValueError:
        return color
    amount = max(0.0, min(1.0, amount))
    # Rec. 601 luma — good enough heuristic for "is this color bright?"
    luma = 0.299 * r + 0.587 * g + 0.114 * b
    if luma > 200:
        # Bright background: nudge toward black so the derived color is
        # actually distinguishable from the source.
        r = int(r - r * amount)
        g = int(g - g * amount)
        b = int(b - b * amount)
    else:
        r = int(r + (255 - r) * amount)
        g = int(g + (255 - g) * amount)
        b = int(b + (255 - b) * amount)
    return f"#{r:02x}{g:02x}{b:02x}"
