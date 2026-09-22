# -*- encoding: utf-8 -*-
"""
archie.ui.rename module

This module contains the rename dialog for renaming a conversation from the sidebar.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QWidget, QHBoxLayout, QPushButton, QLineEdit


class RenameDialog(QDialog):
    def __init__(self, current_name, parent=None):
        super().__init__(parent)
        self.new_name = None
        self.setWindowTitle("Rename Conversation")
        self.setFixedSize(400, 250)
        self.setStyleSheet("""
            QDialog {
                background-color: white;
                border-radius: 12px;
            }
            QLabel#title {
                font-size: 28px;
                font-weight: semibold;
                color: #010101;
                background-color: white;
            }
            QLabel#subtitle {
                font-size: 13px;
                color: #444;
                background-color: white;
            }
            QLineEdit {
                padding: 12px;
                font-size: 16px;
                border-radius: 6px;
                border: 1px solid #ccc;
                background-color: #fff;
                color: #000;
            }
            QPushButton {
                padding: 10px 20px;
                font-size: 14px;
                border-radius: 8px;
            }
            QPushButton#cancel {
                color: #ec6f27;
                border: 1px solid #ec6f27;
                background: transparent;
            }
            QPushButton#cancel:hover {
                background-color: #ffe8dd;
            }
            QPushButton#rename {
                background-color: #ec6f27;
                color: white;
            }
            QPushButton#rename:hover {
                background-color: #d95c16;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        # Title
        title = QLabel("Rename Conversation")
        title.setObjectName("title")
        layout.addWidget(title)

        # Divider line
        divider = QWidget()
        divider.setFixedHeight(1)
        divider.setStyleSheet("background-color: #ccc;")
        layout.addWidget(divider)

        # Subtitle
        subtitle = QLabel("Enter a new name for this conversation.")
        subtitle.setWordWrap(True)
        subtitle.setObjectName("subtitle")
        layout.addWidget(subtitle)

        # Name input
        self.name_input = QLineEdit(text=current_name)
        self.name_input.selectAll()
        layout.addWidget(self.name_input)

        # Spacer
        layout.addStretch()

        # Action buttons
        button_row = QHBoxLayout()
        button_row.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("cancel")
        cancel_btn.setFixedWidth(100)
        cancel_btn.clicked.connect(self.reject)

        rename_btn = QPushButton("Rename")
        rename_btn.setObjectName("rename")
        rename_btn.setDefault(True)
        rename_btn.setFixedWidth(100)
        rename_btn.clicked.connect(self.accept_rename)

        button_row.addWidget(cancel_btn)
        button_row.addWidget(rename_btn)

        layout.addLayout(button_row)

    def accept_rename(self):
        self.new_name = self.name_input.text().strip()
        if self.new_name:
            self.accept()

    def showEvent(self, event):
        """Override showEvent to set focus on the text field when dialog is shown."""
        super().showEvent(event)
        self.name_input.setFocus()