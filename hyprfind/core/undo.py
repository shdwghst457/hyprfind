"""Undo/redo command stack for file operations."""

from __future__ import annotations

import os
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from hyprfind.core.trash import move_to_trash, restore_from_trash


class Command(ABC):
    @abstractmethod
    def undo(self) -> bool:
        pass

    @abstractmethod
    def redo(self) -> bool:
        pass

    @abstractmethod
    def description(self) -> str:
        pass


@dataclass
class TrashCommand(Command):
    """Undo trash by restoring; redo re-trashes."""

    trashed: list[tuple[str, str]] = field(default_factory=list)

    def undo(self) -> bool:
        ok = True
        for trash_path, _original in reversed(self.trashed):
            if restore_from_trash(trash_path) is None:
                ok = False
        return ok

    def redo(self) -> bool:
        restored_paths = [orig for _t, orig in self.trashed]
        self.trashed.clear()
        for path in restored_paths:
            if os.path.lexists(path):
                result = move_to_trash(path)
                if result:
                    self.trashed.append(result)
        return bool(self.trashed)

    def description(self) -> str:
        n = len(self.trashed)
        return f"Move {n} item(s) to Trash"


@dataclass
class MoveCommand(Command):
    pairs: list[tuple[str, str]] = field(default_factory=list)

    def undo(self) -> bool:
        ok = True
        for dest, src in reversed(self.pairs):
            if os.path.lexists(dest):
                try:
                    if os.path.dirname(src):
                        os.makedirs(os.path.dirname(src), exist_ok=True)
                    shutil.move(dest, src)
                except OSError:
                    ok = False
        return ok

    def redo(self) -> bool:
        ok = True
        for src, dest in [(s, d) for d, s in self.pairs]:
            if os.path.lexists(src):
                try:
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    shutil.move(src, dest)
                except OSError:
                    ok = False
        return ok

    def description(self) -> str:
        return f"Move {len(self.pairs)} item(s)"


@dataclass
class MkdirCommand(Command):
    path: str = ""

    def undo(self) -> bool:
        if os.path.isdir(self.path):
            try:
                os.rmdir(self.path)
                return True
            except OSError:
                return False
        return False

    def redo(self) -> bool:
        try:
            os.mkdir(self.path)
            return True
        except OSError:
            return False

    def description(self) -> str:
        return "New Folder"


class UndoStack:
    MAX_DEPTH = 50

    def __init__(self) -> None:
        self._undo: list[Command] = []
        self._redo: list[Command] = []
        self._listeners: list = []

    def push(self, command: Command) -> None:
        self._undo.append(command)
        if len(self._undo) > self.MAX_DEPTH:
            self._undo.pop(0)
        self._redo.clear()
        self._notify()

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self) -> str | None:
        if not self._undo:
            return None
        cmd = self._undo.pop()
        if cmd.undo():
            self._redo.append(cmd)
            self._notify()
            return cmd.description()
        self._undo.append(cmd)
        return None

    def redo(self) -> str | None:
        if not self._redo:
            return None
        cmd = self._redo.pop()
        if cmd.redo():
            self._undo.append(cmd)
            self._notify()
            return cmd.description()
        self._redo.append(cmd)
        return None

    def add_listener(self, callback) -> None:
        self._listeners.append(callback)

    def _notify(self) -> None:
        for cb in self._listeners:
            cb()
