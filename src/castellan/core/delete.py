# -*- encoding: utf-8 -*-
"""
archie.ui.delete module

This module contains the delete dialog for deleting a conversation from the sidebar.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QWidget, QHBoxLayout, QPushButton


class ConfirmDeleteDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Delete Conversation")
        self.setFixedSize(400, 220)
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
            QPushButton#delete {
                background-color: #a31d1d;
                color: white;
            }
            QPushButton#delete:hover {
                background-color: #8a1818;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        # Title
        title = QLabel("Delete Conversation")
        title.setObjectName("title")
        layout.addWidget(title)

        # Divider line
        divider = QWidget()
        divider.setFixedHeight(1)
        divider.setStyleSheet("background-color: #ccc;")
        layout.addWidget(divider)

        # Subtitle
        subtitle = QLabel("Are you sure you want to delete this conversation? This action cannot be undone.")
        subtitle.setWordWrap(True)
        subtitle.setObjectName("subtitle")
        layout.addWidget(subtitle)

        # Spacer
        layout.addStretch()

        # Action buttons
        button_row = QHBoxLayout()
        button_row.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("cancel")
        cancel_btn.setFixedWidth(100)
        cancel_btn.clicked.connect(self.reject)

        delete_btn = QPushButton("Delete")
        delete_btn.setObjectName("delete")
        delete_btn.setDefault(True)
        delete_btn.setFixedWidth(100)
        delete_btn.clicked.connect(self.accept)

        button_row.addWidget(cancel_btn)
        button_row.addWidget(delete_btn)

        layout.addLayout(button_row)

