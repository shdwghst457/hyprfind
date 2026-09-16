"""Connect to Server dialog.

Mounting blocks on the network, so it runs on a worker thread; a dead host would
otherwise freeze the window for the length of the TCP timeout.
"""

from __future__ import annotations

from PyQt6.QtCore import QObject, Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
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
    PROTOCOLS,
    ServerStore,
    ServerTarget,
    build_server_uri,
    list_shares,
    missing_backend,
    mount_server,
    parse_server_uri,
    protocol_for,
    split_server_uri,
)
from hyprfind.ui.share_picker import SharePickerDialog


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


class _ListWorker(QObject):
    """Asks the server which shares it offers."""

    finished = pyqtSignal(object, object)  # shares, error

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
        shares, error = list_shares(
            self._target,
            user=self._user,
            domain=self._domain,
            password=self._password,
            anonymous=self._anonymous,
        )
        self.finished.emit(shares, error)


class ConnectServerDialog(QDialog):
    """Collects a share address plus credentials, then mounts it."""

    def __init__(self, store: ServerStore, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Connect to Server")
        self.setModal(True)
        self.setMinimumWidth(460)

        self._store = store
        self.mount_point: str | None = None
        self.partial_error: str | None = None
        self._thread: QThread | None = None
        self._worker: _MountWorker | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)

        address_row = QHBoxLayout()
        self._protocol = QComboBox()
        for protocol in PROTOCOLS:
            self._protocol.addItem(protocol.label, protocol.scheme)
        self._protocol.currentIndexChanged.connect(self._on_protocol_changed)
        self._address = QLineEdit()
        self._address.textChanged.connect(self._on_address_changed)
        self._address.returnPressed.connect(self._connect)
        address_row.addWidget(QLabel("Protocol:"))
        address_row.addWidget(self._protocol)
        address_row.addWidget(QLabel("Server:"))
        address_row.addWidget(self._address, 1)
        layout.addLayout(address_row)

        self._hint = QLabel("")
        self._hint.setObjectName("transferDetail")
        self._hint.setWordWrap(True)
        layout.addWidget(self._hint)

        self._credentials = QGroupBox("Credentials")
        form = QFormLayout(self._credentials)
        self._form = form
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
        layout.addWidget(self._credentials)

        recent_label = QLabel("Recent Servers")
        layout.addWidget(recent_label)
        self._recent = QListWidget()
        self._recent.setMinimumHeight(96)
        self._recent.itemActivated.connect(self._use_recent)
        self._recent.currentItemChanged.connect(self._on_recent_selected)
        # Let the list take the slack so hiding the credentials box for NFS
        # does not leave a hole in the middle of the dialog.
        layout.addWidget(self._recent, 1)

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
        # Setting the full URI lets _on_address_changed split out the protocol.
        self._address.setText(item.data(Qt.ItemDataRole.UserRole))
        self._connect()

    def _remove_recent(self) -> None:
        item = self._recent.currentItem()
        if item is None:
            return
        self._store.remove(item.data(Qt.ItemDataRole.UserRole))
        self._reload_recent()

    def _current_protocol(self):
        return protocol_for(self._protocol.currentData())

    def _current_uri(self) -> str:
        return build_server_uri(self._protocol.currentData(), self._address.text())

    def _on_protocol_changed(self) -> None:
        self._update_enabled()

    def _on_address_changed(self, text: str) -> None:
        """Let a pasted URI drive the protocol menu instead of fighting it."""
        if "://" in text or text.startswith("\\\\"):
            scheme, location = split_server_uri(text)
            index = self._protocol.findData(scheme)
            if index >= 0:
                self._protocol.blockSignals(True)
                self._protocol.setCurrentIndex(index)
                self._protocol.blockSignals(False)
            self._address.blockSignals(True)
            self._address.setText(location)
            self._address.blockSignals(False)
        self._update_enabled()

    def _set_row_visible(self, widget, visible: bool) -> None:
        if hasattr(self._form, "setRowVisible"):
            self._form.setRowVisible(widget, visible)
            return
        widget.setVisible(visible)
        label = self._form.labelForField(widget)
        if label is not None:
            label.setVisible(visible)

    def _update_enabled(self) -> None:
        protocol = self._current_protocol()
        self._address.setPlaceholderText(protocol.placeholder)

        # Domain is a Windows concept, so it only belongs to SMB; NFS
        # authenticates by host and takes no credentials at all.
        self._credentials.setVisible(protocol.credentials)
        self._set_row_visible(self._domain, protocol.domain)

        anonymous = self._anonymous.isChecked()
        for widget in (self._user, self._domain, self._password):
            widget.setEnabled(not anonymous)

        uri = self._current_uri()
        warning = missing_backend(protocol.scheme)
        target = parse_server_uri(uri) if uri else None
        if warning:
            self._hint.setText(warning)
        elif target is not None and self._will_browse(protocol, target):
            self._hint.setText(f"Will list the shares on {target.host}")
        elif uri:
            self._hint.setText(f"Will connect to {uri}")
        else:
            self._hint.setText(f"Enter a {protocol.label} address.")

        self._connect_button.setEnabled(bool(uri) and self._thread is None)

    @staticmethod
    def _will_browse(protocol, target: ServerTarget) -> bool:
        """A bare host on a browsable protocol means "show me the shares"."""
        return protocol.browsable and not target.share

    # ------------------------------------------------------------------ mounting

    def _connect(self) -> None:
        if self._thread is not None:
            return
        protocol = self._current_protocol()
        target = parse_server_uri(self._current_uri())
        if target is None:
            QMessageBox.warning(
                self,
                "Connect to Server",
                f"Enter a {protocol.label} address, for example "
                f"{protocol.placeholder}.",
            )
            return

        self._connect_button.setEnabled(False)
        credentials = (
            self._user.text().strip(),
            self._domain.text().strip() if protocol.domain else "",
            self._password.text(),
            self._anonymous.isChecked(),
        )

        # No share named on a browsable protocol: ask the server what it has
        # and let the user choose, rather than requiring them to guess.
        if self._will_browse(protocol, target):
            self._status.setText(f"Listing shares on {target.host}…")
            self._thread = QThread(self)
            self._worker = _ListWorker(target, *credentials)
            self._worker.moveToThread(self._thread)
            self._thread.started.connect(self._worker.run)
            self._worker.finished.connect(
                lambda shares, error: self._on_listed(target, shares, error)
            )
            self._thread.start()
            return

        self._status.setText(f"Connecting to {target.display_name}…")
        self._thread = QThread(self)
        self._worker = _MountWorker(target, *credentials)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(
            lambda point, error: self._on_mounted(target, point, error)
        )
        self._thread.start()

    def _on_listed(self, target: ServerTarget, shares, error) -> None:
        self._join_thread()
        if error:
            self._status.setText("" if error == self._hint.text() else error)
            self._update_enabled()
            return
        if not shares:
            self._status.setText(f"{target.host} offers no shares.")
            self._update_enabled()
            return

        protocol = self._current_protocol()
        picker = SharePickerDialog(
            target,
            shares,
            user=self._user.text().strip(),
            domain=self._domain.text().strip() if protocol.domain else "",
            password=self._password.text(),
            anonymous=self._anonymous.isChecked(),
            parent=self,
        )
        if picker.exec() != QDialog.DialogCode.Accepted:
            self._status.setText("")
            self._update_enabled()
            return

        self.mount_point = picker.mount_point
        # Some shares can mount while others fail; say so rather than looking
        # like everything worked.
        self.partial_error = picker.partial_error
        # Remember the host, so next time the share list is one click away.
        self._store.push(target.uri)
        self.accept()

    def _on_mounted(self, target: ServerTarget, point, error) -> None:
        self._join_thread()
        if error:
            # A missing backend is already spelled out in the hint above the
            # form, so repeating it here would print the same paragraph twice.
            self._status.setText("" if error == self._hint.text() else error)
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
