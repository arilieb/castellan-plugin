# -*- encoding: utf-8 -*-
"""
castellan.issuers.upload module

Dialog for uploading a local (non-group) identifier to the Castellan server
for peer discovery. Local-only — no remote/peer upload option.

Also serves as the sole entry point into InitiateMultisigPage via the
"Create a Castellan Multisig" link; it does not itself read or write
MultisigIdentityState, which remains exclusively InitiateMultisigPage's
concern.
"""
from collections.abc import Callable
from typing import TYPE_CHECKING

import qasync
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton
from keri import help
from keri.app.habbing import GroupHab

from locksmith.ui import colors
from locksmith.ui.toolkit.widgets import LocksmithDialog, LocksmithButton, LocksmithInvertedButton
from locksmith.ui.toolkit.widgets.fields import FloatingLabelComboBox
from ..core import remoting

if TYPE_CHECKING:
    from locksmith.core.apping import LocksmithApplication
    from locksmith.ui.vault.page import VaultPage

logger = help.ogler.getLogger(__name__)


class UploadIdentifierDialog(LocksmithDialog):
    """Dialog for uploading a local identifier to the Castellan server."""

    def __init__(
        self,
        app: "LocksmithApplication",
        existing_identifiers: list[str],
        on_refresh: Callable[[], None] | None = None,
        on_navigate_to_multisig_init: Callable[[], None] | None = None,
        parent: "VaultPage | None" = None,
    ):
        self.app = app
        self.existing_identifiers = existing_identifiers
        self.on_refresh = on_refresh
        self.on_navigate_to_multisig_init = on_navigate_to_multisig_init
        self._is_uploading = False
        self._aid_by_display: dict[str, str] = {}

        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 10, 0, 0)
        content_layout.setSpacing(12)

        self.identifier_selector = FloatingLabelComboBox(label_text="Select Issuer")
        self.identifier_selector.setFixedWidth(420)
        content_layout.addWidget(self.identifier_selector)

        self.multisig_link = QPushButton("Create a Castellan Multi-signature Issuer")
        self.multisig_link.setCursor(Qt.CursorShape.PointingHandCursor)
        self.multisig_link.setFlat(True)
        self.multisig_link.setStyleSheet(f"""
            QPushButton {{
                border: none;
                background: transparent;
                color: {colors.BLUE_ACCENT};
                text-decoration: underline;
                font-size: 13px;
                text-align: left;
                padding: 0;
            }}
            QPushButton:hover {{
                color: {colors.BLUE_SELECTION};
            }}
        """)
        self.multisig_link.clicked.connect(self._on_multisig_link_clicked)
        content_layout.addWidget(self.multisig_link)

        content_layout.addStretch()

        button_row = QHBoxLayout()
        button_row.addStretch()
        self.cancel_btn = LocksmithInvertedButton("Cancel")
        self.upload_btn = LocksmithButton("Upload")
        button_row.addWidget(self.cancel_btn)
        button_row.addSpacing(10)
        button_row.addWidget(self.upload_btn)

        super().__init__(
            parent=parent,
            title="Add Issuer",
            title_icon=":/assets/material-icons/badge.svg",
            content=content_widget,
            buttons=button_row,
        )

        self.setFixedSize(480, 270)

        self.cancel_btn.clicked.connect(self.close)
        self.upload_btn.clicked.connect(self._on_upload)

        self._populate_dropdown()

    def _populate_dropdown(self):
        """Populate with local, non-group habs not already uploaded."""
        if not self.app or not self.app.vault:
            return

        self.identifier_selector.clear()
        self._aid_by_display.clear()

        hby = self.app.vault.hby
        for aid, hab in hby.habs.items():
            if isinstance(hab, GroupHab):
                continue
            if aid in self.existing_identifiers:
                continue
            display = f"{hab.name} - {aid}"
            self._aid_by_display[display] = aid
            self.identifier_selector.addItem(display)

        if not self._aid_by_display:
            self.identifier_selector.setEnabled(False)
            self.upload_btn.setEnabled(False)

    def _on_multisig_link_clicked(self):
        self.close()
        if self.on_navigate_to_multisig_init:
            self.on_navigate_to_multisig_init()

    def _on_upload(self):
        if self._is_uploading:
            return

        display = self.identifier_selector.currentText()
        aid = self._aid_by_display.get(display)
        if not aid:
            self.show_error("Select an issuer to upload.")
            return

        hab = self.app.vault.hby.habs.get(aid)
        if hab is None:
            self.show_error("Selected issuer not found.")
            return

        self._is_uploading = True
        self.upload_btn.setEnabled(False)
        self.upload_btn.setText("Uploading...")
        self.clear_error()
        self._do_upload(hab)

    @qasync.asyncSlot()
    async def _do_upload(self, hab):
        try:
            oobi = ""
            try:
                oobi_result = hab.makeOwnEndRole()
                if oobi_result:
                    oobi = oobi_result.decode() if isinstance(oobi_result, bytes) else str(oobi_result)
            except Exception:
                pass

            kel_bytes = b"".join(self.app.vault.hby.db.clonePreIter(pre=hab.pre, fn=0))
            if not kel_bytes:
                self.show_error("No KEL events found for selected issuer — cannot upload.")
                return

            result = await remoting.upload_identifier(
                app=self.app,
                aid=hab.pre,
                alias=hab.name,
                kel_bytes=kel_bytes,
                oobi=oobi,
            )

            if not result.get('success'):
                self.show_error(f"Upload failed: {result.get('error', 'Unknown error')}")
            else:
                self.close()
                if self.on_refresh:
                    QTimer.singleShot(100, self.on_refresh)
        except Exception as e:
            logger.exception(f"Error uploading identifier: {e}")
            self.show_error(str(e))
        finally:
            self._is_uploading = False
            self.upload_btn.setEnabled(True)
            self.upload_btn.setText("Upload")
