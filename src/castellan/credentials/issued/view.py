# -*- encoding: utf-8 -*-
"""
castellan.credentials.issued.view module

Dialog for viewing an issued credential stored on the Castellan server.
"""
import json
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame
from keri import help
from keri.app import connecting
from keri.help import helping
from locksmith.ui import colors
from locksmith.ui.toolkit.widgets import (
    LocksmithDialog, LocksmithButton,
    EditableTextLabelValue, EditableURLLabelValue, EditableEmailLabelValue,
    EditableAddressLabelValue, EditableDateLabelValue, EditablePhoneLabelValue
)
from locksmith.ui.toolkit.widgets.buttons import LocksmithCopyButton
from locksmith.ui.toolkit.widgets.fields import LocksmithLineEdit, LocksmithPlainTextEdit

if TYPE_CHECKING:
    from locksmith.ui.vault.page import VaultPage

logger = help.ogler.getLogger(__name__)


class ViewIssuedCredentialDialog(LocksmithDialog):
    """Read-only dialog displaying all fields of an issued credential from Castellan."""

    def __init__(self, app, credential: dict, parent: "VaultPage | None" = None):
        self.app = app
        self.org = connecting.Organizer(hby=self.app.vault.hby)

        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(12)

        sad = credential.get('sad', {})

        # Add spacing after SAID
        layout.addSpacing(8)

        self._build_credential_info_section(layout, credential)

        # Display dynamic fields if present
        dynamic_fields = credential.get('dynamic_fields', [])
        if dynamic_fields:
            # Add spacing before dynamic fields section
            layout.addSpacing(8)

            # Add section header
            dynamic_header = QLabel("Additional Fields")
            dynamic_header.setStyleSheet("font-weight: bold; font-size: 13px; color: #636466;")
            layout.addWidget(dynamic_header)

            # Add each dynamic field
            for field_data in dynamic_fields:
                if isinstance(field_data, dict) and field_data.get('label') and field_data.get('value'):
                    field_widget = self._create_readonly_dynamic_field(field_data)
                    layout.addWidget(field_widget)

            # Add spacing after dynamic fields section
            layout.addSpacing(8)

        sad_label = QLabel("Raw Credental Data")
        sad_label.setStyleSheet("font-weight: bold; font-size: 13px;")
        layout.addWidget(sad_label)

        sad_field = LocksmithPlainTextEdit()
        sad_field.setPlainText(json.dumps(sad, indent=2))
        sad_field.setReadOnly(True)
        sad_field.setMinimumHeight(160)
        layout.addWidget(sad_field)

        button_row = QHBoxLayout()
        button_row.addStretch()
        close_btn = LocksmithButton("Close")

        title_content = QWidget()
        title_content_layout = QVBoxLayout()
        title_content.setLayout(title_content_layout)
        self.title_label = QLabel("Issued Credential")
        self.title_label.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {colors.TEXT_PRIMARY};")
        title_content_layout.addWidget(self.title_label)
        title_content_layout.addSpacing(2)

        # Display SAID as a label with copy button
        said = credential.get('said', '')
        said_row = QHBoxLayout()
        said_label = QLabel(said)
        said_label.setStyleSheet(
            "font-family: 'Menlo', 'SF Mono', monospace; "
            "font-size: 12px; "
            "color: #636466;"
        )
        said_label.setWordWrap(True)
        said_row.addWidget(said_label)
        copy_btn = LocksmithCopyButton(copy_content=said,  icon_size=24)
        copy_btn.setFixedHeight(22)
        copy_btn.setFixedWidth(22)

        said_row.addWidget(copy_btn)
        said_row.addStretch()
        title_content_layout.addLayout(said_row)


        super().__init__(
            parent=parent,
            title_content=title_content,
            title_icon=":/assets/material-icons/out-badge.svg",
            content=content_widget,
            buttons=button_row,
        )

        close_btn.clicked.connect(self.close)
        button_row.addWidget(close_btn)
        button_row.addStretch()

        self.setFixedSize(600, 800)


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

        # Issuer
        issuer_pre = credential['sad']['i']
        issuer_alias = None
        try:
            for hab_pre, hab in self.app.vault.hby.habs.items():
                if hab.pre == issuer_pre:
                    issuer_alias = hab.name
                    break
        except:
            pass

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

        # Recipient
        recp = credential.get('recipient', '')
        recipient_pre = credential['sad']['a']['i']
        recipient_alias = None
        if (remote_id := self.org.get(recp)) is not None:
            recipient_alias = f'{remote_id['alias']}'

        recipient_label = QLabel("Recipient")
        recipient_label.setStyleSheet("font-weight: bold; font-size: 14px; border: none; margin-top: 10px;")
        info_layout.addWidget(recipient_label)

        recipient_container = QWidget()
        recipient_container.setStyleSheet("border: none;")
        recipient_inner_layout = QVBoxLayout(recipient_container)
        recipient_inner_layout.setContentsMargins(20, 0, 0, 0)
        recipient_inner_layout.setSpacing(5)

        recipient_alias_row = QHBoxLayout()
        recipient_alias_label = QLabel("Alias:")
        recipient_alias_label.setStyleSheet("font-weight: 500; font-size: 13px; border: none;")
        recipient_alias_row.addWidget(recipient_alias_label)
        recipient_alias_value = QLabel(recipient_alias if recipient_alias else "N/A")
        recipient_alias_value.setStyleSheet("font-size: 13px; border: none;")
        recipient_alias_row.addWidget(recipient_alias_value)
        recipient_alias_row.addStretch()
        recipient_inner_layout.addLayout(recipient_alias_row)

        recipient_aid_row = QHBoxLayout()
        recipient_aid_label = QLabel("AID:")
        recipient_aid_label.setStyleSheet("font-weight: 500; font-size: 13px; border: none;")
        recipient_aid_row.addWidget(recipient_aid_label)
        recipient_aid_value = QLabel(recipient_pre)
        recipient_aid_value.setStyleSheet("font-size: 13px; border: none;")
        recipient_aid_value.setWordWrap(True)
        recipient_aid_row.addWidget(recipient_aid_value)
        recipient_aid_row.addStretch()
        recipient_inner_layout.addLayout(recipient_aid_row)

        info_layout.addWidget(recipient_container)

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

        # Issued Date
        dt = helping.fromIso8601(credential.get('created_at', ''))

        date_row = QHBoxLayout()
        date_label = QLabel("Issued Date:")
        date_label.setStyleSheet("font-weight: 500; font-size: 13px; border: none;")
        date_row.addWidget(date_label)

        date_value = QLabel(dt.strftime("%b %d, %Y %I:%M %p"))
        date_value.setStyleSheet("font-size: 13px; border: none;")
        date_row.addWidget(date_value)
        date_row.addStretch()
        info_layout.addLayout(date_row)

        layout.addWidget(info_frame)


    @staticmethod
    def _add_field_row(layout: QVBoxLayout, label: str, value: str,
                       monospace: bool = False, copyable: bool = False):
        field_label = QLabel(label)
        field_label.setStyleSheet("font-weight: bold; font-size: 13px;")
        layout.addWidget(field_label)

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

        layout.addLayout(row)

    @staticmethod
    def _create_readonly_dynamic_field(field_data: dict) -> QWidget:
        """
        Create a read-only dynamic field widget based on field type.

        Args:
            field_data: Dict with 'label', 'value', and 'type' keys

        Returns:
            Read-only widget displaying the field
        """
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
        field_widget = ComponentClass(label=label, value=value)

        # Set to read-only mode (no click-to-edit)
        field_widget.setReadOnly(True)

        return field_widget
