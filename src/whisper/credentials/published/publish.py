# -*- encoding: utf-8 -*-
"""
locksmith.ui.vault.healthKERI.credentials.published.publish module

Dialog for publishing credentials to the healthKERI account.
"""
from collections.abc import Callable
from typing import TYPE_CHECKING

import qasync
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel,
)
from keri import help

from ...core import remoting
from locksmith.ui import colors
from locksmith.ui.toolkit.widgets import (
    LocksmithDialog,
    LocksmithButton,
    LocksmithInvertedButton
)
from locksmith.ui.toolkit.widgets.fields import FloatingLabelComboBox

if TYPE_CHECKING:
    from locksmith.core.apping import LocksmithApplication
    from locksmith.ui.vault.page import VaultPage

logger = help.ogler.getLogger(__name__)


class PublishCredentialDialog(LocksmithDialog):
    """Dialog for publishing credentials to the healthKERI account.

    Allows users to select an issued credential from their vault
    and publish it to their healthKERI account.
    """

    def __init__(
        self,
        app: "LocksmithApplication",
        existing_credentials: list[str] | None = None,
        on_refresh: Callable[[], None] | None = None,
        parent: "VaultPage | None" = None
    ):
        """
        Initialize the PublishCredentialDialog.

        Args:
            app: Application instance
            existing_credentials: List of credential SAIDs already published (to filter out)
            on_refresh: Callback to refresh the credentials list on success
            parent: Parent widget
        """
        super().__init__(
            parent=parent,
            title="Publish Credential",
            title_icon=":/assets/material-icons/out-badge.svg"
        )

        self.app = app
        self.existing_credentials = set(existing_credentials) if existing_credentials else set()
        self.on_refresh = on_refresh
        self._is_publishing = False

        # Build dialog content
        self._build_content()

        # Set dialog size
        self.setFixedSize(470, 300)

    def _build_content(self):
        """Build the dialog content."""
        layout = self.content_layout
        layout.setSpacing(15)

        layout.addSpacing(10)

        # Instruction label
        instruction_label = QLabel("Select a credential to publish to your healthKERI account")
        instruction_label.setStyleSheet("font-size: 13px; color: #636466;")
        instruction_label.setWordWrap(True)
        layout.addWidget(instruction_label)

        layout.addSpacing(10)

        # Credential dropdown
        self.credential_dropdown = FloatingLabelComboBox(label_text="Issued Credential")
        self.credential_dropdown.setFixedWidth(425)

        self._populate_credential_dropdown()
        layout.addWidget(self.credential_dropdown)

        # Status/error label
        self.status_label = QLabel()
        self.status_label.setStyleSheet(f"color: {colors.DANGER}; font-size: 12px;")
        self.status_label.setWordWrap(True)
        self.status_label.setVisible(False)
        layout.addWidget(self.status_label)

        layout.addStretch()

        # Button section
        self._build_buttons(layout)

        layout.addStretch()

    @qasync.asyncSlot()
    async def _populate_credential_dropdown(self):
        """Populate the credential dropdown with issued credentials."""
        self.credential_dropdown.clear()
        self.credential_dropdown.addItem("Select a credential...")

        if not self.app or not self.app.vault or not self.app.vault.rgy:
            return

        try:
            aids =  await remoting.fetch_all_published_identifier_aids(self.app)

            # Get all issued credentials
            reger = self.app.vault.rgy.reger
            saids = [said for (_, said) in reger.issus.getItemIter()]
            creds = reger.cloneCreds(saids, self.app.vault.hby.db)

            for credential in creds:
                sad = credential['sad']
                cred_said = sad['d']
                issuer = sad.get('i')

                if issuer not in aids:
                    continue

                # Filter out already-published credentials
                if cred_said in self.existing_credentials:
                    continue

                # Get schema info for display
                schema = credential.get("schema")
                if not schema:
                    continue

                # Get info
                schema_title = schema.get("title", "Unknown Schema")
                issuer = sad.get('i', '')
                subject = sad.get('a')
                recipient = subject.get('i', '')
                recipient_display = recipient[:15] + '...' if len(recipient) > 15 else recipient

                # Format: "Schema Title - Recipient (SAID...)"
                display_text = f"{schema_title} - {recipient_display} ({cred_said[:12]}...)"

                self.credential_dropdown.addItem(
                    display_text,
                    userData={
                        'said': cred_said,
                        'schema': schema,
                        'recipient': recipient,
                        'issuer': issuer
                    }
                )

            # If no credentials available
            if self.credential_dropdown.count() == 1:
                self.credential_dropdown.addItem("No credentials available to publish")
                self.credential_dropdown.setCurrentIndex(1)
                self.credential_dropdown.setEnabled(False)

        except Exception as e:
            logger.exception(f"Error loading issued credentials: {e}")
            self.credential_dropdown.addItem("Error loading credentials")
            self.credential_dropdown.setEnabled(False)

    def _build_buttons(self, layout: QVBoxLayout):
        """Build the action buttons."""
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.cancel_button = LocksmithInvertedButton(text="Cancel")
        self.cancel_button.clicked.connect(self.close)
        button_layout.addWidget(self.cancel_button)

        self.publish_button = LocksmithButton(text="Publish")
        self.publish_button.clicked.connect(self._on_publish)
        button_layout.addWidget(self.publish_button)

        layout.addLayout(button_layout)

    def _on_publish(self):
        """Handle publish button click."""
        if self._is_publishing:
            return

        if self.credential_dropdown.currentIndex() <= 0:
            self._show_error("Please select a credential to publish.")
            return

        data = self.credential_dropdown.currentData()
        if not data:
            self._show_error("Invalid selection.")
            return

        cred_said = data.get('said')
        if not cred_said:
            self._show_error("Could not retrieve credential SAID.")
            return

        # Start publish with proper qasync integration
        self._is_publishing = True
        self.publish_button.setEnabled(False)
        self.publish_button.setText("Publishing...")
        self.status_label.setVisible(False)
        self._do_publish(cred_said=cred_said, schema=data.get('schema', {}), issuer=data.get('issuer', ''),
                         recipient=data.get('recipient', ''))

    @qasync.asyncSlot()
    async def _do_publish(self, cred_said: str, schema: dict, issuer: str, recipient: str):
        """
        Perform the publish operation asynchronously.

        Parameters:
            cred_said: The SAID of the credential to be published.
            schema: The schema information for the credential.
            issuer: The issuer's identifier.
            recipient: The recipient's identifier.

        Returns:
            None
        """
        try:
            # First ensure the issuer's KEL is up to date.
            result = await remoting.send_key_state_update(self.app, issuer)
            if result.get('success'):
                logger.info(f"Key state update successful for issuer {issuer}")
            else:
                error_msg = result.get('error', 'Unknown error')
                logger.error(f"Failed to update issuer's key state: {error_msg}")
                self._show_error(f"Failed to update issuer's key state: {error_msg}")
                return

            result = await remoting.publish_credential(
                app=self.app,
                credential_said=cred_said,
                schema=schema,
                issuer=issuer,
                recipient=recipient
            )

            if result.get('success'):
                logger.info(f"Successfully published credential {cred_said}")
                # Close dialog first
                self.close()
                # Then trigger refresh with slight delay to let UI settle
                if self.on_refresh:
                    QTimer.singleShot(100, self.on_refresh)
            else:
                error_msg = result.get('error', 'Unknown error')
                logger.error(f"Failed to publish credential: {error_msg}")
                self._show_error(f"Publish failed: {error_msg}")

        except Exception as e:
            logger.exception(f"Error publishing credential: {e}")
            self._show_error(f"Publish failed: {str(e)}")
        finally:
            self._is_publishing = False
            self.publish_button.setEnabled(True)
            self.publish_button.setText("Publish")

    def _show_error(self, message: str):
        """Display an error message."""
        self.status_label.setText(message)
        self.status_label.setVisible(True)
