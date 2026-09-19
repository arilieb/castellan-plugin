# -*- encoding: utf-8 -*-
"""
castellan.users.view module

Dialog for viewing a user account from the Castellan server.
"""
import json
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel
from keri import help
from keri.help import helping

from locksmith.ui.toolkit.widgets import LocksmithDialog, LocksmithButton
from locksmith.ui.toolkit.widgets.fields import LocksmithLineEdit, LocksmithPlainTextEdit
from locksmith.ui.toolkit.widgets.buttons import LocksmithCopyButton
from locksmith.ui import colors

if TYPE_CHECKING:
    from locksmith.ui.vault.page import VaultPage

logger = help.ogler.getLogger(__name__)


class ViewUserDialog(LocksmithDialog):
    """Read-only dialog displaying user account details."""

    def __init__(self, user: dict, parent: "VaultPage | None" = None):
        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(12)

        # Extract user fields
        user_id = user.get('aid', '')
        name = user.get('username', '') or user.get('name', '')
        email = user.get('email', '')
        first_name = user.get('first_name')
        last_name = user.get('last_name')
        role = user.get('role', 'Owner').capitalize()
        status = user.get('status', 'Active').capitalize()
        created_at_raw = user.get('created_at', '')

        # Format dates
        if created_at_raw:
            created_at_date = helping.fromIso8601(created_at_raw)
            created_at = created_at_date.strftime("%b %d, %Y %I:%M %p")
        else:
            created_at = "Unknown"

        # Build layout
        self._add_field_row(layout, "User ID", user_id, monospace=True, copyable=True)
        self._add_field_row(layout, "User Name", name)
        self._add_field_row(layout, "First Name", first_name)
        self._add_field_row(layout, "Last Name", last_name)
        self._add_field_row(layout, "Email", email, copyable=True)
        self._add_field_row(layout, "Role", role)
        self._add_field_row(layout, "Status", status)
        self._add_field_row(layout, "Created Date", created_at)

        button_row = QHBoxLayout()
        button_row.addStretch()
        close_btn = LocksmithButton("Close")

        super().__init__(
            parent=parent,
            title="User Account",
            title_icon=":/assets/material-icons/group.svg",
            content=content_widget,
            buttons=button_row,
        )

        close_btn.clicked.connect(self.close)
        button_row.addWidget(close_btn)
        button_row.addStretch()

        self.setFixedWidth(550)
        self.setFixedHeight(800)

    @staticmethod
    def _add_field_row(layout: QVBoxLayout, label: str, value: str,
                       monospace: bool = False, copyable: bool = False):
        """Add a label/value row to the layout."""
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
