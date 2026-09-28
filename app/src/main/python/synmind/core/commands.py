"""Undo/redo commands. Each command knows how to do() and undo() itself."""
from __future__ import annotations

from dataclasses import dataclass, field

from synmind.core.model import MindMap, Node, _now_iso


class Command:
    label: str = "Command"

    def do(self, mind_map: MindMap) -> None:
        raise NotImplementedError

    def undo(self, mind_map: MindMap) -> None:
        raise NotImplementedError


@dataclass
class AddNodeCommand(Command):
    parent_id: str
    new_node: Node
    # -1 = append (existing behavior). Any other value inserts at that
    # position in the parent's children list, clamped to a valid index.
    insert_index: int = -1
    label: str = "Add Node"

    @property
    def node_id(self) -> str:
        return self.new_node.id

    def do(self, mind_map: MindMap) -> None:
        parent = mind_map.find(self.parent_id)
        if parent is None:
            return
        if not any(c.id == self.new_node.id for c in parent.children):
            if self.insert_index < 0 or self.insert_index >= len(parent.children):
                parent.add_child(self.new_node)
            else:
                parent.insert_child(self.insert_index, self.new_node)
            # Medical branch: a new node added under a medical-root ancestor
            # defaults its evidence to 5 (Needs verification) when unset, so
            # nothing enters the medical knowledge base unreviewed.
            try:
                if int(getattr(self.new_node, "evidence", 0) or 0) == 0 \
                        and mind_map.is_in_medical_branch(parent.id):
                    self.new_node.evidence = 5
            except Exception:
                pass

    def undo(self, mind_map: MindMap) -> None:
        parent = mind_map.find(self.parent_id)
        if parent is None:
            return
        parent.children = [c for c in parent.children if c.id != self.new_node.id]


@dataclass
class DeleteNodeCommand(Command):
    node_id: str
    label: str = "Delete Node"
    _parent_id: str = ""
    _index: int = -1
    _node: Node | None = None
    # Re-runs the layout after removing the node so remaining siblings
    # compact together. Without this, the row-height "budget" used by
    # the dead node stays, leaving a gap and accumulating imbalance as
    # more deletions happen. Cached on first execution for cheap redo;
    # the pre-delete positions sit on _old_positions for undo.
    _old_positions: dict[str, tuple[float, float]] | None = None
    _new_positions: dict[str, tuple[float, float]] | None = None

    def do(self, mind_map: MindMap) -> None:
        from synmind.core.layout import apply_layout

        if self._node is None:
            parent = mind_map.parent_of(self.node_id)
            if parent is None:
                return
            self._parent_id = parent.id
            self._index = mind_map.index_of_child(parent.id, self.node_id)
            self._node = parent.children[self._index]
        parent = mind_map.find(self._parent_id)
        if parent is None:
            return
        if self._new_positions is None:
            self._old_positions = {
                n.id: (n.x, n.y) for n in mind_map.all_nodes()
            }
            parent.children = [c for c in parent.children if c.id != self.node_id]
            apply_layout(mind_map)
            self._new_positions = {
                n.id: (n.x, n.y) for n in mind_map.all_nodes()
            }
        else:
            parent.children = [c for c in parent.children if c.id != self.node_id]
            for n in mind_map.all_nodes():
                if n.id in self._new_positions:
                    n.x, n.y = self._new_positions[n.id]

    def undo(self, mind_map: MindMap) -> None:
        if self._node is None:
            return
        parent = mind_map.find(self._parent_id)
        if parent is None:
            return
        parent.insert_child(min(self._index, len(parent.children)), self._node)
        if self._old_positions:
            for n in mind_map.all_nodes():
                if n.id in self._old_positions:
                    n.x, n.y = self._old_positions[n.id]


@dataclass
class MoveToTrashCommand(Command):
    """Remove a node subtree from the map AND append a TrashEntry to
    mind_map.trash. Mirrors DeleteNodeCommand's tree-removal + layout
    handling, but the subtree survives in the trash list so the user
    can restore it.

    Undo: pop the trash entry we appended, then re-insert the subtree
    under its original parent at its original index — bringing the
    map back to its pre-delete state. The trash entry only exists in
    trash for the duration the user has not undone, so undoing the
    delete cleanly removes both the gap and the trash row.
    """
    node_id: str
    label: str = "Move to Trash"
    _parent_id: str = ""
    _index: int = -1
    _node: Node | None = None
    _trash_entry: object | None = None  # core.model.TrashEntry; avoid circular import
    _old_positions: dict[str, tuple[float, float]] | None = None
    _new_positions: dict[str, tuple[float, float]] | None = None

    def do(self, mind_map: MindMap) -> None:
        from synmind.core.layout import apply_layout
        from synmind.core.model import TrashEntry, _now_iso

        if self._node is None:
            parent = mind_map.parent_of(self.node_id)
            if parent is None:
                return
            self._parent_id = parent.id
            self._index = mind_map.index_of_child(parent.id, self.node_id)
            self._node = parent.children[self._index]
        parent = mind_map.find(self._parent_id)
        if parent is None:
            return
        if self._new_positions is None:
            self._old_positions = {
                n.id: (n.x, n.y) for n in mind_map.all_nodes()
            }
            parent.children = [c for c in parent.children if c.id != self.node_id]
            apply_layout(mind_map)
            self._new_positions = {
                n.id: (n.x, n.y) for n in mind_map.all_nodes()
            }
            # First execution: build the TrashEntry the canvas / panel
            # will surface. On redo we reuse the same entry so its
            # deleted_at timestamp doesn't drift across undo/redo.
            display = (self._node.text or "").strip() or "(empty)"
            if len(display) > 80:
                display = display[:77] + "…"
            self._trash_entry = TrashEntry(
                node=self._node,
                parent_id=self._parent_id,
                child_index=self._index,
                deleted_at=_now_iso(),
                display_text=display,
            )
            mind_map.trash.append(self._trash_entry)
        else:
            parent.children = [c for c in parent.children if c.id != self.node_id]
            for n in mind_map.all_nodes():
                if n.id in self._new_positions:
                    n.x, n.y = self._new_positions[n.id]
            # Redo: re-append the SAME trash entry instance so the
            # trash panel re-shows the row identically.
            if self._trash_entry is not None and self._trash_entry not in mind_map.trash:
                mind_map.trash.append(self._trash_entry)

    def undo(self, mind_map: MindMap) -> None:
        if self._node is None:
            return
        parent = mind_map.find(self._parent_id)
        if parent is None:
            return
        # Pull the trash row we created (no-op if it was already purged
        # out-of-band; defensive but shouldn't happen during normal flow).
        if self._trash_entry is not None:
            try:
                mind_map.trash.remove(self._trash_entry)
            except ValueError:
                pass
        parent.insert_child(min(self._index, len(parent.children)), self._node)
        if self._old_positions:
            for n in mind_map.all_nodes():
                if n.id in self._old_positions:
                    n.x, n.y = self._old_positions[n.id]


@dataclass
class RestoreFromTrashCommand(Command):
    """Pop one TrashEntry out of mind_map.trash and re-insert its
    subtree under the original parent at the original index.

    If the original parent no longer exists in the map (it was also
    deleted, or the trash entry was somehow stranded), the node is
    restored under root as a fallback so the user doesn't lose the
    data outright.

    Undo: reverse — remove the restored node from wherever we put it
    and re-add the trash entry at its original position in the list.
    """
    trash_index: int
    label: str = "Restore from Trash"
    _entry: object | None = None  # TrashEntry; cached for redo / undo
    _restored_parent_id: str = ""
    _restored_child_index: int = -1
    _old_positions: dict[str, tuple[float, float]] | None = None
    _new_positions: dict[str, tuple[float, float]] | None = None

    def do(self, mind_map: MindMap) -> None:
        from synmind.core.layout import apply_layout

        # First-run vs redo bookkeeping mirrors DeleteNodeCommand.
        if self._new_positions is None:
            if not (0 <= self.trash_index < len(mind_map.trash)):
                return
            self._entry = mind_map.trash[self.trash_index]
            target_parent = mind_map.find(self._entry.parent_id)
            if target_parent is None:
                target_parent = mind_map.root
            self._restored_parent_id = target_parent.id
            insert_at = self._entry.child_index
            if insert_at < 0 or insert_at > len(target_parent.children):
                insert_at = len(target_parent.children)
            self._restored_child_index = insert_at
            self._old_positions = {
                n.id: (n.x, n.y) for n in mind_map.all_nodes()
            }
            mind_map.trash.pop(self.trash_index)
            target_parent.insert_child(insert_at, self._entry.node)
            apply_layout(mind_map)
            self._new_positions = {
                n.id: (n.x, n.y) for n in mind_map.all_nodes()
            }
        else:
            # Redo path
            if self._entry is None:
                return
            target_parent = mind_map.find(self._restored_parent_id)
            if target_parent is None:
                target_parent = mind_map.root
            # The trash entry was placed back in the list by undo; pop
            # it again (by identity, since trash_index may have shifted
            # if other entries moved around).
            try:
                mind_map.trash.remove(self._entry)
            except ValueError:
                pass
            insert_at = min(self._restored_child_index, len(target_parent.children))
            target_parent.insert_child(insert_at, self._entry.node)
            for n in mind_map.all_nodes():
                if n.id in self._new_positions:
                    n.x, n.y = self._new_positions[n.id]

    def undo(self, mind_map: MindMap) -> None:
        if self._entry is None:
            return
        parent = mind_map.find(self._restored_parent_id)
        if parent is not None:
            parent.children = [
                c for c in parent.children if c.id != self._entry.node.id
            ]
        # Put the trash entry back where it was in the trash list.
        idx = min(self.trash_index, len(mind_map.trash))
        mind_map.trash.insert(idx, self._entry)
        if self._old_positions:
            for n in mind_map.all_nodes():
                if n.id in self._old_positions:
                    n.x, n.y = self._old_positions[n.id]


