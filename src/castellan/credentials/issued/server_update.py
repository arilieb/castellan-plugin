# -*- encoding: utf-8 -*-
"""Dialog for prompting user to push local revocation/key state changes to the Castellan server."""

from typing import TYPE_CHECKING

import qasync
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel
from keri import help
from locksmith.ui.toolkit.widgets import LocksmithDialog, LocksmithButton, LocksmithInvertedButton

from ...core import remoting

if TYPE_CHECKING:
    from locksmith.ui.vault.page import VaultPage

logger = help.ogler.getLogger(__name__)


class ServerUpdateDialog(LocksmithDialog):
    """
    Dialog for prompting the user to push local state to the Castellan server.

    Handles two related out-of-sync conditions:
    - A credential was revoked locally but the server still reports it as issued
      (pass `revoked_credential`). Revoking a credential anchors a new event into
      the issuer's KEL, so this also re-checks/pushes the issuer's key state.
    - An identifier's local key state is simply ahead of the server's copy, with
      no revocation involved (`revoked_credential=None`).
    """

    def __init__(
        self,
        app,
        issuer_name: str,
        issuer_aid: str,
        local_sn: int,
        remote_sn: int,
        revoked_credential: dict | None = None,
        parent: "VaultPage | None" = None,
    ):
        """Initialize the server update dialog.

        Args:
            issuer_name: Human-readable name of the issuer identifier
            issuer_aid: AID of the issuer identifier
            local_sn: Local sequence number (current key state)
            remote_sn: Remote sequence number (server's key state)
            revoked_credential: Optional dict with 'said' and 'schema_title' for a
                credential that was revoked locally but not yet on the server
            parent: Parent VaultPage
        """

        self.app = app
        self.issuer_name = issuer_name
        self.issuer_aid = issuer_aid
        self.local_sn = local_sn
        self.remote_sn = remote_sn
        self.revoked_credential = revoked_credential

        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(12)

        if revoked_credential:
            credential_label = revoked_credential.get('schema_title') or revoked_credential.get('said', '')
            message_text = (
                f"The credential '{credential_label}' was revoked locally, but the Castellan "
                f"server still reports it as issued. Revoking it also changed the key state "
                f"for issuer '{issuer_name}'.\n\n"
                f"Local sequence number: {local_sn}\n"
                f"Server sequence number: {remote_sn if remote_sn > -1 else 'Not found'}\n\n"
                f"Would you like to update the server with the revocation and current key state?"
            )
        else:
            message_text = (
                f"The Castellan server has an outdated key state for identifier '{issuer_name}'.\n\n"
                f"Local sequence number: {local_sn}\n"
                f"Server sequence number: {remote_sn if remote_sn > -1 else 'Not found'}\n\n"
                f"Would you like to update the key state on the server?"
            )

        message = QLabel(message_text)
        message.setStyleSheet("font-size: 13px;")
        message.setWordWrap(True)
        layout.addWidget(message)

        # Button row
        button_row = QHBoxLayout()
        button_row.addStretch()
        self.cancel_btn = LocksmithInvertedButton("Cancel")
        self.update_btn = LocksmithButton("Update")
        button_row.addWidget(self.cancel_btn)
        button_row.addSpacing(10)
        button_row.addWidget(self.update_btn)

        super().__init__(
            parent=parent,
            title="Update Key State",
            title_icon=":/assets/material-icons/warning.svg",
            content=content_widget,
            buttons=button_row,
        )

        self.cancel_btn.clicked.connect(self.reject)
        self.update_btn.clicked.connect(self._on_update)
        if revoked_credential:
            self.setFixedSize(500, 350)
        else:
            self.setFixedSize(500, 300)

    @qasync.asyncSlot()
    async def _on_update(self):
        """Push the revoked credential's status (if any) and the identifier's key state."""
        if self.revoked_credential:
            said = self.revoked_credential.get('said', '')
            logger.info(f"Pushing revoked status for credential {said}")
            result = await remoting.update_issued_credential_status(
                app=self.app,
                credential_said=said,
                status="revoked",
            )
            if not result.get('success'):
                self.show_error(f"Failed to update credential status: {result.get('error', 'Unknown error')}")
                return

        if self.remote_sn < self.local_sn:
            logger.info(
                f"Update key state requested for '{self.issuer_name}' "
                f"(local_sn={self.local_sn}, remote_sn={self.remote_sn})"
            )
            result = await remoting.upload_account_identifier(
                app=self.app,
                aid=self.issuer_aid,
                alias=self.issuer_name,
            )
            if not result.get('success'):
                self.show_error(f"Failed to update key state: {result.get('error', 'Unknown error')}")
                return

        self.accept()
