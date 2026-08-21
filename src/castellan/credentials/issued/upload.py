# -*- encoding: utf-8 -*-
"""
castellan.credentials.issued.upload module

Dialog for uploading issued credentials to the Castellan server.
Uses ExtensibleSelectorWidget for multi-select.
"""
import json
from collections.abc import Callable
from typing import TYPE_CHECKING

import qasync
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel
from keri import help

from locksmith.ui.toolkit.widgets import LocksmithDialog, LocksmithButton, LocksmithInvertedButton
from locksmith.ui.toolkit.widgets.extensible import ExtensibleSelectorWidget
from ...core import remoting

if TYPE_CHECKING:
    from locksmith.core.apping import LocksmithApplication
    from locksmith.ui.vault.page import VaultPage

logger = help.ogler.getLogger(__name__)


class UploadIssuedCredentialsDialog(LocksmithDialog):
    """Dialog for uploading one or more issued credentials to the Castellan server."""

    def __init__(
        self,
        app: "LocksmithApplication",
        on_refresh: Callable[[], None] | None = None,
        parent: "VaultPage | None" = None,
    ):
        self.app = app
        self.on_refresh = on_refresh
        self._is_uploading = False

        content_widget = QWidget()
        self._content_layout = QVBoxLayout(content_widget)
        self._content_layout.setContentsMargins(0, 10, 0, 0)
        self._content_layout.setSpacing(12)

        instruction = QLabel("Select credentials to upload to the Castellan server.")
        instruction.setStyleSheet("font-size: 13px; color: #636466;")
        instruction.setWordWrap(True)
        self._content_layout.addWidget(instruction)

        self.credential_selector = ExtensibleSelectorWidget(
            dropdown_label="Select Credential",
            selector_dropdown_items=[],
            max_scrollable_height=200,
        )
        self.credential_selector.setFixedWidth(450)
        self._content_layout.addWidget(self.credential_selector)
        self._content_layout.addStretch()

        button_row = QHBoxLayout()
        button_row.addStretch()
        self.cancel_btn = LocksmithInvertedButton("Cancel")
        self.upload_btn = LocksmithButton("Upload")
        button_row.addWidget(self.cancel_btn)
        button_row.addSpacing(10)
        button_row.addWidget(self.upload_btn)

        super().__init__(
            parent=parent,
            title="Upload Issued Credentials",
            title_icon=":/assets/material-icons/out-badge.svg",
            content=content_widget,
            buttons=button_row,
        )

        self.cancel_btn.clicked.connect(self.close)
        self.upload_btn.clicked.connect(self._on_upload)

        self.setFixedWidth(530)

        # Populate dropdown async
        self._populate_dropdown()

    def showEvent(self, event):
        super().showEvent(event)
        self.credential_selector.set_dialog(self)

    @qasync.asyncSlot()
    async def _populate_dropdown(self):
        """Populate the selector with local issued credentials not yet on Castellan."""
        if not self.app or not self.app.vault or not self.app.vault.rgy:
            return

        try:
            existing_saids = await remoting.fetch_all_castellan_issued_saids(self.app)

            reger = self.app.vault.rgy.reger
            hby = self.app.vault.hby
            saids = [said for (_, said) in reger.issus.getItemIter()]
            creds = reger.cloneCreds(saids, hby.db)

            items = []
            for cred in creds:
                sad = cred['sad']
                cred_said = sad['d']

                if cred_said in existing_saids:
                    continue

                schema = cred.get('schema', {})
                if not schema:
                    continue

                schema_title = schema.get('title', 'Unknown Schema')
                issuer = sad.get('i', '')
                subject = sad.get('a', {})
                recipient = subject.get('i', '') if isinstance(subject, dict) else ''
                recipient_display = recipient[:15] + '...' if len(recipient) > 15 else recipient
                display_text = f"{schema_title} - {recipient_display} ({cred_said[:12]}...)"
                items.append((display_text, {
                    'said': cred_said,
                    'schema': schema,
                    'issuer': issuer,
                    'recipient': recipient,
                    'iss_rec': f"Issuer/Recipient: {issuer[:10]}... / {recipient[:10]}...",
                    'schema_title': schema_title
                }))

            if items:
                self.credential_selector._populate_dropdown(items)
            else:
                self.credential_selector.selector_dropdown.setPlaceholderText("No credentials available to upload")
                self.upload_btn.setEnabled(False)

        except Exception as e:
            logger.exception(f"Error populating upload dropdown: {e}")
            self.show_error(f"Error loading credentials: {e}")

    def _on_upload(self):
        if self._is_uploading:
            return

        selected = self.credential_selector.get_selected_items()
        if not selected:
            self.show_error("Select at least one credential to upload.")
            return

        self._is_uploading = True
        self.upload_btn.setEnabled(False)
        self.upload_btn.setText("Uploading...")
        self.clear_error()
        self._do_upload(selected)


    @qasync.asyncSlot()
    async def _do_upload(self, selected: list):
        errors = []
        try:
            for _text, data in selected:
                if data is None:
                    continue
                result = await remoting.upload_issued_credential(
                    app=self.app,
                    credential_said=data['said'],
                    schema=data['schema'],
                    issuer=data['issuer'],
                    recipient=data['recipient'],
                )
                if not result.get('success'):
                    errors.append(f"{data['said'][:12]}...: {result.get('error', 'Unknown error')}")

            if errors:
                self.show_error("Some uploads failed:\n" + "\n".join(errors))
            else:
                self.close()
                if self.on_refresh:
                    self.on_refresh()
        except Exception as e:
            logger.exception(f"Error during upload: {e}")
            self.show_error(str(e))
        finally:
            self._is_uploading = False
            self.upload_btn.setEnabled(True)
            self.upload_btn.setText("Upload")