@dataclass
class MoveNodeCommand(Command):
    node_id: str
    old_x: float
    old_y: float
    new_x: float
    new_y: float
    label: str = "Move Node"

    def do(self, mind_map: MindMap) -> None:
        node = mind_map.find(self.node_id)
        if node is None:
            return
        node.x = self.new_x
        node.y = self.new_y

    def undo(self, mind_map: MindMap) -> None:
        node = mind_map.find(self.node_id)
        if node is None:
            return
        node.x = self.old_x
        node.y = self.old_y


@dataclass
class EditTextCommand(Command):
    node_id: str
    old_text: str
    new_text: str
    # Rich-text snapshots. None on either side means "plain text"; legacy
    # callers (canvas note-derived rename, etc.) pass neither and the
    # command just edits the plain-text body without touching text_html,
    # preserving existing behavior for non-rich edits.
    old_text_html: str | None = None
    new_text_html: str | None = None
    label: str = "Edit Text"
    _old_updated_at: str | None = field(default=None)
    _new_updated_at: str | None = field(default=None)
    _captured_html: bool = False

    def do(self, mind_map: MindMap) -> None:
        node = mind_map.find(self.node_id)
        if node is None:
            return
        if self._new_updated_at is None:
            self._old_updated_at = node.updated_at
            self._new_updated_at = _now_iso()
        # First run: snapshot the node's prior text_html so undo restores
        # the rich-text state too — callers from non-rich paths don't pass
        # old_text_html, but we still want a faithful undo.
        if not self._captured_html:
            self.old_text_html = node.text_html
            self._captured_html = True
        node.text = self.new_text
        node.text_html = self.new_text_html
        node.updated_at = self._new_updated_at

    def undo(self, mind_map: MindMap) -> None:
        node = mind_map.find(self.node_id)
        if node is None:
            return
        node.text = self.old_text
        node.text_html = self.old_text_html
        if self._old_updated_at is not None:
            node.updated_at = self._old_updated_at


@dataclass
class SetImageCommand(Command):
    node_id: str
    old_data: str | None
    old_format: str | None
    new_data: str | None
    new_format: str | None
    label: str = "Set Image"
    _old_updated_at: str | None = field(default=None)
    _new_updated_at: str | None = field(default=None)

    def do(self, mind_map: MindMap) -> None:
        node = mind_map.find(self.node_id)
        if node is None:
            return
        if self._new_updated_at is None:
            self._old_updated_at = node.updated_at
            self._new_updated_at = _now_iso()
        node.image_data = self.new_data
        node.image_format = self.new_format
        node.updated_at = self._new_updated_at

    def undo(self, mind_map: MindMap) -> None:
        node = mind_map.find(self.node_id)
        if node is None:
            return
        node.image_data = self.old_data
        node.image_format = self.old_format
        if self._old_updated_at is not None:
            node.updated_at = self._old_updated_at


