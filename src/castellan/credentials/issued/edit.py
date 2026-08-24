# -*- encoding: utf-8 -*-
"""
castellan.credentials.issued.edit module

Dialog for editing dynamic fields of an issued credential on the Castellan server.
"""
from collections.abc import Callable
from typing import TYPE_CHECKING

import qasync
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from PySide6.QtGui import QIcon
from PySide6.QtCore import Qt, Signal
from keri import help

from locksmith.ui.toolkit.widgets import (
    LocksmithDialog, LocksmithButton, LocksmithInvertedButton,
    EditableTextLabelValue, EditableURLLabelValue, EditableEmailLabelValue,
    EditableAddressLabelValue, EditableDateLabelValue, EditablePhoneLabelValue
)
from locksmith.ui.toolkit.widgets.fields import FloatingLabelComboBox, LocksmithLineEdit
from locksmith.ui.toolkit.widgets.buttons import LocksmithCopyButton
from ...core import remoting

if TYPE_CHECKING:
    from locksmith.core.apping import LocksmithApplication
    from locksmith.ui.vault.page import VaultPage

logger = help.ogler.getLogger(__name__)


class DynamicFieldWidget(QWidget):
    """Wrapper for editable field components with delete button."""

    delete_requested = Signal()

    def __init__(self, field_component: QWidget, deletable: bool = True):
        super().__init__()
        self.field_component = field_component
        self.type = getattr(field_component, 'type', 'text')

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Add field component (takes most space)
        layout.addWidget(field_component, stretch=1)

        if deletable:
            # Add delete button (trash icon)
            delete_btn = QPushButton()
            delete_btn.setIcon(QIcon(":/assets/material-icons/delete.svg"))
            delete_btn.setFixedSize(32, 32)
            delete_btn.setStyleSheet("border: none; background: transparent;")
            delete_btn.setCursor(Qt.PointingHandCursor)
            delete_btn.setToolTip("Delete field")
            delete_btn.clicked.connect(self.delete_requested.emit)
            layout.addWidget(delete_btn, alignment=Qt.AlignTop)

    def label(self) -> str:
        """Get the field label."""
        return self.field_component.label()

    def value(self) -> str:
        """Get the field value."""
        return self.field_component.value()


