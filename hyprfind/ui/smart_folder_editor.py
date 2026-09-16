"""Editor for smart folders (saved searches)."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from hyprfind.core.search import SCOPE_EVERYWHERE, SCOPE_HERE
from hyprfind.core.smart_folders import SmartFolder, SmartFolderStore


class SmartFolderEditor(QDialog):
    """Add, edit, reorder, and delete saved searches."""

    def __init__(self, store: SmartFolderStore, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Smart Folders")
        self.setModal(True)
        self.setMinimumSize(560, 420)

        self._store = store
        # Edited in a copy so Cancel really discards everything.
        self._folders: list[SmartFolder] = store.all()
        self._loading = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        left = QVBoxLayout()
        left.setSpacing(6)
        self._list = QListWidget()
        self._list.currentRowChanged.connect(self._on_row_changed)
        left.addWidget(self._list, 1)

        buttons = QHBoxLayout()
        for label, slot in (
            ("+", self._add),
            ("−", self._remove),
            ("↑", lambda: self._move(-1)),
            ("↓", lambda: self._move(1)),
        ):
            button = QPushButton(label)
            button.setFixedWidth(32)
            button.clicked.connect(slot)
            buttons.addWidget(button)
        buttons.addStretch(1)
        left.addLayout(buttons)
        layout.addLayout(left, 1)

        self._details = QGroupBox("Search")
        form = QFormLayout(self._details)
        self._name = QLineEdit()
        self._name.textChanged.connect(self._apply_edits)
        form.addRow("Name:", self._name)

        self._query = QLineEdit()
        self._query.setPlaceholderText("report  or  *.pdf")
        self._query.textChanged.connect(self._apply_edits)
        form.addRow("Matches:", self._query)

        self._scope = QComboBox()
        self._scope.addItem("Home", SCOPE_EVERYWHERE)
        self._scope.addItem("Folder being browsed", SCOPE_HERE)
        self._scope.currentIndexChanged.connect(self._apply_edits)
        form.addRow("Search in:", self._scope)

        root_row = QHBoxLayout()
        self._root = QLineEdit()
        self._root.setPlaceholderText("(use the scope above)")
        self._root.textChanged.connect(self._apply_edits)
        root_row.addWidget(self._root, 1)
        browse = QPushButton("Choose…")
        browse.clicked.connect(self._choose_root)
        root_row.addWidget(browse)
        form.addRow("Pinned folder:", root_row)

        self._hidden = QCheckBox("Include hidden files")
        self._hidden.toggled.connect(self._apply_edits)
        form.addRow(self._hidden)

        self._dirs_only = QCheckBox("Folders only")
        self._dirs_only.toggled.connect(self._apply_edits)
        form.addRow(self._dirs_only)

        self._summary = QLabel("")
        self._summary.setObjectName("transferDetail")
        self._summary.setWordWrap(True)
        form.addRow(self._summary)

        right = QVBoxLayout()
        right.addWidget(self._details, 1)
        box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        box.accepted.connect(self._save)
        box.rejected.connect(self.reject)
        right.addWidget(box)
        layout.addLayout(right, 2)

        self._reload_list()
        if self._folders:
            self._list.setCurrentRow(0)
        else:
            self._set_details_enabled(False)

    # -------------------------------------------------------------------- helpers

    def _reload_list(self, select: int | None = None) -> None:
        self._loading = True
        self._list.clear()
        for folder in self._folders:
            item = QListWidgetItem(folder.name)
            item.setToolTip(folder.describe())
            self._list.addItem(item)
        self._loading = False
        if select is not None and 0 <= select < len(self._folders):
            self._list.setCurrentRow(select)

    def _set_details_enabled(self, enabled: bool) -> None:
        self._details.setEnabled(enabled)

    def _current(self) -> SmartFolder | None:
        row = self._list.currentRow()
        if 0 <= row < len(self._folders):
            return self._folders[row]
        return None

    def _on_row_changed(self, row: int) -> None:
        folder = self._folders[row] if 0 <= row < len(self._folders) else None
        self._set_details_enabled(folder is not None)
        if folder is None:
            return

        # Populate without echoing every change back into the model.
        self._loading = True
        self._name.setText(folder.name)
        self._query.setText(folder.query)
        index = self._scope.findData(folder.scope)
        self._scope.setCurrentIndex(max(0, index))
        self._root.setText(folder.root)
        self._hidden.setChecked(folder.include_hidden)
        self._dirs_only.setChecked(folder.directories_only)
        self._loading = False
        self._summary.setText(folder.describe())

    def _apply_edits(self) -> None:
        if self._loading:
            return
        folder = self._current()
        if folder is None:
            return
        folder.name = self._name.text().strip() or "Untitled"
        folder.query = self._query.text()
        folder.scope = self._scope.currentData() or SCOPE_EVERYWHERE
        folder.root = self._root.text().strip()
        folder.include_hidden = self._hidden.isChecked()
        folder.directories_only = self._dirs_only.isChecked()

        row = self._list.currentRow()
        item = self._list.item(row)
        if item is not None:
            item.setText(folder.name)
            item.setToolTip(folder.describe())
        self._summary.setText(folder.describe())

    def _choose_root(self) -> None:
        start = self._root.text().strip() or ""
        chosen = QFileDialog.getExistingDirectory(self, "Choose Folder", start)
        if chosen:
            self._root.setText(chosen)

    # -------------------------------------------------------------------- actions

    def _add(self) -> None:
        self._folders.append(
            SmartFolder(name="New Smart Folder", query="", scope=SCOPE_EVERYWHERE)
        )
        self._reload_list(select=len(self._folders) - 1)
        self._name.setFocus()
        self._name.selectAll()

    def _remove(self) -> None:
        row = self._list.currentRow()
        if not 0 <= row < len(self._folders):
            return
        del self._folders[row]
        self._reload_list(select=min(row, len(self._folders) - 1))
        if not self._folders:
            self._set_details_enabled(False)

    def _move(self, offset: int) -> None:
        row = self._list.currentRow()
        target = row + offset
        if not (0 <= row < len(self._folders)) or not (
            0 <= target < len(self._folders)
        ):
            return
        self._folders.insert(target, self._folders.pop(row))
        self._reload_list(select=target)

    def _save(self) -> None:
        # Entries with no query would match everything, so drop them.
        keep = [f for f in self._folders if f.query.strip()]
        self._store.replace_all(keep)
        self.accept()
