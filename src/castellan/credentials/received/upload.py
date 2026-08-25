# -*- encoding: utf-8 -*-
"""
castellan.credentials.received.upload module

Dialog for uploading a single received credential to the Castellan server.
Uses FloatingLabelComboBox for credential selection with dynamic fields support.
"""
from collections.abc import Callable
from typing import TYPE_CHECKING

import qasync
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


class UploadReceivedCredentialsDialog(LocksmithDialog):
    """Dialog for uploading a single received credential to the Castellan server."""

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
        field_type_container = QHBoxLayout()
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
            title="Upload Received Credential",
            title_icon=":/assets/material-icons/in-badge.svg",
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
            # No credential selected - hide add field dropdown
            self.add_field_dropdown.setVisible(False)
            # Reset add field dropdown to default state
            self.add_field_dropdown.setCurrentIndex(0)
            # Clear dynamic fields
            self._clear_dynamic_fields()
            # Restore original dialog height
            self.setFixedHeight(self._initial_height)
            self.center_on_parent()
        else:
            # Credential selected - show add field dropdown
            self.add_field_dropdown.setVisible(True)
            # Resize dialog to accommodate field dropdown
            self.setFixedHeight(self._expanded_height)
            self.center_on_parent()

    def _clear_dynamic_fields(self):
        """Remove all dynamic field widgets from the layout."""
        for field in self._dynamic_fields:
            self._content_layout.removeWidget(field)
            field.deleteLater()
        self._dynamic_fields.clear()

    def _adjust_dialog_height(self):
        """Adjust dialog height based on number of dynamic fields."""
        # Each field adds approximately 60px
        field_height = 60
        base_height = self._expanded_height
        additional_height = len(self._dynamic_fields) * field_height
        new_height = min(base_height + additional_height, 700)  # Cap at 700px
        self.setFixedHeight(new_height)
        self.center_on_parent()

    def _on_field_type_selected(self, index: int):
        """Handle field type selection from the '+ add more' dropdown."""
        if index <= 0:  # Skip the placeholder
            return

        field_type = self.add_field_dropdown.currentText()

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

            # Insert before the stretch
            insert_index = self._content_layout.count() - 1  # Before stretch
            self._content_layout.insertWidget(insert_index, field_widget)

            # Adjust dialog height to accommodate new field
            self._adjust_dialog_height()

        # Reset dropdown to placeholder after selection
        self.add_field_dropdown.setCurrentIndex(0)

    @qasync.asyncSlot()
    async def _populate_dropdown(self):
        """Populate the selector with local received credentials not yet on Castellan."""
        if not self.app or not self.app.vault or not self.app.vault.rgy:
            return

        try:
            existing_saids = await remoting.fetch_all_castellan_received_saids(self.app)

            reger = self.app.vault.rgy.reger
            hby = self.app.vault.hby
            saids = list()
            for pre in self.app.vault.hby.habs.keys():
                saids.extend([saider for saider in self.app.vault.rgy.reger.subjs.get(keys=(pre,))])
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
                holder = subject.get('i', '') if isinstance(subject, dict) else ''
                issuer_display = issuer[:15] + '...' if len(issuer) > 15 else issuer

                display_text = f"{schema_title} - {issuer_display} ({cred_said[:12]}...)"
                items.append({
                    'display': display_text,
                    'said': cred_said,
                    'schema': schema,
                    'issuer': issuer,
                    'holder': holder,
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

            result = await remoting.upload_received_credential(
                app=self.app,
                credential_said=credential_data['said'],
                schema=credential_data['schema'],
                issuer=credential_data['issuer'],
                holder=credential_data['holder'],
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