@dataclass
class SetCompletionRateCommand(Command):
    """Set (or clear) a node's manual completion-rate bullet. `new_rate`
    is one of 0/20/40/60/80/100, or None to remove the bullet.

    The completion RATE is the source of truth for a work node's
    completeness, so this command also bundles the completion CASCADE so a
    single Ctrl+Z reverses everything it caused:
      * 100%  → stamp `completed_at` and turn every node in this node's
        `do_after_completion` list into a Working node.
      * below → clear `completed_at` (un-complete).
    The prior `completed_at` and each fired target's prior `working` flag
    are captured on first do() and restored on undo()."""

    node_id: str
    old_rate: int | None
    new_rate: int | None
    label: str = "Set Completion Rate"
    _old_updated_at: str | None = field(default=None)
    _new_updated_at: str | None = field(default=None)
    _captured: bool = field(default=False)
    _old_completed_at: str | None = field(default=None)
    _new_completed_at: str | None = field(default=None)
    # target id -> its `working` value BEFORE this command changed it, and
    # the value the command SET it to (True when firing at 100%, False when
    # un-firing on a drop below 100%). Kept separate so redo re-applies the
    # right value and undo restores the original.
    _target_prev_working: dict = field(default_factory=dict)
    _target_new_working: dict = field(default_factory=dict)
    # This node's own `working` value before the command, whether the
    # command changed it, and the value it set (partial <100% → Working;
    # 100% → NOT working, since the node is now complete).
    _node_prev_working: bool = field(default=False)
    _node_set_working: bool = field(default=False)
    _node_new_working: bool = field(default=False)
    # FINISHED-sentinel auto-completion: node_id -> prior/new
    # (completed_at, completion_rate, working) so completing a flow's last
    # feeder can auto-complete FINISHED and its START, reversibly.
    _finish_prev: dict = field(default_factory=dict)
    _finish_new: dict = field(default_factory=dict)

    def do(self, mind_map: MindMap) -> None:
        node = mind_map.find(self.node_id)
        if node is None:
            return
        if self._new_updated_at is None:
            self._old_updated_at = node.updated_at
            self._new_updated_at = _now_iso()
        node.completion_rate = self.new_rate
        node.updated_at = self._new_updated_at
        if not self._captured:
            self._capture_and_apply(mind_map, node)
            self._captured = True
        else:
            self._replay(mind_map, node)

    def _capture_and_apply(self, mind_map: MindMap, node: Node) -> None:
        self._old_completed_at = node.completed_at
        self._node_prev_working = bool(getattr(node, "working", False))
        if self.new_rate == 100:
            self._new_completed_at = node.completed_at or _now_iso()
            node.completed_at = self._new_completed_at
            # The node is now COMPLETE, so it's no longer a work node —
            # clear working so it reads as done (green), not active (orange).
            node.working = False
            self._node_set_working = True
            self._node_new_working = False
            # Completing a FINISHED sentinel completes the START (origin) node
            # of its flow and clears the origin's work mode.
            if getattr(node, "workflow_finish_for", None):
                self._complete_origin_of_finish(mind_map, node)
            self._set_targets(mind_map, node, True)
        elif self.old_rate == 100:
            self._new_completed_at = None
            node.completed_at = None
            # Dropping below 100% un-completes the node, so the descendant
            # nodes it had activated revert to NOT working.
            self._set_targets(mind_map, node, False)
        else:
            self._new_completed_at = node.completed_at
        # A partial completion (0–80%) means the node is still in progress,
        # so it becomes a Working node.
        if self.new_rate is not None and self.new_rate < 100:
            node.working = True
            self._node_set_working = True
            self._node_new_working = True

    def _all_inputs_complete(self, mind_map: MindMap, target_id: str) -> bool:
        """True when EVERY node with a do_after_completion edge INTO
        `target_id` is completed (or it has none). The AND-gate: a node only
        starts working once all its incoming feeders have finished."""
        for n in mind_map.root.walk():
            if getattr(n, "alias_of", None) is not None:
                continue
            if target_id in (getattr(n, "do_after_completion", None) or []):
                if not bool(getattr(n, "completed_at", None)):
                    return False
        return True

    def _complete_finish(self, mind_map: MindMap, finish: Node) -> None:
        """A FINISHED sentinel's incoming AND-gate is satisfied → stamp it
        complete and complete the START (origin) node it stands for. Captured
        so undo can reverse both."""
        for tgt in (finish, mind_map.find(
                str(getattr(finish, "workflow_finish_for", "")) or "")):
            if tgt is None:
                continue
            tgt = mind_map.resolve_alias(tgt)
            if bool(getattr(tgt, "completed_at", None)):
                continue
            self._finish_prev.setdefault(tgt.id, (
                tgt.completed_at,
                getattr(tgt, "completion_rate", None),
                bool(getattr(tgt, "working", False)),
            ))
            tgt.completed_at = _now_iso()
            tgt.completion_rate = 100
            tgt.working = False
            self._finish_new[tgt.id] = (tgt.completed_at, 100, False)

    def _uncomplete_finish(self, mind_map: MindMap, finish: Node) -> None:
        """A FINISHED sentinel lost a required input (an upstream node dropped
        below 100%) → revert it and its START origin to incomplete: FINISHED
        goes idle, the origin resumes working. Reversible."""
        origin_id = getattr(finish, "workflow_finish_for", None)
        origin = mind_map.find(str(origin_id)) if origin_id else None
        for tgt, resumes_working in ((finish, False), (origin, True)):
            if tgt is None:
                continue
            tgt = mind_map.resolve_alias(tgt)
            self._finish_prev.setdefault(tgt.id, (
                tgt.completed_at,
                getattr(tgt, "completion_rate", None),
                bool(getattr(tgt, "working", False)),
            ))
            tgt.completed_at = None
            tgt.completion_rate = 0
            tgt.working = resumes_working
            self._finish_new[tgt.id] = (None, 0, resumes_working)

    def _complete_origin_of_finish(
        self, mind_map: MindMap, finish: Node
    ) -> None:
        """FINISHED itself was completed directly → complete the START
        (origin) node it stands for and clear its work mode. Reversible."""
        origin_id = getattr(finish, "workflow_finish_for", None)
        origin = mind_map.find(str(origin_id)) if origin_id else None
        if origin is None:
            return
        origin = mind_map.resolve_alias(origin)
        if bool(getattr(origin, "completed_at", None)):
            return
        self._finish_prev.setdefault(origin.id, (
            origin.completed_at,
            getattr(origin, "completion_rate", None),
            bool(getattr(origin, "working", False)),
        ))
        origin.completed_at = _now_iso()
        origin.completion_rate = 100
        origin.working = False
        self._finish_new[origin.id] = (origin.completed_at, 100, False)

    def _set_targets(self, mind_map: MindMap, node: Node, value: bool) -> None:
        """Activate/deactivate this node's do-after targets. When firing
        (value=True) the AND-gate applies — a target only starts once ALL of
        its own inputs are complete — and a FINISHED sentinel auto-completes
        instead of merely turning Working. Prior values are recorded for undo."""
        for rid in list(getattr(node, "do_after_completion", None) or []):
            tgt = mind_map.find(str(rid))
            if tgt is None:
                continue
            tgt = mind_map.resolve_alias(tgt)
            if value:
                if not self._all_inputs_complete(mind_map, tgt.id):
                    continue  # not all feeders done yet — don't start it
                if bool(getattr(tgt, "completed_at", None)):
                    continue  # already 100% done → stays complete, not working
                if getattr(tgt, "workflow_finish_for", None):
                    self._complete_finish(mind_map, tgt)
                    continue
            else:
                # Un-firing (the node dropped below 100%). A FINISHED sentinel
                # that had auto-completed but has now lost a required input
                # reverts to incomplete — and its START origin with it.
                if getattr(tgt, "workflow_finish_for", None) \
                        and bool(getattr(tgt, "completed_at", None)) \
                        and not self._all_inputs_complete(mind_map, tgt.id):
                    self._uncomplete_finish(mind_map, tgt)
                    continue
            self._target_prev_working.setdefault(
                tgt.id, bool(getattr(tgt, "working", False))
            )
            self._target_new_working[tgt.id] = value
            tgt.working = value

    def _replay(self, mind_map: MindMap, node: Node) -> None:
        node.completed_at = self._new_completed_at
        if self._node_set_working:
            node.working = self._node_new_working
        for tid, val in self._target_new_working.items():
            t = mind_map.find(tid)
            if t is not None:
                mind_map.resolve_alias(t).working = val
        for nid, (ca, cr, wk) in self._finish_new.items():
            t = mind_map.find(nid)
            if t is not None:
                t = mind_map.resolve_alias(t)
                t.completed_at, t.completion_rate, t.working = ca, cr, wk

    def undo(self, mind_map: MindMap) -> None:
        node = mind_map.find(self.node_id)
        if node is None:
            return
        node.completion_rate = self.old_rate
        if self._old_updated_at is not None:
            node.updated_at = self._old_updated_at
        node.completed_at = self._old_completed_at
        if self._node_set_working:
            node.working = self._node_prev_working
        for tid, prev in self._target_prev_working.items():
            t = mind_map.find(tid)
            if t is not None:
                mind_map.resolve_alias(t).working = prev
        for nid, (ca, cr, wk) in self._finish_prev.items():
            t = mind_map.find(nid)
            if t is not None:
                t = mind_map.resolve_alias(t)
                t.completed_at, t.completion_rate, t.working = ca, cr, wk


@dataclass
class SetDoAfterCompletionCommand(Command):
    """Replace a node's `do_after_completion` list — the undoable backing
    for adding a copied node to / removing a node from the 'Do after
    completion' work list."""

    node_id: str
    old_list: list
    new_list: list
    label: str = "Edit Do-After List"

    def do(self, mind_map: MindMap) -> None:
        node = mind_map.find(self.node_id)
        if node is not None:
            node.do_after_completion = list(self.new_list)

    def undo(self, mind_map: MindMap) -> None:
        node = mind_map.find(self.node_id)
        if node is not None:
            node.do_after_completion = list(self.old_list)


@dataclass
class AddToWorkFlowCommand(Command):
    """Add `child_id` as a completion-child of `parent_id` in a Work Flow:
    appends it to the parent's `do_after_completion` list AND flags the
    child `in_work_flow` so it shows in the flow map."""

    parent_id: str
    child_id: str
    label: str = "Add to Work Flow"
    _did_add: bool = field(default=False)
    _child_prev_in_flow: bool = field(default=False)

    def do(self, mind_map: MindMap) -> None:
        parent = mind_map.find(self.parent_id)
        child = mind_map.find(self.child_id)
        if parent is None or child is None:
            return
        self._child_prev_in_flow = bool(getattr(child, "in_work_flow", False))
        lst = list(getattr(parent, "do_after_completion", None) or [])
        if self.child_id not in lst:
            lst.append(self.child_id)
            parent.do_after_completion = lst
            self._did_add = True
        child.in_work_flow = True

    def undo(self, mind_map: MindMap) -> None:
        parent = mind_map.find(self.parent_id)
        child = mind_map.find(self.child_id)
        if parent is not None and self._did_add:
            parent.do_after_completion = [
                x for x in (getattr(parent, "do_after_completion", None) or [])
                if x != self.child_id
            ]
        if child is not None:
            child.in_work_flow = self._child_prev_in_flow


@dataclass
class SetPriorityLevelCommand(Command):
    """Set (1–5) or clear (None) a node's general priority label."""

    node_id: str
    new_level: "int | None"
    label: str = "Set Priority"
    _old_level: "int | None" = field(default=None)
    _captured: bool = field(default=False)

    def do(self, mind_map: MindMap) -> None:
        node = mind_map.find(self.node_id)
        if node is None:
            return
        if not self._captured:
            self._old_level = getattr(node, "priority_level", None)
            self._captured = True
        node.priority_level = self.new_level

    def undo(self, mind_map: MindMap) -> None:
        node = mind_map.find(self.node_id)
        if node is not None:
            node.priority_level = self._old_level


@dataclass
class SetMaturityCommand(Command):
    """Set (1–5) or clear (0) a node's knowledge-maturity level."""

    node_id: str
    new_level: int
    label: str = "Set Knowledge Maturity"
    _old_level: int = field(default=0)
    _captured: bool = field(default=False)

    def do(self, mind_map: MindMap) -> None:
        node = mind_map.find(self.node_id)
        if node is None:
            return
        if not self._captured:
            self._old_level = int(getattr(node, "maturity", 0) or 0)
            self._captured = True
        node.maturity = int(self.new_level)

    def undo(self, mind_map: MindMap) -> None:
        node = mind_map.find(self.node_id)
        if node is not None:
            node.maturity = self._old_level


