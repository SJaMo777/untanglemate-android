"""Importers for common mind map file formats.

`import_file(path)` dispatches by extension and returns a fresh `MindMap`.
Supported: .opml, .mm (FreeMind/FreePlane), .md/.markdown/.txt, .xmind.
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from synmind.core.model import MindMap, Node


class MindMapImportError(Exception):
    pass


SUPPORTED_EXTS = (
    ".opml", ".mm", ".md", ".markdown", ".txt", ".xmind", ".smmap")


def import_file(path: str | Path) -> MindMap:
    suffix = Path(path).suffix.lower()
    if suffix == ".smmap":
        # Native map — load through the document layer (handles both the
        # encrypted and plaintext forms). Callers that graft it under a node
        # should re-ID the tree first to avoid id collisions.
        from synmind.core.document import load as _load_smmap
        return _load_smmap(path)
    if suffix == ".opml":
        return _load_opml(path)
    if suffix == ".mm":
        return _load_freemind(path)
    if suffix in (".md", ".markdown", ".txt"):
        return _load_markdown(path)
    if suffix == ".xmind":
        return _load_xmind(path)
    raise MindMapImportError(
        f"No importer for '{suffix}'. Supported: {', '.join(SUPPORTED_EXTS)}"
    )


# --- OPML -----------------------------------------------------------------

def _load_opml(path: str | Path) -> MindMap:
    try:
        tree = ET.parse(path)
    except ET.ParseError as e:
        raise MindMapImportError(f"OPML parse failed: {e}")
    root = tree.getroot()
    body = root.find("body")
    if body is None:
        raise MindMapImportError("OPML file has no <body> element")
    outlines = body.findall("outline")
    if not outlines:
        raise MindMapImportError("OPML body has no <outline> elements")
    if len(outlines) == 1:
        return MindMap(root=_opml_to_node(outlines[0]))
    title_el = root.find("head/title")
    title = title_el.text if title_el is not None and title_el.text else "Imported"
    wrapper = Node(text=title)
    for o in outlines:
        wrapper.add_child(_opml_to_node(o))
    return MindMap(root=wrapper, title=title)


def _opml_to_node(elem: ET.Element) -> Node:
    text = elem.get("text") or elem.get("title") or "(untitled)"
    n = Node(text=text)
    for child in elem.findall("outline"):
        n.add_child(_opml_to_node(child))
    return n


# --- FreeMind / FreePlane (.mm) -------------------------------------------

def _load_freemind(path: str | Path) -> MindMap:
    try:
        tree = ET.parse(path)
    except ET.ParseError as e:
        raise MindMapImportError(f"FreeMind parse failed: {e}")
    root = tree.getroot()
    if root.tag != "map":
        raise MindMapImportError(f"Expected <map> root, got <{root.tag}>")
    root_node = root.find("node")
    if root_node is None:
        raise MindMapImportError("FreeMind file has no root <node>")
    return MindMap(root=_freemind_to_node(root_node))


def _freemind_to_node(elem: ET.Element) -> Node:
    text = elem.get("TEXT", "")
    if not text:
        rc = elem.find('richcontent[@TYPE="NODE"]')
        if rc is not None:
            text = " ".join(rc.itertext()).strip()
    if not text:
        text = "(untitled)"
    n = Node(text=text)
    for child in elem.findall("node"):
        n.add_child(_freemind_to_node(child))
    return n


# --- Markdown -------------------------------------------------------------

_HEADER_RE = re.compile(r"^(#+)\s+(.+?)\s*$")
_BULLET_RE = re.compile(r"^(\s*)[-*+]\s+(.+?)\s*$")


def _load_markdown(path: str | Path) -> MindMap:
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    has_heading = any(_HEADER_RE.match(line) for line in lines)
    if has_heading:
        return _parse_md_headings(lines)
    return _parse_md_bullets(lines)


def _parse_md_headings(lines: list[str]) -> MindMap:
    root: Node | None = None
    stack: list[tuple[int, Node]] = []
    for line in lines:
        m = _HEADER_RE.match(line)
        if not m:
            continue
        level = len(m.group(1))
        text = m.group(2).strip()
        node = Node(text=text)
        if root is None:
            root = node
            stack = [(level, node)]
            continue
        while stack and stack[-1][0] >= level:
            stack.pop()
        if not stack:
            root.add_child(node)
            stack = [(level, node)]
        else:
            stack[-1][1].add_child(node)
            stack.append((level, node))
    if root is None:
        raise MindMapImportError("No headings found in Markdown file")
    return MindMap(root=root)


def _parse_md_bullets(lines: list[str]) -> MindMap:
    items: list[tuple[int, str]] = []
    for line in lines:
        m = _BULLET_RE.match(line)
        if not m:
            continue
        indent = len(m.group(1).expandtabs(4))
        items.append((indent, m.group(2).strip()))
    if not items:
        raise MindMapImportError("No bullet items or headings found in Markdown file")
    wrapper = Node(text="Imported")
    stack: list[tuple[int, Node]] = [(-1, wrapper)]
    for indent, text in items:
        node = Node(text=text)
        while stack and stack[-1][0] >= indent:
            stack.pop()
        if not stack:
            stack = [(-1, wrapper)]
        stack[-1][1].add_child(node)
        stack.append((indent, node))
    if len(wrapper.children) == 1:
        return MindMap(root=wrapper.children[0])
    return MindMap(root=wrapper)


# --- XMind ----------------------------------------------------------------

def _load_xmind(path: str | Path) -> MindMap:
    try:
        zf = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        raise MindMapImportError("Not a valid XMind file (not a ZIP archive)")
    with zf:
        names = zf.namelist()
        if "content.json" in names:
            with zf.open("content.json") as f:
                try:
                    data = json.load(f)
                except json.JSONDecodeError as e:
                    raise MindMapImportError(
                        f"XMind content.json parse failed: {e}"
                    )
            return _parse_xmind_zen(data)
        if "content.xml" in names:
            with zf.open("content.xml") as f:
                return _parse_xmind_legacy(f.read())
        raise MindMapImportError(
            "XMind archive has neither content.json nor content.xml"
        )


def _parse_xmind_zen(data) -> MindMap:
    if not isinstance(data, list) or not data:
        raise MindMapImportError("XMind content.json: expected a non-empty list")
    sheet = data[0]
    topic = sheet.get("rootTopic")
    if not topic:
        raise MindMapImportError("XMind: first sheet has no rootTopic")
    return MindMap(
        root=_xmind_zen_to_node(topic),
        title=sheet.get("title", "Imported"),
    )


def _xmind_zen_to_node(topic: dict) -> Node:
    text = topic.get("title", "(untitled)")
    n = Node(text=text)
    children_data = topic.get("children") or {}
    for child in children_data.get("attached", []) or []:
        n.add_child(_xmind_zen_to_node(child))
    return n


def _parse_xmind_legacy(xml_bytes: bytes) -> MindMap:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        raise MindMapImportError(f"XMind content.xml parse failed: {e}")
    # Strip XML namespaces so .find("topic") etc. work
    for elem in root.iter():
        if "}" in elem.tag:
            elem.tag = elem.tag.split("}", 1)[1]
        for attr in list(elem.attrib):
            if "}" in attr:
                elem.attrib[attr.split("}", 1)[1]] = elem.attrib.pop(attr)
    sheet = root.find("sheet")
    if sheet is None:
        raise MindMapImportError("XMind legacy: no <sheet>")
    topic = sheet.find("topic")
    if topic is None:
        raise MindMapImportError("XMind legacy: no root <topic>")
    return MindMap(root=_xmind_legacy_to_node(topic))


def _xmind_legacy_to_node(elem: ET.Element) -> Node:
    title_el = elem.find("title")
    text = (title_el.text if title_el is not None else None) or "(untitled)"
    n = Node(text=text)
    container = elem.find("children/topics[@type='attached']")
    if container is None:
        container = elem.find("children/topics")
    if container is not None:
        for child in container.findall("topic"):
            n.add_child(_xmind_legacy_to_node(child))
    return n
