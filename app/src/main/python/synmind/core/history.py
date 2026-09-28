"""Undo/redo history. Drives a command pipeline against a single MindMap."""
from __future__ import annotations

from synmind.core.commands import Command
from synmind.core.model import MindMap


class History:
    def __init__(self, mind_map: MindMap) -> None:
        self.mind_map = mind_map
        self._undo: list[Command] = []
        self._redo: list[Command] = []

    def execute(self, command: Command) -> Command:
        # Any command may change tree structure / links / aliases, so drop
        # the model's O(1) lookup indexes before it runs — reads during the
        # mutation then use a correct fresh scan, and the next scene rebuild
        # repopulates the cache.
        self.mind_map.invalidate_lookup_cache()
        command.do(self.mind_map)
        self._undo.append(command)
        self._redo.clear()
        return command

    def push_already_applied(self, command: Command) -> None:
        """For commands whose effect has already happened (e.g. a drag)."""
        self.mind_map.invalidate_lookup_cache()
        self._undo.append(command)
        self._redo.clear()

    def undo(self) -> Command | None:
        if not self._undo:
            return None
        self.mind_map.invalidate_lookup_cache()
        cmd = self._undo.pop()
        cmd.undo(self.mind_map)
        self._redo.append(cmd)
        return cmd

    def redo(self) -> Command | None:
        if not self._redo:
            return None
        self.mind_map.invalidate_lookup_cache()
        cmd = self._redo.pop()
        cmd.do(self.mind_map)
        self._undo.append(cmd)
        return cmd

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)