@dataclass
class SetEvidenceCommand(Command):
    """Set (1–5) or clear (0) a node's evidence-basis indicator."""

    node_id: str
    new_level: int
    label: str = "Set Evidence"
    _old_level: int = field(default=0)
    _captured: bool = field(default=False)

    def do(self, mind_map: MindMap) -> None:
        node = mind_map.find(self.node_id)
        if node is None:
            return
        if not self._captured:
            self._old_level = int(getattr(node, "evidence", 0) or 0)
            self._captured = True
        node.evidence = int(self.new_level)

    def undo(self, mind_map: MindMap) -> None:
        node = mind_map.find(self.node_id)
        if node is not None:
            node.evidence = self._old_level


@dataclass
class SetMedicalRootCommand(Command):
    """Flag (or unflag) a node as a medical-branch root. When turning it ON,
    every descendant whose evidence is unset defaults to 5 (Needs
    verification). Captures those changes so undo restores them exactly."""

    node_id: str
    new_on: bool
    label: str = "Mark Medical Branch"
    _old_on: bool = field(default=False)
    # node_id -> prior evidence, for descendants we defaulted.
    _defaulted: dict = field(default_factory=dict)
    _captured: bool = field(default=False)

    def do(self, mind_map: MindMap) -> None:
        node = mind_map.find(self.node_id)
        if node is None:
            return
        if not self._captured:
            self._old_on = bool(getattr(node, "is_medical_root", False))
            self._captured = True
        node.is_medical_root = bool(self.new_on)
        if self.new_on:
            for d in node.walk():
                if int(getattr(d, "evidence", 0) or 0) == 0:
                    self._defaulted.setdefault(d.id, 0)
                    d.evidence = 5
        else:
            # Re-apply the recorded defaults on redo of an un-flag is a no-op;
            # nothing to change here (the flag alone is cleared).
            pass

    def undo(self, mind_map: MindMap) -> None:
        node = mind_map.find(self.node_id)
        if node is not None:
            node.is_medical_root = self._old_on
        for nid, prev in self._defaulted.items():
            d = mind_map.find(nid)
            if d is not None:
                d.evidence = prev


@dataclass
class SetWorkFlowMemberCommand(Command):
    """Toggle a node's `in_work_flow` flag — the undoable backing for the
    'Make Work Flow Node' mark. A standalone in_work_flow node is its own
    (trivial) flow top until other nodes are linked under it."""

    node_id: str
    new_value: bool
    label: str = "Set Work Flow Node"
    _old: bool = field(default=False)

    def do(self, mind_map: MindMap) -> None:
        n = mind_map.find(self.node_id)
        if n is not None:
            self._old = bool(getattr(n, "in_work_flow", False))
            n.in_work_flow = self.new_value

    def undo(self, mind_map: MindMap) -> None:
        n = mind_map.find(self.node_id)
        if n is not None:
            n.in_work_flow = self._old


@dataclass
class DeleteWorkFlowCommand(Command):
    """Dismantle the whole work flow rooted at `top_id`.

    Clears every work-flow field (membership, name, group id, finish links,
    saved positions, do_after_completion links) on the START and all its
    members, AND removes the synthetic `FINISHED:` sentinel node that
    Start Work Flow created. Ordinary nodes stay on the map — only the flow
    definition and the sentinel go. The node's independent `working` (orange)
    status is left untouched. Fully reversible."""

    top_id: str
    label: str = "Delete Work Flow"
    # nid -> {field: value} snapshot of cleared flow fields.
    _field_snapshot: dict = field(default_factory=dict)
    # (parent_id, index, node) for each removed FINISHED sentinel.
    _removed_finish: list = field(default_factory=list)

    # Every flow field wiped on delete. `working` is intentionally excluded —
    # deleting the flow shouldn't change whether the node is being worked on.
    _WF_FIELDS = (
        "in_work_flow", "workflow_name", "workflow_finish_id",
        "workflow_finish_for", "workflow_pos", "workflow_group_id",
        "do_after_completion",
    )
    _WF_DEFAULTS = {
        "in_work_flow": False,
        "workflow_name": "",
        "workflow_finish_id": None,
        "workflow_finish_for": None,
        "workflow_pos": None,
        "workflow_group_id": None,
        "do_after_completion": None,   # -> [] applied below
    }

    def _members(self, mind_map: MindMap) -> set:
        """Every node in the flow: the do_after_completion chain from the
        top, plus anything tagged with this flow's group id, plus the
        top's FINISHED sentinel."""
        seen: set = set()
        stack = [self.top_id]
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            n = mind_map.find(cur)
            if n is not None:
                stack.extend(getattr(n, "do_after_completion", None) or [])
        for n in mind_map.root.walk():
            if getattr(n, "workflow_group_id", None) == self.top_id:
                seen.add(n.id)
            if getattr(n, "workflow_finish_for", None) == self.top_id:
                seen.add(n.id)
        top = mind_map.find(self.top_id)
        if top is not None and getattr(top, "workflow_finish_id", None):
            seen.add(top.workflow_finish_id)
        return seen

    def _finish_ids(self, mind_map: MindMap, members: set) -> set:
        """The FINISHED sentinel node ids to remove from the tree."""
        finish: set = set()
        top = mind_map.find(self.top_id)
        if top is not None and getattr(top, "workflow_finish_id", None):
            finish.add(top.workflow_finish_id)
        for nid in members:
            n = mind_map.find(nid)
            if n is not None and getattr(
                n, "workflow_finish_for", None
            ) == self.top_id:
                finish.add(nid)
        return finish

    def do(self, mind_map: MindMap) -> None:
        self._field_snapshot = {}
        self._removed_finish = []
        members = self._members(mind_map)
        finish_ids = self._finish_ids(mind_map, members)

        # Snapshot the flow fields on every member first.
        for nid in members:
            n = mind_map.find(nid)
            if n is None:
                continue
            snap = {}
            for f in self._WF_FIELDS:
                v = getattr(n, f, None)
                snap[f] = list(v) if isinstance(v, list) else v
            self._field_snapshot[nid] = snap

        # Remove the FINISHED sentinel node(s) from the tree.
        for fid in finish_ids:
            fnode = mind_map.find(fid)
            parent = mind_map.parent_of(fid)
            if fnode is None or parent is None:
                continue
            try:
                idx = parent.children.index(fnode)
            except ValueError:
                continue
            self._removed_finish.append((parent.id, idx, fnode))
            parent.children.pop(idx)

        # Clear the flow fields on every member.
        for nid in self._field_snapshot:
            n = mind_map.find(nid)
            if n is None:
                continue
            for f, default in self._WF_DEFAULTS.items():
                setattr(n, f, [] if f == "do_after_completion" else default)

        try:
            mind_map.invalidate_lookup_cache()
        except Exception:
            pass

    def undo(self, mind_map: MindMap) -> None:
        # Re-insert removed FINISHED sentinels at their original spots.
        for parent_id, idx, fnode in self._removed_finish:
            parent = mind_map.find(parent_id)
            if parent is not None:
                parent.children.insert(min(idx, len(parent.children)), fnode)
        # Restore the flow fields on every member.
        for nid, snap in self._field_snapshot.items():
            n = mind_map.find(nid)
            if n is None:
                continue
            for f, v in snap.items():
                setattr(n, f, list(v) if isinstance(v, list) else v)
        try:
            mind_map.invalidate_lookup_cache()
        except Exception:
            pass


@dataclass
class MoveInWorkFlowCommand(Command):
    """Reparent a node within a work flow: detach it from every current
    completion-parent and attach it under `new_parent_id`. Backs the
    drag-to-reparent gesture in the Work Flow Map."""

    child_id: str
    new_parent_id: str
    label: str = "Move in Work Flow"
    _removed_from: list = field(default_factory=list)
    _added_to_new: bool = field(default=False)
    _child_prev_in_flow: bool = field(default=False)

    def do(self, mind_map: MindMap) -> None:
        child = mind_map.find(self.child_id)
        parent = mind_map.find(self.new_parent_id)
        if child is None or parent is None:
            return
        self._child_prev_in_flow = bool(getattr(child, "in_work_flow", False))
        self._removed_from = []
        for n in mind_map.root.walk():
            if n.id == self.new_parent_id:
                continue
            lst = getattr(n, "do_after_completion", None) or []
            if self.child_id in lst:
                self._removed_from.append(n.id)
                n.do_after_completion = [x for x in lst if x != self.child_id]
        plst = list(getattr(parent, "do_after_completion", None) or [])
        if self.child_id not in plst:
            plst.append(self.child_id)
            parent.do_after_completion = plst
            self._added_to_new = True
        child.in_work_flow = True

    def undo(self, mind_map: MindMap) -> None:
        parent = mind_map.find(self.new_parent_id)
        if parent is not None and self._added_to_new:
            parent.do_after_completion = [
                x for x in (getattr(parent, "do_after_completion", None) or [])
                if x != self.child_id
            ]
        for pid in self._removed_from:
            p = mind_map.find(pid)
            if p is None:
                continue
            lst = list(getattr(p, "do_after_completion", None) or [])
            if self.child_id not in lst:
                lst.append(self.child_id)
                p.do_after_completion = lst
        child = mind_map.find(self.child_id)
        if child is not None:
            child.in_work_flow = self._child_prev_in_flow


