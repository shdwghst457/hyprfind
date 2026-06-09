"""Single browser tab with its own history and refresh watcher."""

from __future__ import annotations

import os

from PyQt6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget

from hyprfind.core.history import HistoryStack
from hyprfind.core.model import HyprFileSystemModel
from hyprfind.core.mounts import MountService
from hyprfind.core.refresh import DirectoryRefreshService
from hyprfind.ui.view_stack import ViewStack
from hyprfind.core.trash import ensure_trash, is_trash_directory
from hyprfind.utils.paths import expand_path


class BrowserTab(QWidget):
    def __init__(
        self,
        model: HyprFileSystemModel,
        mount_service: MountService,
        initial_path: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._model = model
        self._mount_service = mount_service
        self.history = HistoryStack()
        self.refresh_service = DirectoryRefreshService(mount_service, parent=self)
        self._current_path = ""

        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.view_stack = ViewStack(model)
        self.file_list = self.view_stack.file_list
        layout.addWidget(self.view_stack, 1)

        self.navigate_to(initial_path, push_history=True)

    @property
    def current_path(self) -> str:
        return self._current_path

    def tab_label(self) -> str:
        if not self._current_path:
            return "Tab"
        name = os.path.basename(self._current_path.rstrip("/"))
        return name or self._current_path

    def navigate_to(self, path: str, *, push_history: bool = False) -> bool:
        normalized = expand_path(path)
        if is_trash_directory(normalized):
            ensure_trash()
        if not os.path.isdir(normalized):
            return False

        self._current_path = normalized
        self.view_stack.set_current_directory(normalized)
        self.refresh_service.watch(normalized)

        if push_history:
            self.history.push(normalized)
        return True

    def stop_watching(self) -> None:
        self.refresh_service.stop()
