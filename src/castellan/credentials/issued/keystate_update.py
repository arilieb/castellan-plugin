# -*- encoding: utf-8 -*-
"""Dialog for prompting user to update identifier key state on Castellan server."""

from typing import TYPE_CHECKING

import qasync
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel
from keri import help
from locksmith.ui.toolkit.widgets import LocksmithDialog, LocksmithButton, LocksmithInvertedButton

from ...core import remoting

if TYPE_CHECKING:
    from locksmith.ui.vault.page import VaultPage

logger = help.ogler.getLogger(__name__)


class KeyStateUpdateDialog(LocksmithDialog):
    """Dialog for prompting user to update identifier key state on the Castellan server."""

    def __init__(
        self,
        app,
        issuer_name: str,
        issuer_aid: str,
        local_sn: int,
        remote_sn: int,
        parent: "VaultPage | None" = None,
    ):
        """Initialize the key state update dialog.

        Args:
            issuer_name: Human-readable name of the issuer identifier
            issuer_aid: AID of the issuer identifier
            local_sn: Local sequence number (current key state)
            remote_sn: Remote sequence number (server's key state)
            parent: Parent VaultPage
        """

        self.app = app
        self.issuer_name = issuer_name
        self.issuer_aid = issuer_aid
        self.local_sn = local_sn
        self.remote_sn = remote_sn

        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(12)

        # Warning message
        message = QLabel(
            f"The Castellan server has an outdated key state for identifier '{issuer_name}'.\n\n"
            f"Local sequence number: {local_sn}\n"
            f"Server sequence number: {remote_sn if remote_sn > -1 else 'Not found'}\n\n"
            f"Would you like to update the key state on the server?"
        )
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

        self.setFixedSize(500, 300)

    @qasync.asyncSlot()
    async def _on_update(self):
        """Handle Update button click (stubbed for now)."""
        logger.info(f"Update key state requested for '{self.issuer_name}' (local_sn={self.local_sn}, remote_sn={self.remote_sn})")
        result = await remoting.upload_account_identifier(
            app=self.app,
            aid=self.issuer_aid,
            alias=self.issuer_name
        )
        self.accept()