@dataclass
class RemoveFromWorkFlowCommand(Command):
    """Remove a node from a Work Flow: drop it from EVERY parent's
    `do_after_completion` list and clear its `in_work_flow` flag."""

    node_id: str
    label: str = "Remove from Work Flow"
    _removed_from: list = field(default_factory=list)
    _prev_in_flow: bool = field(default=False)

    def do(self, mind_map: MindMap) -> None:
        node = mind_map.find(self.node_id)
        if node is None:
            return
        self._prev_in_flow = bool(getattr(node, "in_work_flow", False))
        self._removed_from = []
        for n in mind_map.root.walk():
            lst = getattr(n, "do_after_completion", None) or []
            if self.node_id in lst:
                self._removed_from.append(n.id)
                n.do_after_completion = [x for x in lst if x != self.node_id]
        node.in_work_flow = False

    def undo(self, mind_map: MindMap) -> None:
        for pid in self._removed_from:
            p = mind_map.find(pid)
            if p is None:
                continue
            lst = list(getattr(p, "do_after_completion", None) or [])
            if self.node_id not in lst:
                lst.append(self.node_id)
                p.do_after_completion = lst
        node = mind_map.find(self.node_id)
        if node is not None:
            node.in_work_flow = self._prev_in_flow


@dataclass
class SetFillColorCommand(Command):
    node_id: str
    old_color: str | None
    new_color: str | None
    label: str = "Set Color"
    _old_updated_at: str | None = field(default=None)
    _new_updated_at: str | None = field(default=None)

    def do(self, mind_map: MindMap) -> None:
        node = mind_map.find(self.node_id)
        if node is None:
            return
        if self._new_updated_at is None:
            self._old_updated_at = node.updated_at
            self._new_updated_at = _now_iso()
        node.fill_color = self.new_color
        node.updated_at = self._new_updated_at

    def undo(self, mind_map: MindMap) -> None:
        node = mind_map.find(self.node_id)
        if node is None:
            return
        node.fill_color = self.old_color
        if self._old_updated_at is not None:
            node.updated_at = self._old_updated_at


@dataclass
class SetBorderColorCommand(Command):
    """The node's frame colour. Mirror of SetFillColorCommand, kept
    separate so fill and frame undo independently - setting both and
    then pressing Ctrl+Z once should take back one of them."""
    node_id: str
    old_color: str | None
    new_color: str | None
    label: str = "Set Frame Color"
    _old_updated_at: str | None = field(default=None)
    _new_updated_at: str | None = field(default=None)

    def do(self, mind_map: MindMap) -> None:
        node = mind_map.find(self.node_id)
        if node is None:
            return
        if self._new_updated_at is None:
            self._old_updated_at = node.updated_at
            self._new_updated_at = _now_iso()
        node.border_color = self.new_color
        node.updated_at = self._new_updated_at

    def undo(self, mind_map: MindMap) -> None:
        node = mind_map.find(self.node_id)
        if node is None:
            return
        node.border_color = self.old_color
        if self._old_updated_at is not None:
            node.updated_at = self._old_updated_at


@dataclass
class SetFunctionIdCommand(Command):
    """Turn an EXISTING node into a function, or back again.

    Distinct from AddNodeCommand, which brings a new function node and
    its settings subtree in together. This one converts a node that is
    already on the map and already has children — the case being: a node
    whose children are functions, which the user wants to run as one
    Multi-Function Set. Adding a set beside it would mean re-parenting
    everything underneath.

    Only `function_id` moves. The children, the text, and any settings
    already under the node are left exactly as they are, so an undo puts
    the node back to an ordinary node with its subtree untouched.
    """
    node_id: str
    old_function_id: str | None
    new_function_id: str | None
    label: str = "Make Function"
    _old_updated_at: str | None = field(default=None)
    _new_updated_at: str | None = field(default=None)

    def do(self, mind_map: MindMap) -> None:
        node = mind_map.find(self.node_id)
        if node is None:
            return
        if self._new_updated_at is None:
            self._old_updated_at = node.updated_at
            self._new_updated_at = _now_iso()
        node.function_id = self.new_function_id
        node.updated_at = self._new_updated_at

    def undo(self, mind_map: MindMap) -> None:
        node = mind_map.find(self.node_id)
        if node is None:
            return
        node.function_id = self.old_function_id
        if self._old_updated_at is not None:
            node.updated_at = self._old_updated_at


@dataclass
class SetAttachmentsCommand(Command):
    """Replace the node's attachments list wholesale. Used by
    'Remove Image(s)' so Ctrl+Z restores every dropped attachment
    reference at once (the underlying files stay on disk regardless
    — only the reference from this node moves)."""
    node_id: str
    old_attachments: list
    new_attachments: list
    label: str = "Change Attachments"

    def do(self, mind_map: MindMap) -> None:
        node = mind_map.find(self.node_id)
        if node is None:
            return
        node.attachments = list(self.new_attachments)

    def undo(self, mind_map: MindMap) -> None:
        node = mind_map.find(self.node_id)
        if node is None:
            return
        node.attachments = list(self.old_attachments)


@dataclass
class SetManualWidthCommand(Command):
    """Set (or clear) a node's manual body-width override. Passing
    `new_width = None` puts the node back to auto-sizing."""
    node_id: str
    old_width: float | None
    new_width: float | None
    label: str = "Resize Node"

    def do(self, mind_map: MindMap) -> None:
        node = mind_map.find(self.node_id)
        if node is None:
            return
        node.manual_width = self.new_width

    def undo(self, mind_map: MindMap) -> None:
        node = mind_map.find(self.node_id)
        if node is None:
            return
        node.manual_width = self.old_width


@dataclass
class SetThemeCommand(Command):
    old_theme: str
    new_theme: str
    label: str = "Change Theme"

    def do(self, mind_map: MindMap) -> None:
        mind_map.theme_name = self.new_theme

    def undo(self, mind_map: MindMap) -> None:
        mind_map.theme_name = self.old_theme


@dataclass
class SetMapColorsCommand(Command):
    """Map-wide node fill / text color. Both round-trip together so one
    Ctrl+Z restores the pair — setting a fill usually implies a matching
    text color, and undoing only half leaves the map unreadable."""
    old_fill: str | None
    new_fill: str | None
    old_text: str | None
    new_text: str | None
    label: str = "Set Map Colors"

    _old_auto: bool | None = field(default=None)

    def do(self, mind_map: MindMap) -> None:
        if self._old_auto is None:
            self._old_auto = bool(mind_map.map_text_color_auto)
        mind_map.map_node_fill_color = self.new_fill
        mind_map.map_node_text_color = self.new_text
        # An explicit pick is the user's, so the optimizer must not
        # later release it as if it were its own correction.
        mind_map.map_text_color_auto = False

    def undo(self, mind_map: MindMap) -> None:
        mind_map.map_node_fill_color = self.old_fill
        mind_map.map_node_text_color = self.old_text
        mind_map.map_text_color_auto = bool(self._old_auto)


@dataclass
class OptimizeMapColorsCommand(Command):
    """Apply a `colors.ColorOptimization` plan — the map-wide text color
    plus every per-node `text_color` rewrite — as one undoable unit.

    Built from a pre-computed plan rather than re-deriving on `do()`
    because this command is usually bundled behind the theme change that
    triggered it: by the time it runs inside a CompositeCommand the theme
    has already flipped, and re-planning then would score contrast
    against the wrong palette on redo.
    """
    old_map_text: str | None
    new_map_text: str | None
    old_map_text_auto: bool = False
    new_map_text_auto: bool = False
    node_changes: list[tuple[str, str | None, str | None]] = field(
        default_factory=list
    )
    label: str = "Optimize Colors"

    @classmethod
    def from_plan(cls, plan) -> "OptimizeMapColorsCommand":
        return cls(
            old_map_text=plan.old_map_text_color,
            new_map_text=plan.new_map_text_color,
            old_map_text_auto=plan.old_map_text_auto,
            new_map_text_auto=plan.new_map_text_auto,
            node_changes=list(plan.node_changes),
        )

    def do(self, mind_map: MindMap) -> None:
        mind_map.map_node_text_color = self.new_map_text
        mind_map.map_text_color_auto = self.new_map_text_auto
        for node_id, _old, new in self.node_changes:
            node = mind_map.find(node_id)
            if node is not None:
                node.text_color = new

    def undo(self, mind_map: MindMap) -> None:
        mind_map.map_node_text_color = self.old_map_text
        mind_map.map_text_color_auto = self.old_map_text_auto
        for node_id, old, _new in self.node_changes:
            node = mind_map.find(node_id)
            if node is not None:
                node.text_color = old


