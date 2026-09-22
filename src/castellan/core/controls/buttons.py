# -*- encoding: utf-8 -*-
"""
archie.ui.controls module

This module contains the an icon right button control
"""
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel
from PySide6.QtGui import QIcon, QCursor
from PySide6.QtCore import Qt, Signal, QPoint


class IconRightButton(QWidget):
    clicked = Signal()

    def __init__(self, text, icon=None, parent=None):
        super().__init__(parent)

        self.menu = None
        self.text = text

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 5)
        layout.setSpacing(5)

        # Add text
        self.text_label = QLabel(text)
        layout.addWidget(self.text_label, stretch=0)

        # Add icon
        if icon:
            self.icon_label = QLabel()
            if isinstance(icon, QIcon):
                pixmap = icon.pixmap(28, 28)
            else:
                pixmap = icon
            self.icon_label.setPixmap(pixmap)
            layout.addWidget(self.icon_label, stretch=1)

        # Make it look and behave like a button
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setStyleSheet("""
            IconRightButton {
                background-color: transparent;
                font-size: 16px;
                color: #383838;
                border: none;
                text-align: left;
                padding-left: 10px;
                padding-top: 0px;  /* Make room for icon */
            }
            QLabel {
                border: none;
            }
            IconRightButton:hover {
                background-color: #34495e;
                border-radius: 4px;
                
            }
            QLabel {
                font-size: 16px;
                color: #383838;
                background-color: transparent;
                border: none;
            }
        """)

    def set_text(self, text):
        self.text_label.setText(text)
        self.text = text

    def set_menu(self, menu):
        """Set a menu to be displayed when the button is clicked"""
        self.menu = menu

    def show_menu(self):
        """Show the popup menu at the appropriate position"""
        if self.menu:
            # Calculate position below the button
            pos = self.mapToGlobal(QPoint(self.text_label.width(), self.height()))
            self.menu.exec(pos)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self.menu:
                self.show_menu()
            else:
                self.clicked.emit()