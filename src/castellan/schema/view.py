# -*- encoding: utf-8 -*-
"""
castellan.schema.view module

Dialog for viewing a schema stored on the Castellan server.
"""
import json
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel
from keri import help

from locksmith.ui.toolkit.widgets import LocksmithDialog, LocksmithButton
from locksmith.ui.toolkit.widgets.fields import LocksmithLineEdit, LocksmithPlainTextEdit
from locksmith.ui.toolkit.widgets.buttons import LocksmithCopyButton

if TYPE_CHECKING:
    from locksmith.ui.vault.page import VaultPage

logger = help.ogler.getLogger(__name__)


class ViewSchemaDialog(LocksmithDialog):
    """Read-only dialog displaying all fields of a schema from Castellan."""

    def __init__(self, schema: dict, parent: "VaultPage | None" = None):
        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(12)

        said = schema.get('$id', '')
        title = schema.get('title', '')
        version = schema.get('version', '')
        description = schema.get('description', '')
        created_at = schema.get('created_at', '')
        sad = schema.get('sad', {})

        self._add_field_row(layout, "SAID", said, monospace=True, copyable=True)
        self._add_field_row(layout, "Title", title)
        self._add_field_row(layout, "Version", version)
        if description:
            self._add_field_row(layout, "Description", description)
        self._add_field_row(layout, "Created Date", created_at)

        sad_label = QLabel("Schema Definition (SAD)")
        sad_label.setStyleSheet("font-weight: bold; font-size: 13px;")
        layout.addWidget(sad_label)

        sad_field = LocksmithPlainTextEdit()
        sad_field.setPlainText(json.dumps(sad, indent=2))
        sad_field.setReadOnly(True)
        sad_field.setMinimumHeight(200)
        layout.addWidget(sad_field)

        button_row = QHBoxLayout()
        button_row.addStretch()
        close_btn = LocksmithButton("Close")

        super().__init__(
            parent=parent,
            title="Schema",
            title_icon=":/assets/material-icons/schema.svg",
            content=content_widget,
            buttons=button_row,
        )

        close_btn.clicked.connect(self.close)
        button_row.addWidget(close_btn)
        button_row.addStretch()

        self.setFixedWidth(530)

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