@dataclass
class ApplyLayoutCommand(Command):
    """Captures all node positions before applying tidy layout, restores them on undo."""
    label: str = "Auto Arrange"
    _old_positions: dict[str, tuple[float, float]] | None = field(default=None)
    _new_positions: dict[str, tuple[float, float]] | None = field(default=None)

    def do(self, mind_map: MindMap) -> None:
        from synmind.core.layout import apply_layout

        if self._new_positions is None:
            self._old_positions = {n.id: (n.x, n.y) for n in mind_map.all_nodes()}
            apply_layout(mind_map)
            self._new_positions = {n.id: (n.x, n.y) for n in mind_map.all_nodes()}
        else:
            for n in mind_map.all_nodes():
                if n.id in self._new_positions:
                    n.x, n.y = self._new_positions[n.id]

    def undo(self, mind_map: MindMap) -> None:
        if self._old_positions is None:
            return
        for n in mind_map.all_nodes():
            if n.id in self._old_positions:
                n.x, n.y = self._old_positions[n.id]


@dataclass
class SetLineStyleCommand(Command):
    old_style: str
    new_style: str
    label: str = "Change Line Style"

    def do(self, mind_map: MindMap) -> None:
        mind_map.line_style = self.new_style

    def undo(self, mind_map: MindMap) -> None:
        mind_map.line_style = self.old_style


@dataclass
class SetLineThicknessCommand(Command):
    old_thickness: float
    new_thickness: float
    label: str = "Change Line Thickness"

    def do(self, mind_map: MindMap) -> None:
        mind_map.line_thickness = self.new_thickness

    def undo(self, mind_map: MindMap) -> None:
        mind_map.line_thickness = self.old_thickness


@dataclass
class SetEdgeThicknessCommand(Command):
    node_id: str
    old_thickness: float | None
    new_thickness: float | None
    label: str = "Set Edge Thickness"
    _old_updated_at: str | None = field(default=None)
    _new_updated_at: str | None = field(default=None)

    def do(self, mind_map: MindMap) -> None:
        node = mind_map.find(self.node_id)
        if node is None:
            return
        if self._new_updated_at is None:
            self._old_updated_at = node.updated_at
            self._new_updated_at = _now_iso()
        node.edge_thickness = self.new_thickness
        node.updated_at = self._new_updated_at

    def undo(self, mind_map: MindMap) -> None:
        node = mind_map.find(self.node_id)
        if node is None:
            return
        node.edge_thickness = self.old_thickness
        if self._old_updated_at is not None:
            node.updated_at = self._old_updated_at


@dataclass
class ReorderNodeCommand(Command):
    """Move a node to a new index within its parent's children list and re-run
    the layout. Used by drag-to-reorder. Caches before/after positions so undo
    and redo are both cheap."""
    parent_id: str
    node_id: str
    old_index: int
    new_index: int
    label: str = "Reorder Node"
    _old_positions: dict[str, tuple[float, float]] | None = field(default=None)
    _new_positions: dict[str, tuple[float, float]] | None = field(default=None)

    def do(self, mind_map: MindMap) -> None:
        from synmind.core.layout import apply_layout

        parent = mind_map.find(self.parent_id)
        if parent is None:
            return
        node = next(
            (c for c in parent.children if c.id == self.node_id), None
        )
        if node is None:
            return

        if self._new_positions is None:
            # First execution: snapshot, mutate, layout, snapshot new state.
            self._old_positions = {
                n.id: (n.x, n.y) for n in mind_map.all_nodes()
            }
            parent.children.remove(node)
            insert_at = max(0, min(self.new_index, len(parent.children)))
            parent.children.insert(insert_at, node)
            apply_layout(mind_map)
            self._new_positions = {
                n.id: (n.x, n.y) for n in mind_map.all_nodes()
            }
        else:
            # Re-execute (redo): apply cached state directly.
            parent.children.remove(node)
            insert_at = max(0, min(self.new_index, len(parent.children)))
            parent.children.insert(insert_at, node)
            for n in mind_map.all_nodes():
                if n.id in self._new_positions:
                    x, y = self._new_positions[n.id]
                    n.x = x
                    n.y = y

    def undo(self, mind_map: MindMap) -> None:
        parent = mind_map.find(self.parent_id)
        if parent is None:
            return
        node = next(
            (c for c in parent.children if c.id == self.node_id), None
        )
        if node is None:
            return
        parent.children.remove(node)
        insert_at = max(0, min(self.old_index, len(parent.children)))
        parent.children.insert(insert_at, node)
        if self._old_positions:
            for n in mind_map.all_nodes():
                if n.id in self._old_positions:
                    x, y = self._old_positions[n.id]
                    n.x = x
                    n.y = y


@dataclass
class ReorderChildrenCommand(Command):
    """Re-order ALL of a parent's children at once.

    `ReorderNodeCommand` moves one child to one index; a drag in the
    Procedures panel's Steps list hands back a whole permutation, and
    replaying it as a series of single moves would put a pile of
    intermediate states on the undo stack. Ids not present under the
    parent are ignored, and any child the caller left out keeps its
    relative place at the end — a partial list can never drop a step."""
    parent_id: str
    new_order: list
    label: str = "Reorder Steps"
    _old_order: list | None = field(default=None)
    _old_positions: dict[str, tuple[float, float]] | None = field(default=None)

    @staticmethod
    def _apply(parent, order: list) -> None:
        by_id = {c.id: c for c in parent.children}
        kept = [by_id[i] for i in order if i in by_id]
        kept += [c for c in parent.children if c.id not in set(order)]
        parent.children = kept

    def do(self, mind_map: MindMap) -> None:
        from synmind.core.layout import apply_layout

        parent = mind_map.find(self.parent_id)
        if parent is None:
            return
        if self._old_order is None:
            self._old_order = [c.id for c in parent.children]
            self._old_positions = {
                n.id: (n.x, n.y) for n in mind_map.all_nodes()
            }
        self._apply(parent, list(self.new_order))
        apply_layout(mind_map)

    def undo(self, mind_map: MindMap) -> None:
        from synmind.core.layout import apply_layout

        parent = mind_map.find(self.parent_id)
        if parent is None or self._old_order is None:
            return
        self._apply(parent, list(self._old_order))
        if self._old_positions:
            for n in mind_map.all_nodes():
                if n.id in self._old_positions:
                    n.x, n.y = self._old_positions[n.id]
        else:
            apply_layout(mind_map)


@dataclass
class ReparentNodeCommand(Command):
    """Move a node out from under its current parent and into a new parent's
    children list. Runs apply_layout so the moved subtree slots cleanly into
    its new position. Caches old/new positions of the entire tree for cheap
    undo and redo."""
    node_id: str
    old_parent_id: str
    old_index: int
    new_parent_id: str
    new_index: int = -1  # -1 means append
    label: str = "Reparent Node"
    _old_positions: dict[str, tuple[float, float]] | None = field(default=None)
    _new_positions: dict[str, tuple[float, float]] | None = field(default=None)

    def do(self, mind_map: MindMap) -> None:
        from synmind.core.layout import apply_layout

        old_parent = mind_map.find(self.old_parent_id)
        new_parent = mind_map.find(self.new_parent_id)
        if old_parent is None or new_parent is None:
            return
        node = next(
            (c for c in old_parent.children if c.id == self.node_id), None
        )
        if node is None:
            return

        if self._new_positions is None:
            self._old_positions = {
                n.id: (n.x, n.y) for n in mind_map.all_nodes()
            }
            old_parent.children.remove(node)
            insert_at = (
                len(new_parent.children)
                if self.new_index < 0
                else max(0, min(self.new_index, len(new_parent.children)))
            )
            new_parent.children.insert(insert_at, node)
            apply_layout(mind_map)
            self._new_positions = {
                n.id: (n.x, n.y) for n in mind_map.all_nodes()
            }
        else:
            old_parent.children.remove(node)
            insert_at = (
                len(new_parent.children)
                if self.new_index < 0
                else max(0, min(self.new_index, len(new_parent.children)))
            )
            new_parent.children.insert(insert_at, node)
            for n in mind_map.all_nodes():
                if n.id in self._new_positions:
                    n.x, n.y = self._new_positions[n.id]

    def undo(self, mind_map: MindMap) -> None:
        old_parent = mind_map.find(self.old_parent_id)
        new_parent = mind_map.find(self.new_parent_id)
        if old_parent is None or new_parent is None:
            return
        node = next(
            (c for c in new_parent.children if c.id == self.node_id), None
        )
        if node is None:
            return
        new_parent.children.remove(node)
        insert_at = max(0, min(self.old_index, len(old_parent.children)))
        old_parent.children.insert(insert_at, node)
        if self._old_positions:
            for n in mind_map.all_nodes():
                if n.id in self._old_positions:
                    n.x, n.y = self._old_positions[n.id]