class EditIssuedCredentialDialog(LocksmithDialog):
    """Dialog for editing dynamic fields of an issued credential."""

    def __init__(
        self,
        app: "LocksmithApplication",
        credential: dict,
        on_success: Callable[[], None] | None = None,
        parent: "VaultPage | None" = None,
    ):
        self.app = app
        self.credential = credential
        self.on_success = on_success
        self._is_saving = False
        self._dynamic_fields = []  # List of DynamicFieldWidget instances

        # Build content widget
        content_widget = QWidget()
        self._content_layout = QVBoxLayout(content_widget)
        self._content_layout.setContentsMargins(0, 10, 0, 0)
        self._content_layout.setSpacing(12)

        # Section 1: Read-only credential metadata
        self._add_readonly_metadata()

        # Section 2: Editable dynamic fields
        self._add_dynamic_fields_section()

        # Section 3: Add field dropdown
        self._add_field_type_dropdown()

        # Error message label
        self.error_label = QLabel()
        self.error_label.setStyleSheet("color: red; font-size: 12px;")
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)
        self._content_layout.addWidget(self.error_label)

        self._content_layout.addStretch()

        # Buttons
        button_row = self._create_button_row()

        super().__init__(
            parent=parent,
            title="Edit Issued Credential",
            title_icon=":/assets/material-icons/edit.svg",
            content=content_widget,
            buttons=button_row,
        )

        self.setFixedSize(600, 800)
        self._adjust_dialog_height()

    def _add_readonly_metadata(self):
        """Add read-only credential metadata section."""
        metadata_label = QLabel("Credential Information")
        metadata_label.setStyleSheet("font-weight: bold; font-size: 13px; color: #636466;")
        self._content_layout.addWidget(metadata_label)

        said = self.credential.get('said', '')
        schema = self.credential.get('schema', {})

        self._add_field_row("SAID", said, monospace=True, copyable=True)
        self._add_field_row("Schema", schema.get('title', ''))
        self._add_field_row("Issuer", self.credential.get('issuer', ''), monospace=True)
        self._add_field_row("Recipient", self.credential.get('recipient', ''), monospace=True)

        # Add spacing before dynamic fields section
        self._content_layout.addSpacing(8)

    def _add_field_row(self, label: str, value: str, monospace: bool = False, copyable: bool = False):
        """Add a read-only field row."""
        field_label = QLabel(label)
        field_label.setStyleSheet("font-weight: bold; font-size: 13px;")
        self._content_layout.addWidget(field_label)

        row = QHBoxLayout()
        field = LocksmithLineEdit()
        field.setText(value)
        field.setReadOnly(True)
        if monospace:
            field.setStyleSheet(field.styleSheet() + "font-family: 'Menlo', 'SF Mono', monospace;")
        row.addWidget(field)

        if copyable:
            copy_btn = LocksmithCopyButton(copy_content=value)
            row.addWidget(copy_btn)

        self._content_layout.addLayout(row)

    def _add_dynamic_fields_section(self):
        """Add editable dynamic fields section."""
        dynamic_header = QLabel("Dynamic Fields")
        dynamic_header.setStyleSheet("font-weight: bold; font-size: 13px; color: #636466;")
        self._content_layout.addWidget(dynamic_header)

        # Add existing dynamic fields from credential
        existing_fields = self.credential.get('dynamic_fields', [])
        for field_data in existing_fields:
            if isinstance(field_data, dict) and field_data.get('label') and field_data.get('value'):
                field_widget = self._create_field_widget(field_data, deletable=True)
                if field_widget:
                    self._dynamic_fields.append(field_widget)
                    self._content_layout.addWidget(field_widget)

    def _add_field_type_dropdown(self):
        """Add '+ add more' dropdown for adding new fields."""
        field_type_container = QHBoxLayout()
        field_type_container.addStretch()

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
        self.add_field_dropdown.currentIndexChanged.connect(self._on_field_type_selected)

        field_type_container.addWidget(self.add_field_dropdown)
        self._content_layout.addLayout(field_type_container)

    def _create_field_widget(self, field_data: dict, deletable: bool = True) -> DynamicFieldWidget | None:
        """Create a dynamic field widget with delete button."""
        label = field_data.get('label', 'Field')
        value = field_data.get('value', '')
        field_type = field_data.get('type', 'text').lower()

        # Map type to appropriate component class
        type_map = {
            'text': EditableTextLabelValue,
            'url': EditableURLLabelValue,
            'email': EditableEmailLabelValue,
            'address': EditableAddressLabelValue,
            'date': EditableDateLabelValue,
            'phone': EditablePhoneLabelValue,
        }

        # Get component class (default to text if unknown type)
        ComponentClass = type_map.get(field_type, EditableTextLabelValue)

        # Create component with label and value
        field_component = ComponentClass(label=label, value=value)

        # Wrap in DynamicFieldWidget with delete button
        wrapper = DynamicFieldWidget(field_component, deletable=deletable)
        wrapper.delete_requested.connect(lambda w=wrapper: self._on_delete_field(w))

        return wrapper

    def _on_field_type_selected(self, index: int):
        """Handle field type selection from '+ add more' dropdown."""
        if index <= 0:  # Skip placeholder
            return

        field_type = self.add_field_dropdown.currentText()

        # Create empty field of selected type
        field_data = {
            'label': 'Field Name',
            'value': '',
            'type': field_type.lower()
        }

        field_widget = self._create_field_widget(field_data, deletable=True)
        if field_widget:
            self._dynamic_fields.append(field_widget)

            # Insert before error label, stretch, and buttons
            insert_index = self._content_layout.count() - 2  # Before error label and stretch
            self._content_layout.insertWidget(insert_index, field_widget)

            # Adjust dialog height
            self._adjust_dialog_height()

        # Reset dropdown to placeholder
        self.add_field_dropdown.setCurrentIndex(0)

    def _on_delete_field(self, field_widget: DynamicFieldWidget):
        """Remove field from layout and list."""
        if field_widget in self._dynamic_fields:
            self._dynamic_fields.remove(field_widget)
            self._content_layout.removeWidget(field_widget)
            field_widget.deleteLater()
            self._adjust_dialog_height()

    def _adjust_dialog_height(self):
        """Adjust dialog height based on number of dynamic fields."""
        # Base height includes: metadata section + headers + dropdown + buttons
        base_height = 800

        # Each field adds approximately 60px
        field_height = 60
        additional_height = len(self._dynamic_fields) * field_height

        # Cap at 700px to prevent dialog from being too tall
        new_height = min(base_height + additional_height, 950)
        self.setFixedHeight(new_height)
        self.center_on_parent()

    def _create_button_row(self) -> QHBoxLayout:
        """Create button row with Cancel and Save buttons."""
        button_row = QHBoxLayout()
        button_row.addStretch()

        self.cancel_btn = LocksmithInvertedButton("Cancel")
        self.save_btn = LocksmithButton("Save")

        button_row.addWidget(self.cancel_btn)
        button_row.addSpacing(10)
        button_row.addWidget(self.save_btn)

        self.cancel_btn.clicked.connect(self.close)
        self.save_btn.clicked.connect(self._on_save)

        return button_row

    def _on_save(self):
        """Validate and trigger async save operation."""
        if self._is_saving:
            return

        # Clear previous error
        self.error_label.setVisible(False)
        self.error_label.setText("")

        # Validate fields
        for field_widget in self._dynamic_fields:
            label = field_widget.label().strip()
            value = field_widget.value().strip()

            if not label:
                self.error_label.setText("Field labels cannot be empty.")
                self.error_label.setVisible(True)
                return

            if not value:
                self.error_label.setText("Field values cannot be empty.")
                self.error_label.setVisible(True)
                return

        # Start save operation
        self._is_saving = True
        self.save_btn.setEnabled(False)
        self.save_btn.setText("Saving...")
        self.cancel_btn.setEnabled(False)

        self._do_save()

    @qasync.asyncSlot()
    async def _do_save(self):
        """Perform async save operation."""
        try:
            # Collect dynamic field data
            dynamic_field_data = []
            for field_widget in self._dynamic_fields:
                field_data = {
                    'label': field_widget.label(),
                    'value': field_widget.value(),
                    'type': field_widget.type,
                }
                dynamic_field_data.append(field_data)

            # Call update API
            result = await remoting.update_issued_credential_metadata(
                app=self.app,
                credential_said=self.credential.get('said', ''),
                dynamic_field_data=dynamic_field_data,
            )

            if not result.get('success'):
                error_msg = result.get('error', 'Unknown error')
                self.error_label.setText(f"Save failed: {error_msg}")
                self.error_label.setVisible(True)
            else:
                # Success - close dialog and call callback
                self.close()
                if self.on_success:
                    self.on_success()

        except Exception as e:
            logger.exception(f"Error during save: {e}")
            self.error_label.setText(f"Save failed: {str(e)}")
            self.error_label.setVisible(True)
        finally:
            self._is_saving = False
            self.save_btn.setEnabled(True)
            self.save_btn.setText("Save")
            self.cancel_btn.setEnabled(True)
