# -*- encoding: utf-8 -*-
"""
castellan.credentials.received.edit module

Dialog for editing dynamic fields of a received credential on the Castellan server.
"""
from collections.abc import Callable
from typing import TYPE_CHECKING

import qasync
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame
from keri import help
from keri.app import connecting
from keri.help import helping
from locksmith.ui import colors
from locksmith.ui.toolkit.widgets import (
    LocksmithDialog, LocksmithButton, LocksmithInvertedButton,
    EditableTextLabelValue, EditableURLLabelValue, EditableEmailLabelValue,
    EditableAddressLabelValue, EditableDateLabelValue, EditablePhoneLabelValue
)
from locksmith.ui.toolkit.widgets.buttons import LocksmithCopyButton
from locksmith.ui.toolkit.widgets.fields import FloatingLabelComboBox, LocksmithLineEdit

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
            delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            delete_btn.setToolTip("Delete field")
            delete_btn.clicked.connect(self.delete_requested.emit)
            layout.addWidget(delete_btn, alignment=Qt.AlignmentFlag.AlignTop)

    def label(self) -> str:
        """Get the field label."""
        return self.field_component.label()

    def value(self) -> str:
        """Get the field value."""
        return self.field_component.value()


class EditReceivedCredentialDialog(LocksmithDialog):
    """Dialog for editing dynamic fields of a received credential."""

    def __init__(
        self,
        app: "LocksmithApplication",
        credential: dict,
        on_success: Callable[[], None] | None = None,
        parent: "VaultPage | None" = None,
    ):
        self.app = app
        self.org = connecting.Organizer(hby=self.app.vault.hby)

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
        self._build_credential_info_section(self._content_layout, credential)

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
            title="Edit Received Credential",
            title_icon=":/assets/material-icons/edit.svg",
            content=content_widget,
            buttons=button_row,
        )

        # Set fixed width only, allow height to be dynamic
        self.setFixedWidth(700)
        self.setMinimumHeight(400)  # Minimum viable height
        self.setMaximumHeight(950)  # Cap at 950px as before
        self._adjust_dialog_height()

    def _build_credential_info_section(self, layout, credential):
        """Build the credential information section as a bordered, rounded QFrame."""
        schema = credential.get('schema', {})
        schema_title = schema.get('title', '')

        info_frame = QFrame()
        info_frame.setStyleSheet(f"""
            QFrame {{
                border: 2px solid {colors.BORDER};
                border-radius: 8px;
                background-color: {colors.BACKGROUND_CONTENT};
            }}
        """)
        info_layout = QVBoxLayout(info_frame)
        info_layout.setContentsMargins(10, 10, 10, 10)
        info_layout.setSpacing(10)

        # Title
        info_title = QLabel("Credential Information")
        info_title.setStyleSheet("font-weight: bold; font-size: 14px; border: none;")
        info_layout.addWidget(info_title)

        # Schema
        schema_row = QHBoxLayout()
        schema_label = QLabel("Schema:")
        schema_label.setStyleSheet("font-weight: 500; font-size: 13px; border: none;")
        schema_row.addWidget(schema_label)

        schema_value = QLabel(schema_title)
        schema_value.setStyleSheet("font-size: 13px; border: none;")
        schema_row.addWidget(schema_value)
        schema_row.addStretch()
        info_layout.addLayout(schema_row)

        # Issuer (remote)
        issuer_pre = credential['sad']['i']
        issuer_alias = None
        if (remote_id := self.org.get(issuer_pre)) is not None:
            issuer_alias = f'{remote_id["alias"]}'

        issuer_label = QLabel("Issuer")
        issuer_label.setStyleSheet("font-weight: bold; font-size: 14px; border: none; margin-top: 10px;")
        info_layout.addWidget(issuer_label)

        issuer_container = QWidget()
        issuer_container.setStyleSheet("border: none;")
        issuer_inner_layout = QVBoxLayout(issuer_container)
        issuer_inner_layout.setContentsMargins(20, 0, 0, 0)
        issuer_inner_layout.setSpacing(5)

        issuer_alias_row = QHBoxLayout()
        issuer_alias_label = QLabel("Alias:")
        issuer_alias_label.setStyleSheet("font-weight: 500; font-size: 13px; border: none;")
        issuer_alias_row.addWidget(issuer_alias_label)
        issuer_alias_value = QLabel(issuer_alias if issuer_alias else "N/A")
        issuer_alias_value.setStyleSheet("font-size: 13px; border: none;")
        issuer_alias_row.addWidget(issuer_alias_value)
        issuer_alias_row.addStretch()
        issuer_inner_layout.addLayout(issuer_alias_row)

        issuer_aid_row = QHBoxLayout()
        issuer_aid_label = QLabel("AID:")
        issuer_aid_label.setStyleSheet("font-weight: 500; font-size: 13px; border: none;")
        issuer_aid_row.addWidget(issuer_aid_label)
        issuer_aid_value = QLabel(issuer_pre)
        issuer_aid_value.setStyleSheet("font-size: 13px; border: none;")
        issuer_aid_value.setWordWrap(True)
        issuer_aid_row.addWidget(issuer_aid_value)
        issuer_aid_row.addStretch()
        issuer_inner_layout.addLayout(issuer_aid_row)

        info_layout.addWidget(issuer_container)

        # Holder (local)
        holder = credential.get('holder', '')
        holder_alias = None
        try:
            for hab_pre, hab in self.app.vault.hby.habs.items():
                if hab.pre == holder:
                    holder_alias = hab.name
                    break
        except:
            pass

        holder_label = QLabel("Holder")
        holder_label.setStyleSheet("font-weight: bold; font-size: 14px; border: none; margin-top: 10px;")
        info_layout.addWidget(holder_label)

        holder_container = QWidget()
        holder_container.setStyleSheet("border: none;")
        holder_inner_layout = QVBoxLayout(holder_container)
        holder_inner_layout.setContentsMargins(20, 0, 0, 0)
        holder_inner_layout.setSpacing(5)

        holder_alias_row = QHBoxLayout()
        holder_alias_label = QLabel("Alias:")
        holder_alias_label.setStyleSheet("font-weight: 500; font-size: 13px; border: none;")
        holder_alias_row.addWidget(holder_alias_label)
        holder_alias_value = QLabel(holder_alias if holder_alias else "N/A")
        holder_alias_value.setStyleSheet("font-size: 13px; border: none;")
        holder_alias_row.addWidget(holder_alias_value)
        holder_alias_row.addStretch()
        holder_inner_layout.addLayout(holder_alias_row)

        holder_aid_row = QHBoxLayout()
        holder_aid_label = QLabel("AID:")
        holder_aid_label.setStyleSheet("font-weight: 500; font-size: 13px; border: none;")
        holder_aid_row.addWidget(holder_aid_label)
        holder_aid_value = QLabel(holder)
        holder_aid_value.setStyleSheet("font-size: 13px; border: none;")
        holder_aid_value.setWordWrap(True)
        holder_aid_row.addWidget(holder_aid_value)
        holder_aid_row.addStretch()
        holder_inner_layout.addLayout(holder_aid_row)

        info_layout.addWidget(holder_container)

        # Status
        status_text = credential.get("status", {})

        status_row = QHBoxLayout()
        status_label = QLabel("Status:")
        status_label.setStyleSheet("font-weight: 500; font-size: 13px; border: none;")
        status_row.addWidget(status_label)

        status_value = QLabel(status_text)
        status_value.setStyleSheet("font-size: 13px; border: none;")
        status_row.addWidget(status_value)
        status_row.addStretch()
        info_layout.addLayout(status_row)

        # Received Date
        dt = helping.fromIso8601(credential.get('created_at', ''))

        date_row = QHBoxLayout()
        date_label = QLabel("Received Date:")
        date_label.setStyleSheet("font-weight: 500; font-size: 13px; border: none;")
        date_row.addWidget(date_label)

        date_value = QLabel(dt.strftime("%b %d, %Y %I:%M %p"))
        date_value.setStyleSheet("font-size: 13px; border: none;")
        date_row.addWidget(date_value)
        date_row.addStretch()
        info_layout.addLayout(date_row)

        layout.addWidget(info_frame)

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

        # Connect to editModeChanged signal for address fields to adjust dialog height
        if isinstance(field_component, EditableAddressLabelValue):
            field_component.editModeChanged.connect(self._on_address_edit_mode_changed)

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

    def _on_address_edit_mode_changed(self, mode: str):
        """
        Handle address widget edit mode changes.

        When an address field enters edit mode, it expands from ~40px to ~220px.
        We resize the dialog FIRST, then let layout recalculate with correct space.

        Args:
            mode: The new edit mode ('display', 'edit_value', or 'edit_label')
        """
        # CRITICAL: Adjust dialog height FIRST, before layout recalculation
        # This ensures the dialog has enough space for the expanded widget
        self._adjust_dialog_height()

        # Now force layout recalculation with new dialog size
        content_widget = self._content_layout.parentWidget()
        if content_widget:
            content_widget.updateGeometry()
            if content_widget.layout():
                content_widget.layout().activate()

        # Update scroll area to new content size
        if hasattr(self, 'scroll_area'):
            self.scroll_area.updateGeometry()
            # Force scroll area to recalculate viewport size
            self.scroll_area.widget().adjustSize()

        # Process any pending layout events
        from PySide6.QtCore import QCoreApplication
        QCoreApplication.processEvents()

    def _adjust_dialog_height(self):
        """Adjust dialog height based on actual dynamic field sizes."""
        # Calculate base height: info section + headers + dropdown + buttons + margins
        base_height = 500  # Approximate base without dynamic fields

        # Calculate actual height needed for dynamic fields
        fields_height = 0
        for field_widget in self._dynamic_fields:
            widget_height = field_widget.sizeHint().height()
            fields_height += widget_height + 12  # Add spacing

        # Calculate total content height needed
        content_height = base_height + fields_height

        # Clamp to min/max bounds
        new_height = max(400, min(content_height, 950))

        # Set both min and max to lock height at calculated value
        # Using setMinimum/Maximum instead of setFixedHeight allows future calls to change height
        self.setMinimumHeight(new_height)
        self.setMaximumHeight(new_height)

        # Force geometry update to propagate changes
        self.updateGeometry()

        # Center on parent after resize
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
            result = await remoting.update_received_credential_metadata(
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
