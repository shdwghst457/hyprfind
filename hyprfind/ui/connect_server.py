"""Connect to Server dialog.

Mounting blocks on the network, so it runs on a worker thread; a dead host would
otherwise freeze the window for the length of the TCP timeout.
"""

from __future__ import annotations

from PyQt6.QtCore import QObject, Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from hyprfind.core.servers import (
    ServerStore,
    ServerTarget,
    mount_server,
    normalize_server_uri,
    parse_server_uri,
)


class _MountWorker(QObject):
    finished = pyqtSignal(object, object)  # mount_point, error

    def __init__(
        self,
        target: ServerTarget,
        user: str,
        domain: str,
        password: str,
        anonymous: bool,
    ) -> None:
        super().__init__()
        self._target = target
        self._user = user
        self._domain = domain
        self._password = password
        self._anonymous = anonymous

    def run(self) -> None:
        point, error = mount_server(
            self._target,
            user=self._user,
            domain=self._domain,
            password=self._password,
            anonymous=self._anonymous,
        )
        self.finished.emit(point, error)


class ConnectServerDialog(QDialog):
    """Collects a share address plus credentials, then mounts it."""

    def __init__(self, store: ServerStore, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Connect to Server")
        self.setModal(True)
        self.setMinimumWidth(460)

        self._store = store
        self.mount_point: str | None = None
        self._thread: QThread | None = None
        self._worker: _MountWorker | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)

        address_row = QHBoxLayout()
        self._address = QLineEdit()
        self._address.setPlaceholderText("smb://server/share")
        self._address.textChanged.connect(self._update_enabled)
        self._address.returnPressed.connect(self._connect)
        address_row.addWidget(QLabel("Server:"))
        address_row.addWidget(self._address, 1)
        layout.addLayout(address_row)

        hint = QLabel(
            "Supports smb://, sftp://, ftp://, nfs://, dav://. "
            "A bare host/share is treated as SMB."
        )
        hint.setObjectName("transferDetail")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        credentials = QGroupBox("Credentials")
        form = QFormLayout(credentials)
        self._anonymous = QCheckBox("Connect as guest")
        self._anonymous.toggled.connect(self._update_enabled)
        form.addRow(self._anonymous)
        self._user = QLineEdit()
        form.addRow("Name:", self._user)
        self._domain = QLineEdit()
        self._domain.setPlaceholderText("WORKGROUP")
        form.addRow("Domain:", self._domain)
        self._password = QLineEdit()
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Password:", self._password)
        layout.addWidget(credentials)

        recent_label = QLabel("Recent Servers")
        layout.addWidget(recent_label)
        self._recent = QListWidget()
        self._recent.setMaximumHeight(120)
        self._recent.itemActivated.connect(self._use_recent)
        self._recent.currentItemChanged.connect(self._on_recent_selected)
        layout.addWidget(self._recent)

        recent_buttons = QHBoxLayout()
        recent_buttons.addStretch(1)
        self._remove_button = QPushButton("Remove")
        self._remove_button.setEnabled(False)
        self._remove_button.clicked.connect(self._remove_recent)
        recent_buttons.addWidget(self._remove_button)
        layout.addLayout(recent_buttons)

        self._status = QLabel("")
        self._status.setObjectName("transferDetail")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel
        )
        self._connect_button = self._buttons.addButton(
            "Connect", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self._connect_button.clicked.connect(self._connect)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)

        self._reload_recent()
        self._update_enabled()

    # -------------------------------------------------------------------- state

    def _reload_recent(self) -> None:
        self._recent.clear()
        for uri in self._store.all():
            target = parse_server_uri(uri)
            item = QListWidgetItem(target.display_name if target else uri)
            item.setData(Qt.ItemDataRole.UserRole, uri)
            item.setToolTip(uri)
            self._recent.addItem(item)

    def _on_recent_selected(self, current, _previous) -> None:
        self._remove_button.setEnabled(current is not None)

    def _use_recent(self, item: QListWidgetItem) -> None:
        self._address.setText(item.data(Qt.ItemDataRole.UserRole))
        self._connect()

    def _remove_recent(self) -> None:
        item = self._recent.currentItem()
        if item is None:
            return
        self._store.remove(item.data(Qt.ItemDataRole.UserRole))
        self._reload_recent()

    def _update_enabled(self) -> None:
        anonymous = self._anonymous.isChecked()
        for widget in (self._user, self._domain, self._password):
            widget.setEnabled(not anonymous)
        self._connect_button.setEnabled(
            bool(normalize_server_uri(self._address.text())) and self._thread is None
        )

    # ------------------------------------------------------------------ mounting

    def _connect(self) -> None:
        if self._thread is not None:
            return
        target = parse_server_uri(self._address.text())
        if target is None:
            QMessageBox.warning(
                self, "Connect to Server", "Enter an address like smb://server/share."
            )
            return

        self._status.setText(f"Connecting to {target.display_name}…")
        self._connect_button.setEnabled(False)

        self._thread = QThread(self)
        self._worker = _MountWorker(
            target,
            self._user.text().strip(),
            self._domain.text().strip(),
            self._password.text(),
            self._anonymous.isChecked(),
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(lambda point, error: self._on_mounted(target, point, error))
        self._thread.start()

    def _on_mounted(self, target: ServerTarget, point, error) -> None:
        self._join_thread()
        if error:
            self._status.setText(error)
            self._update_enabled()
            return
        self.mount_point = point
        self._store.push(target.uri)
        self.accept()

    def _join_thread(self) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(3000)
        self._thread = None
        self._worker = None

    def reject(self) -> None:
        # The gio call cannot be interrupted, so wait for it rather than
        # tearing the thread down underneath it.
        if self._thread is not None:
            self._status.setText("Waiting for the connection attempt to finish…")
            self._join_thread()
        super().reject()

    def closeEvent(self, event) -> None:
        self._join_thread()
        super().closeEvent(event)
