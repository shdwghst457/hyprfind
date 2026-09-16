"""Share picker for a connected server.

Finder lists a server's shares and greys out the ones already mounted; this is
the same idea. Mounting blocks on the network, so it runs on a worker thread.
"""

from __future__ import annotations

from PyQt6.QtCore import QObject, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from hyprfind.core.servers import (
    ServerTarget,
    mount_server,
    mounted_share_names,
    parse_server_uri,
)

# Matches the disabled text colour used throughout dark.qss.
DISABLED_TEXT = "#5a5a5e"


class _MountWorker(QObject):
    """Mounts each chosen share in turn, reporting as it goes."""

    progress = pyqtSignal(str)
    finished = pyqtSignal(object, object)  # first mount point, error

    def __init__(
        self,
        host: str,
        scheme: str,
        shares: list[str],
        user: str,
        domain: str,
        password: str,
        anonymous: bool,
        remember: bool = True,
    ) -> None:
        super().__init__()
        self._host = host
        self._scheme = scheme
        self._shares = shares
        self._user = user
        self._domain = domain
        self._password = password
        self._anonymous = anonymous
        self._remember = remember

    def run(self) -> None:
        first: str | None = None
        errors: list[str] = []
        for share in self._shares:
            self.progress.emit(f"Mounting {share}…")
            target = parse_server_uri(f"{self._scheme}://{self._host}/{share}")
            if target is None:
                errors.append(f"{share}: bad name")
                continue
            point, error = mount_server(
                target,
                user=self._user,
                domain=self._domain,
                password=self._password,
                anonymous=self._anonymous,
                remember=self._remember,
            )
            if error:
                errors.append(f"{share}: {error}")
            elif first is None:
                first = point
        # Partial success still navigates; the message names what failed.
        self.finished.emit(first, "; ".join(errors) or None)


class SharePickerDialog(QDialog):
    """Lets the user pick which of a server's shares to mount."""

    def __init__(
        self,
        target: ServerTarget,
        shares: list[str],
        *,
        user: str = "",
        domain: str = "",
        password: str = "",
        anonymous: bool = False,
        remember: bool = True,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Shares on {target.host}")
        self.setModal(True)
        self.setMinimumWidth(380)

        self._target = target
        self._user = user
        self._domain = domain
        self._password = password
        self._anonymous = anonymous
        self._remember = remember
        self.mount_point: str | None = None
        self.partial_error: str | None = None
        self._thread: QThread | None = None
        self._worker: _MountWorker | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        heading = QLabel(f"Select the shares you want to mount on {target.host}:")
        heading.setWordWrap(True)
        layout.addWidget(heading)

        self._list = QListWidget()
        self._list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self._list.itemActivated.connect(self._on_activated)
        self._list.itemSelectionChanged.connect(self._update_enabled)
        layout.addWidget(self._list, 1)

        self._status = QLabel("")
        self._status.setObjectName("transferDetail")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        self._buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self._mount_button = self._buttons.addButton(
            "Mount", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self._mount_button.clicked.connect(self._mount_selected)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)

        self._populate(shares)
        self._update_enabled()

    # ------------------------------------------------------------------ listing

    def _populate(self, shares: list[str]) -> None:
        already = mounted_share_names(self._target.host)
        self._list.clear()
        first_selectable: QListWidgetItem | None = None
        for share in shares:
            mounted = share.casefold() in already
            label = f"{share} — already mounted" if mounted else share
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, share)
            if mounted:
                # Greyed out and unselectable, like Finder. NoItemFlags blocks
                # selection but does not dim the text on its own, so set the
                # theme's disabled colour explicitly.
                item.setFlags(Qt.ItemFlag.NoItemFlags)
                item.setForeground(QBrush(QColor(DISABLED_TEXT)))
            elif first_selectable is None:
                first_selectable = item
            self._list.addItem(item)

        if first_selectable is not None:
            first_selectable.setSelected(True)
            self._list.setCurrentItem(first_selectable)
        elif shares:
            self._status.setText("Every share here is already mounted.")

    def selected_shares(self) -> list[str]:
        return [
            item.data(Qt.ItemDataRole.UserRole)
            for item in self._list.selectedItems()
        ]

    def _update_enabled(self) -> None:
        self._mount_button.setEnabled(
            bool(self.selected_shares()) and self._thread is None
        )

    # ----------------------------------------------------------------- mounting

    def _on_activated(self, item: QListWidgetItem) -> None:
        if item.flags() != Qt.ItemFlag.NoItemFlags:
            self._mount_selected()

    def _mount_selected(self) -> None:
        shares = self.selected_shares()
        if not shares or self._thread is not None:
            return

        self._mount_button.setEnabled(False)
        self._status.setText("Mounting…")

        self._thread = QThread(self)
        self._worker = _MountWorker(
            self._target.host,
            self._target.scheme,
            shares,
            self._user,
            self._domain,
            self._password,
            self._anonymous,
            self._remember,
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._status.setText)
        self._worker.finished.connect(self._on_mounted)
        self._thread.start()

    def _on_mounted(self, point, error) -> None:
        self._join_thread()
        if point is None:
            self._status.setText(error or "Could not mount the share")
            self._update_enabled()
            return
        self.mount_point = point
        if error:
            # Some mounted, some did not; let the caller surface the detail.
            self.partial_error = error
        self.accept()

    def _join_thread(self) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(3000)
        self._thread = None
        self._worker = None

    def reject(self) -> None:
        # gio cannot be interrupted, so wait rather than tearing the thread
        # down underneath it.
        if self._thread is not None:
            self._status.setText("Waiting for the mount to finish…")
            self._join_thread()
        super().reject()

    def closeEvent(self, event) -> None:
        self._join_thread()
        super().closeEvent(event)