# Spaced-repetition interval ladder. Days between reviews; correct answers
# advance one step, wrong answers reset to step 0 (immediate).
REVIEW_INTERVALS_DAYS = [0.0, 1.0, 3.0, 7.0, 14.0, 30.0, 60.0, 120.0]


@dataclass
class SetReviewStateCommand(Command):
    """Set a node's review fields. Used for marking/unmarking and for any
    other state change that needs to be undoable."""
    node_id: str
    old_marked: bool
    old_step: int
    old_due_at: str | None
    new_marked: bool
    new_step: int
    new_due_at: str | None
    label: str = "Update Review"

    def do(self, mind_map: MindMap) -> None:
        node = mind_map.find(self.node_id)
        if node is None:
            return
        node.review_marked = self.new_marked
        node.review_step = self.new_step
        node.review_due_at = self.new_due_at

    def undo(self, mind_map: MindMap) -> None:
        node = mind_map.find(self.node_id)
        if node is None:
            return
        node.review_marked = self.old_marked
        node.review_step = self.old_step
        node.review_due_at = self.old_due_at


@dataclass
class SetExternalLinkCommand(Command):
    """Attach a URL / file path / folder path to a node. Used to make
    double-click on the node open that resource via the OS."""
    node_id: str
    old_link: str | None
    new_link: str | None
    label: str = "Attach Link"

    def do(self, mind_map: MindMap) -> None:
        node = mind_map.find(self.node_id)
        if node is None:
            return
        node.external_link = self.new_link

    def undo(self, mind_map: MindMap) -> None:
        node = mind_map.find(self.node_id)
        if node is None:
            return
        node.external_link = self.old_link


@dataclass
class SetTodoStateCommand(Command):
    """Mark/unmark a node as ToDo, set its due date, and optionally
    attach a recurrence rule. All three fields move atomically so
    undo restores the previous state cleanly."""
    node_id: str
    old_marked: bool
    old_due_at: str | None
    new_marked: bool
    new_due_at: str | None
    # Recurrence rule dicts — None means "one-shot todo" (the
    # default for legacy callers that don't set these). See
    # synmind/core/todo_recurrence.py for the rule schema.
    old_recurrence: dict | None = None
    new_recurrence: dict | None = None
    # Priority bucket — None means "default (MEDIUM)". Stored as
    # the canonical uppercase string when set.
    old_priority: str | None = None
    new_priority: str | None = None
    label: str = "Update ToDo"

    def do(self, mind_map: MindMap) -> None:
        node = mind_map.find(self.node_id)
        if node is None:
            return
        node.todo_marked = self.new_marked
        node.todo_due_at = self.new_due_at
        node.todo_recurrence = (
            dict(self.new_recurrence) if self.new_recurrence else None
        )
        node.todo_priority = self.new_priority

    def undo(self, mind_map: MindMap) -> None:
        node = mind_map.find(self.node_id)
        if node is None:
            return
        node.todo_marked = self.old_marked
        node.todo_due_at = self.old_due_at
        node.todo_recurrence = (
            dict(self.old_recurrence) if self.old_recurrence else None
        )
        node.todo_priority = self.old_priority


@dataclass
class SetTextFormatCommand(Command):
    """Replace a node's per-node text styling (bold/italic/underline/
    strikethrough/font_size/highlight/color). All properties round-trip
    together so a single Ctrl+Z restores the whole style at once."""
    node_id: str
    old_fmt: dict
    new_fmt: dict
    label: str = "Set Text Style"

    def _apply(self, mind_map: MindMap, fmt: dict) -> None:
        node = mind_map.find(self.node_id)
        if node is None:
            return
        node.text_bold = bool(fmt.get("text_bold", False))
        node.text_italic = bool(fmt.get("text_italic", False))
        node.text_underline = bool(fmt.get("text_underline", False))
        node.text_strikethrough = bool(fmt.get("text_strikethrough", False))
        node.text_font_size = fmt.get("text_font_size")
        node.text_highlight = fmt.get("text_highlight")
        node.text_color = fmt.get("text_color")
        # Alignment is the most recent addition — fall back to "center"
        # for legacy command records (e.g. an undo stack from before
        # this field existed) so they don't crash on Ctrl+Z.
        align = fmt.get("text_alignment", "center")
        if align not in ("left", "center", "right"):
            align = "center"
        node.text_alignment = align

    def do(self, mind_map: MindMap) -> None:
        self._apply(mind_map, self.new_fmt)

    def undo(self, mind_map: MindMap) -> None:
        self._apply(mind_map, self.old_fmt)


@dataclass
class SetAttachmentsCommand(Command):
    """Replace a node's attachment-basenames list. Used for both attach
    and remove — both expressed as a full-list swap so undo restores the
    exact prior membership and order."""
    node_id: str
    old_attachments: list[str]
    new_attachments: list[str]
    label: str = "Set Attachments"

    def do(self, mind_map: MindMap) -> None:
        node = mind_map.find(self.node_id)
        if node is None:
            return
        node.attachments = list(self.new_attachments)

    def undo(self, mind_map: MindMap) -> None:
        node = mind_map.find(self.node_id)
        if node is None:
            return
        node.attachments = list(self.old_attachments)


@dataclass
class SetAttachmentsFolderCommand(Command):
    """Change the map-wide attachments folder. Does not move files."""
    old_folder: str | None
    new_folder: str | None
    label: str = "Set Attachments Folder"

    def do(self, mind_map: MindMap) -> None:
        mind_map.attachments_folder = self.new_folder

    def undo(self, mind_map: MindMap) -> None:
        mind_map.attachments_folder = self.old_folder


@dataclass
class SetBookmarksCommand(Command):
    """Replace the map's full bookmark list. Used by Alt+B (add/remove
    one) and by drag-reorder in the bookmark panel — both expressed as a
    full-list swap so the command is uniform and easy to undo."""
    old_ids: list[str]
    new_ids: list[str]
    label: str = "Set Bookmarks"

    def do(self, mind_map: MindMap) -> None:
        mind_map.bookmarked_ids = list(self.new_ids)

    def undo(self, mind_map: MindMap) -> None:
        mind_map.bookmarked_ids = list(self.old_ids)


@dataclass
class SetTagsCommand(Command):
    """Replace a node's tag list. Used for both add and remove operations."""
    node_id: str
    old_tags: list[str]
    new_tags: list[str]
    label: str = "Set Tags"
    _old_updated_at: str | None = field(default=None)
    _new_updated_at: str | None = field(default=None)

    def do(self, mind_map: MindMap) -> None:
        node = mind_map.find(self.node_id)
        if node is None:
            return
        if self._new_updated_at is None:
            self._old_updated_at = node.updated_at
            self._new_updated_at = _now_iso()
        node.tags = list(self.new_tags)
        node.updated_at = self._new_updated_at

    def undo(self, mind_map: MindMap) -> None:
        node = mind_map.find(self.node_id)
        if node is None:
            return
        node.tags = list(self.old_tags)
        if self._old_updated_at is not None:
            node.updated_at = self._old_updated_at


@dataclass
class SetNoteCommand(Command):
    """Replace a node's rich-text note (HTML). Used by the Edit Note dialog."""
    node_id: str
    old_html: str
    new_html: str
    label: str = "Edit Note"
    _old_updated_at: str | None = field(default=None)
    _new_updated_at: str | None = field(default=None)
    _old_note_updated_at: str | None = field(default=None)
    _new_note_updated_at: str | None = field(default=None)

    def do(self, mind_map: MindMap) -> None:
        node = mind_map.find(self.node_id)
        if node is None:
            return
        if self._new_updated_at is None:
            self._old_updated_at = node.updated_at
            self._old_note_updated_at = node.note_updated_at
            ts = _now_iso()
            self._new_updated_at = ts
            self._new_note_updated_at = ts
        node.note_html = self.new_html
        node.updated_at = self._new_updated_at
        node.note_updated_at = self._new_note_updated_at

    def undo(self, mind_map: MindMap) -> None:
        node = mind_map.find(self.node_id)
        if node is None:
            return
        node.note_html = self.old_html
        if self._old_updated_at is not None:
            node.updated_at = self._old_updated_at
        # `_old_note_updated_at` is captured fresh on first do(), so it
        # may still be None — that's correct, it means "no prior note
        # edit existed before this one".
        node.note_updated_at = self._old_note_updated_at


