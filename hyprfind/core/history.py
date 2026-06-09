"""Back/forward navigation history."""

from __future__ import annotations


class HistoryStack:
    def __init__(self) -> None:
        self._stack: list[str] = []
        self._index = -1

    @property
    def current(self) -> str | None:
        if 0 <= self._index < len(self._stack):
            return self._stack[self._index]
        return None

    def push(self, path: str) -> None:
        if self.current == path:
            return
        if self._index < len(self._stack) - 1:
            self._stack = self._stack[: self._index + 1]
        self._stack.append(path)
        self._index = len(self._stack) - 1

    def can_back(self) -> bool:
        return self._index > 0

    def can_forward(self) -> bool:
        return 0 <= self._index < len(self._stack) - 1

    def back(self) -> str | None:
        if not self.can_back():
            return None
        self._index -= 1
        return self.current

    def forward(self) -> str | None:
        if not self.can_forward():
            return None
        self._index += 1
        return self.current
