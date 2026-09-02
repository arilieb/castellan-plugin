# -*- encoding: utf-8 -*-
"""
castellan.credentials.issued.upload module

Dialog for uploading a single issued credential to the Castellan server.
Uses FloatingLabelComboBox for credential selection.
"""
import json
from collections.abc import Callable
from typing import TYPE_CHECKING

import qasync
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel
from keri import help

from locksmith.ui.toolkit.widgets import (
    LocksmithDialog, LocksmithButton, LocksmithInvertedButton,
    EditableTextLabelValue, EditableURLLabelValue, EditableEmailLabelValue,
    EditableAddressLabelValue, EditableDateLabelValue, EditablePhoneLabelValue
)
from locksmith.ui.toolkit.widgets.fields import FloatingLabelComboBox
from ...core import remoting

if TYPE_CHECKING:
    from locksmith.core.apping import LocksmithApplication
    from locksmith.ui.vault.page import VaultPage

logger = help.ogler.getLogger(__name__)


class UploadIssuedCredentialsDialog(LocksmithDialog):
    """Dialog for uploading a single issued credential to the Castellan server."""

    def __init__(
        self,
        app: "LocksmithApplication",
        on_refresh: Callable[[], None] | None = None,
        parent: "VaultPage | None" = None,
    ):
        self.app = app
        self.on_refresh = on_refresh
        self._is_uploading = False
        self._dynamic_fields = []  # List to track added dynamic fields
        self._credential_data = {}  # Map index to credential data
        self._remembered_fields = []  # Store remembered fields for selected schema

        content_widget = QWidget()
        self._content_layout = QVBoxLayout(content_widget)
        self._content_layout.setContentsMargins(0, 10, 0, 0)
        self._content_layout.setSpacing(12)

        instruction = QLabel("Select a credential to upload to the Castellan server.")
        instruction.setStyleSheet("font-size: 13px; color: #636466;")
        instruction.setWordWrap(True)
        self._content_layout.addWidget(instruction)

        self.credential_selector = FloatingLabelComboBox(label_text="Select Credential")
        self.credential_selector.setFixedWidth(450)
        self.credential_selector.currentIndexChanged.connect(self._on_credential_selected)
        self._content_layout.addWidget(self.credential_selector)

        # Add field type dropdown (initially hidden, shown when credential is selected)
        # Right-aligned, positioned directly below the credential selector
        field_type_container = QHBoxLayout()

        # Add "Add remembered fields?" link (left-aligned, initially hidden)
        self.remembered_fields_link = QLabel('Add remembered fields?')
        self.remembered_fields_link.setStyleSheet("""
            QLabel {
                color: #0066cc;
                text-decoration: underline;
                font-size: 13px;
            }
            QLabel:hover {
                color: #0052a3;
            }
        """)
        self.remembered_fields_link.setCursor(Qt.CursorShape.PointingHandCursor)
        self.remembered_fields_link.setVisible(False)  # Hidden initially
        self.remembered_fields_link.mousePressEvent = lambda event: self._on_add_remembered_fields()
        field_type_container.addWidget(self.remembered_fields_link)

        field_type_container.addStretch()  # Push dropdown to the right

        self.add_field_dropdown = FloatingLabelComboBox(label_text="+ add more")
        self.add_field_dropdown.setFixedWidth(200)
        self.add_field_dropdown.addItem("Select field type...")
        self.add_field_dropdown.addItem("Text")
        self.add_field_dropdown.addItem("URL")
        self.add_field_dropdown.addItem("Email")
        self.add_field_dropdown.addItem("Address")
        self.add_field_dropdown.addItem("Date")
        self.add_field_dropdown.addItem("Phone")
        self.add_field_dropdown.setCurrentIndex(0)
        self.add_field_dropdown.setVisible(False)  # Hidden initially
        self.add_field_dropdown.currentIndexChanged.connect(self._on_field_type_selected)

        field_type_container.addWidget(self.add_field_dropdown)
        self._content_layout.addLayout(field_type_container)

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
            title="Upload Issued Credential",
            title_icon=":/assets/material-icons/out-badge.svg",
            content=content_widget,
            buttons=button_row,
        )

        self.cancel_btn.clicked.connect(self.close)
        self.upload_btn.clicked.connect(self._on_upload)

        self.setFixedWidth(530)
        self._initial_height = 350  # Base height without field dropdown
        self._expanded_height = 450  # Height with field dropdown visible

        # Populate dropdown async
        self._populate_dropdown()

    def _on_credential_selected(self, index: int):
        """Handle credential selection from the dropdown."""
        if index <= 0:  # Skip placeholder "Select Credential" option
            # No credential selected - hide add field dropdown and remembered fields link
            self.add_field_dropdown.setVisible(False)
            self.remembered_fields_link.setVisible(False)
            # Reset add field dropdown to default state
            self.add_field_dropdown.setCurrentIndex(0)
            # Clear dynamic fields
            self._clear_dynamic_fields()
            # Clear remembered fields cache
            self._remembered_fields = []
            # Restore original dialog height
            self.setFixedHeight(self._initial_height)
            self.center_on_parent()
        else:
            # Credential selected - show add field dropdown
            self.add_field_dropdown.setVisible(True)
            # Resize dialog to accommodate field dropdown
            self.setFixedHeight(self._expanded_height)
            self.center_on_parent()

            # Query backend for remembered fields
            self._fetch_remembered_fields(index)

    def _clear_dynamic_fields(self):
        """Remove all dynamic field widgets from the layout."""
        for field in self._dynamic_fields:
            self._content_layout.removeWidget(field)
            field.deleteLater()
        self._dynamic_fields.clear()

    @qasync.asyncSlot()
    async def _fetch_remembered_fields(self, credential_index: int):
        """Fetch remembered fields for the selected credential's schema."""
        credential_data = self._credential_data.get(credential_index)
        if not credential_data:
            return

        schema = credential_data.get('schema', {})
        schema_said = schema.get('$id', '')

        if not schema_said:
            logger.warning("Selected credential has no schema SAID")
            self._remembered_fields = []
            self.remembered_fields_link.setVisible(False)
            return

        try:
            result = await remoting.fetch_schema_fields(self.app, schema_said)

            if result.get('success'):
                fields = result.get('fields', [])
                self._remembered_fields = fields

                # Show link only if there are remembered fields
                if fields:
                    self.remembered_fields_link.setVisible(True)
                else:
                    self.remembered_fields_link.setVisible(False)
            else:
                logger.error(f"Failed to fetch schema fields: {result.get('error')}")
                self._remembered_fields = []
                self.remembered_fields_link.setVisible(False)

        except Exception as e:
            logger.exception(f"Error fetching remembered fields: {e}")
            self._remembered_fields = []
            self.remembered_fields_link.setVisible(False)

    def _adjust_dialog_height(self):
        """Adjust dialog height based on number of dynamic fields."""
        # Each field adds approximately 60px (label + value + spacing)
        field_height = 60
        base_height = self._expanded_height
        additional_height = len(self._dynamic_fields) * field_height
        new_height = min(base_height + additional_height, 700)  # Cap at 700px
        self.setFixedHeight(new_height)
        self.center_on_parent()

    def _on_field_type_selected(self, index: int):
        """
        Handle field type selection from the '+ add more' dropdown.

        This method is called when the user selects a field type to add
        as a dynamic field to the credential being uploaded.

        Args:
            index: The selected index in the dropdown
        """
        if index <= 0:  # Skip the placeholder "Select field type..." option
            return

        field_type = self.add_field_dropdown.currentText()
        logger.info(f"Field type selected: {field_type}")

        # Create appropriate editable component based on field type
        field_widget = None
        if field_type == "Text":
            field_widget = EditableTextLabelValue(label="Field Name", value="")
        elif field_type == "URL":
            field_widget = EditableURLLabelValue(label="URL", value="")
        elif field_type == "Email":
            field_widget = EditableEmailLabelValue(label="Email", value="")
        elif field_type == "Address":
            field_widget = EditableAddressLabelValue(label="Address", value="")
        elif field_type == "Date":
            field_widget = EditableDateLabelValue(label="Date", value="")
        elif field_type == "Phone":
            field_widget = EditablePhoneLabelValue(label="Phone", value="")

        if field_widget:
            # Add to dynamic fields list
            self._dynamic_fields.append(field_widget)

            # Insert before the stretch and button row
            # Layout order: instruction, credential_selector, field_type_container, dynamic_fields..., stretch, buttons
            insert_index = self._content_layout.count() - 1  # Before stretch
            self._content_layout.insertWidget(insert_index, field_widget)

            # Adjust dialog height to accommodate new field
            self._adjust_dialog_height()

        # Reset dropdown to placeholder after selection
        self.add_field_dropdown.setCurrentIndex(0)

    def _on_add_remembered_fields(self):
        """Add all remembered fields to the dialog when link is clicked."""
        if not self._remembered_fields:
            return

        # Map type strings to widget classes
        type_map = {
            'text': EditableTextLabelValue,
            'url': EditableURLLabelValue,
            'email': EditableEmailLabelValue,
            'address': EditableAddressLabelValue,
            'date': EditableDateLabelValue,
            'phone': EditablePhoneLabelValue,
        }

        for field_data in self._remembered_fields:
            label = field_data.get('label', 'Field')
            field_type = field_data.get('type', 'text').lower()

            # Get appropriate widget class
            WidgetClass = type_map.get(field_type, EditableTextLabelValue)

            # Create field widget with label and empty value
            field_widget = WidgetClass(label=label, value="")

            # Add to dynamic fields list
            self._dynamic_fields.append(field_widget)

            # Insert before the stretch and button row
            insert_index = self._content_layout.count() - 1  # Before stretch
            self._content_layout.insertWidget(insert_index, field_widget)

        # Adjust dialog height to accommodate new fields
        self._adjust_dialog_height()

        # Hide the link after adding fields (prevent duplicate adds)
        self.remembered_fields_link.setVisible(False)

    @qasync.asyncSlot()
    async def _populate_dropdown(self):
        """Populate the selector with local issued credentials not yet on Castellan."""
        if not self.app or not self.app.vault or not self.app.vault.rgy:
            return

        try:
            existing_saids = await remoting.fetch_all_castellan_issued_saids(self.app)

            reger = self.app.vault.rgy.reger
            hby = self.app.vault.hby
            local_aids = list(hby.habs.keys())
            saids = [said for ((issuer_said,), said) in reger.issus.getItemIter() if issuer_said in local_aids]
            creds = reger.cloneCreds(saids, hby.db)

            # Clear existing items
            self.credential_selector.clear()
            self._credential_data.clear()

            # Add placeholder
            self.credential_selector.addItem("Select a credential...")

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

                # Look up human-readable names
                issuer_name = self._get_issuer_name(issuer)
                recipient_name = self._get_recipient_name(recipient)

                recipient_display = recipient[:15] + '...' if len(recipient) > 15 else recipient
                display_text = f"{schema_title} - {recipient_display} ({cred_said[:12]}...)"
                items.append({
                    'display': display_text,
                    'said': cred_said,
                    'schema': schema,
                    'issuer': issuer,
                    'recipient': recipient,
                    'iss_rec': f"{issuer_name} → {recipient_name}",
                    'schema_title': schema_title
                })

            if items:
                # Add items to combo box and store data
                for idx, item in enumerate(items, start=1):  # Start at 1 to account for placeholder
                    self.credential_selector.addItem(item['display'])
                    self._credential_data[idx] = item
            else:
                self.credential_selector.setEnabled(False)
                self.upload_btn.setEnabled(False)

        except Exception as e:
            logger.exception(f"Error populating upload dropdown: {e}")
            self.show_error(f"Error loading credentials: {e}")

    def _get_issuer_name(self, issuer_aid: str) -> str:
        """
        Get human-readable name for issuer using habery.

        Args:
            issuer_aid: The issuer's AID prefix

        Returns:
            Hab name if found, otherwise truncated AID
        """
        if not issuer_aid or not self.app or not self.app.vault:
            return issuer_aid[:10] + '...' if len(issuer_aid) > 10 else issuer_aid

        try:
            hby = self.app.vault.hby

            # Lookup hab by AID
            hab = hby.habs.get(issuer_aid)
            if hab and hab.name:
                return hab.name

            # Fallback to truncated AID if hab not found
            return issuer_aid[:10] + '...' if len(issuer_aid) > 10 else issuer_aid

        except Exception as e:
            logger.warning(f"Error looking up issuer name for {issuer_aid}: {e}")
            return issuer_aid[:10] + '...' if len(issuer_aid) > 10 else issuer_aid

    def _get_recipient_name(self, recipient_aid: str) -> str:
        """
        Get human-readable name for recipient using Organizer.

        Args:
            recipient_aid: The recipient's AID prefix

        Returns:
            Contact alias if found, otherwise truncated AID
        """
        if not recipient_aid or not self.app or not self.app.vault:
            return recipient_aid[:10] + '...' if len(recipient_aid) > 10 else recipient_aid

        try:
            hby = self.app.vault.hby

            # First check if recipient is a local hab
            hab = hby.habs.get(recipient_aid)
            if hab and hab.name:
                return hab.name

            # Check Organizer for contact
            org = self.app.vault.org
            if org:
                contact = org.get(recipient_aid)
                if contact and isinstance(contact, dict):
                    alias = contact.get("alias", "")
                    if alias:
                        return alias

            # Fallback to truncated AID
            return recipient_aid[:10] + '...' if len(recipient_aid) > 10 else recipient_aid

        except Exception as e:
            logger.warning(f"Error looking up recipient name for {recipient_aid}: {e}")
            return recipient_aid[:10] + '...' if len(recipient_aid) > 10 else recipient_aid

    def _on_upload(self):
        if self._is_uploading:
            return

        # Get selected credential from combo box
        current_index = self.credential_selector.currentIndex()
        if current_index <= 0:
            self.show_error("Select a credential to upload.")
            return

        credential_data = self._credential_data.get(current_index)
        if not credential_data:
            self.show_error("Invalid credential selection.")
            return

        self._is_uploading = True
        self.upload_btn.setEnabled(False)
        self.upload_btn.setText("Uploading...")
        self.clear_error()
        self._do_upload(credential_data)


    @qasync.asyncSlot()
    async def _do_upload(self, credential_data: dict):
        try:
            # Collect dynamic field data
            dynamic_field_data = []
            if self._dynamic_fields:
                for field in self._dynamic_fields:
                    field_data = {
                        'label': field.label(),
                        'value': field.value(),
                        'type': field.type,
                    }
                    dynamic_field_data.append(field_data)

            result = await remoting.upload_issued_credential(
                app=self.app,
                credential_said=credential_data['said'],
                schema=credential_data['schema'],
                issuer=credential_data['issuer'],
                recipient=credential_data['recipient'],
                dynamic_field_data=dynamic_field_data,
            )

            if not result.get('success'):
                self.show_error(f"Upload failed: {result.get('error', 'Unknown error')}")
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