@dataclass
class SetLinkTargetCommand(Command):
    """Set or clear a node's link_target_id (one-click jump target)."""
    node_id: str
    old_target_id: str | None
    new_target_id: str | None
    label: str = "Set Link"
    _old_updated_at: str | None = field(default=None)
    _new_updated_at: str | None = field(default=None)

    def do(self, mind_map: MindMap) -> None:
        node = mind_map.find(self.node_id)
        if node is None:
            return
        if self._new_updated_at is None:
            self._old_updated_at = node.updated_at
            self._new_updated_at = _now_iso()
        node.link_target_id = self.new_target_id
        node.updated_at = self._new_updated_at

    def undo(self, mind_map: MindMap) -> None:
        node = mind_map.find(self.node_id)
        if node is None:
            return
        node.link_target_id = self.old_target_id
        if self._old_updated_at is not None:
            node.updated_at = self._old_updated_at


@dataclass
class SetLayoutStyleCommand(Command):
    """Changes the layout style and re-runs the layout, undoable to old positions."""
    old_style: str
    new_style: str
    label: str = "Change Layout Style"
    _old_positions: dict[str, tuple[float, float]] | None = field(default=None)
    _new_positions: dict[str, tuple[float, float]] | None = field(default=None)

    def do(self, mind_map: MindMap) -> None:
        from synmind.core.layout import apply_layout

        if self._new_positions is None:
            self._old_positions = {n.id: (n.x, n.y) for n in mind_map.all_nodes()}
            mind_map.layout_style = self.new_style
            apply_layout(mind_map)
            self._new_positions = {n.id: (n.x, n.y) for n in mind_map.all_nodes()}
        else:
            mind_map.layout_style = self.new_style
            for n in mind_map.all_nodes():
                if n.id in self._new_positions:
                    n.x, n.y = self._new_positions[n.id]

    def undo(self, mind_map: MindMap) -> None:
        mind_map.layout_style = self.old_style
        if self._old_positions:
            for n in mind_map.all_nodes():
                if n.id in self._old_positions:
                    n.x, n.y = self._old_positions[n.id]


@dataclass
class SetHorizontalLineLengthCommand(Command):
    """Changes the horizontal parent→child gap (the connecting line's
    horizontal span, in horizontal-branching layouts) and re-runs the
    layout, undoable to old positions — same shape as
    SetLayoutStyleCommand."""
    old_length: float
    new_length: float
    label: str = "Change Horizontal Line Length"
    _old_positions: dict[str, tuple[float, float]] | None = field(default=None)
    _new_positions: dict[str, tuple[float, float]] | None = field(default=None)

    def do(self, mind_map: MindMap) -> None:
        from synmind.core.layout import apply_layout

        if self._new_positions is None:
            self._old_positions = {n.id: (n.x, n.y) for n in mind_map.all_nodes()}
            mind_map.horizontal_line_length = self.new_length
            apply_layout(mind_map)
            self._new_positions = {n.id: (n.x, n.y) for n in mind_map.all_nodes()}
        else:
            mind_map.horizontal_line_length = self.new_length
            for n in mind_map.all_nodes():
                if n.id in self._new_positions:
                    n.x, n.y = self._new_positions[n.id]

    def undo(self, mind_map: MindMap) -> None:
        mind_map.horizontal_line_length = self.old_length
        if self._old_positions:
            for n in mind_map.all_nodes():
                if n.id in self._old_positions:
                    n.x, n.y = self._old_positions[n.id]


@dataclass
class SetVisibilityCommand(Command):
    """Bulk-changes `collapsed` state across multiple nodes AND re-runs the layout
    so visible siblings compact together when hidden branches disappear.
    """
    changes: dict[str, bool]
    label: str = "Change Visibility"
    _old_collapsed: dict[str, bool] | None = field(default=None)
    _old_positions: dict[str, tuple[float, float]] | None = field(default=None)
    _new_positions: dict[str, tuple[float, float]] | None = field(default=None)
    # Set True by do() when this command's call ran `apply_layout`. The
    # canvas reads it after history.execute to avoid re-running layout
    # in `_rebuild_scene`'s auto_beautify block — without this hint the
    # same expensive tidy-tree pass ran twice per toggle (once here,
    # once there) which on a 170-node map cost ~1.3 s per pass.
    applied_layout: bool = field(default=False)

    def do(self, mind_map: MindMap) -> None:
        from synmind.core.layout import apply_layout

        if self._old_collapsed is None:
            self._old_collapsed = {}
            for nid in self.changes:
                node = mind_map.find(nid)
                if node is not None:
                    self._old_collapsed[nid] = node.collapsed
        if self._old_positions is None:
            self._old_positions = {n.id: (n.x, n.y) for n in mind_map.all_nodes()}

        for nid, new_state in self.changes.items():
            node = mind_map.find(nid)
            if node is not None:
                node.collapsed = new_state

        if self._new_positions is None:
            apply_layout(mind_map)
            self._new_positions = {n.id: (n.x, n.y) for n in mind_map.all_nodes()}
            self.applied_layout = True
        else:
            for n in mind_map.all_nodes():
                if n.id in self._new_positions:
                    n.x, n.y = self._new_positions[n.id]
            # Cached positions came from a prior apply_layout that the
            # caller already accounted for — the signature stamp will be
            # whatever was current at the time of the original run.
            # Setting True here too is safe: positions and the model
            # structure are consistent, which is the invariant the
            # signature stamp encodes.
            self.applied_layout = True

    def undo(self, mind_map: MindMap) -> None:
        if self._old_collapsed is not None:
            for nid, old_state in self._old_collapsed.items():
                node = mind_map.find(nid)
                if node is not None:
                    node.collapsed = old_state
        if self._old_positions is not None:
            for n in mind_map.all_nodes():
                if n.id in self._old_positions:
                    n.x, n.y = self._old_positions[n.id]


@dataclass
class ConvertToAliasCommand(Command):
    """Turns an existing, already-selected leaf node into an alias of
    `master_id` — the Shift+Alt+A / right-click "Make This Node an
    Alias of…" path (see `MapCanvas.convert_node_to_alias_of`).

    Deliberately NOT used for the inline-fresh-node variant (typing a
    brand-new node's text, then Shift+Alt+A to make IT an alias): that
    path stays a direct mutation on purpose, so the single
    `AddNodeCommand` already on the stack for the new node remains the
    only undo step and removes it entirely — pushing a second command
    here would make that need two Ctrl+Z presses instead of one.
    """
    node_id: str
    master_id: str
    old_text: str
    old_text_html: str | None
    old_alias_of: str | None
    new_text: str
    label: str = "Make Alias"

    def do(self, mind_map: MindMap) -> None:
        node = mind_map.find(self.node_id)
        master = mind_map.find(self.master_id)
        if node is None or master is None:
            return
        node.text = self.new_text
        node.text_html = None
        node.alias_of = self.master_id
        mind_map.invalidate_lookup_cache()

    def undo(self, mind_map: MindMap) -> None:
        node = mind_map.find(self.node_id)
        if node is None:
            return
        node.text = self.old_text
        node.text_html = self.old_text_html
        node.alias_of = self.old_alias_of
        mind_map.invalidate_lookup_cache()


@dataclass
class CompositeCommand(Command):
    """Run a list of sub-commands as one undoable unit. `do` applies them
    in order; `undo` reverses them in the opposite order so the map lands
    back exactly where it started. Used for multi-node delete (Ctrl-click
    several nodes → Delete) so a single Ctrl+Z restores them all.

    `applied_layout` surfaces True when ANY sub-command re-ran the layout,
    so the canvas skips the redundant post-command relayout pass.
    """
    commands: list = field(default_factory=list)
    label: str = "Multiple Changes"

    def do(self, mind_map: MindMap) -> None:
        for cmd in self.commands:
            cmd.do(mind_map)

    def undo(self, mind_map: MindMap) -> None:
        for cmd in reversed(self.commands):
            cmd.undo(mind_map)

    @property
    def applied_layout(self) -> bool:
        return any(getattr(c, "applied_layout", False) for c in self.commands)
