# -*- encoding: utf-8 -*-
"""
archie.ui.menubar module

This module contains the Conversation class for managing conversation UI.
"""
import qtawesome as qta
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QHBoxLayout, QFrame, QMenu

from .controls.buttons import IconRightButton


class TopBar(QFrame):
    def __init__(self, parent=None, text: str=""):
        super(TopBar, self).__init__(parent)

        self.conversation_ui = parent
        self.setAutoFillBackground(True)
        self.setStyleSheet("""
            QWidget {
                background-color: #d8d8d8;
                border-bottom: 1px solid #c8c8c8;
                padding: 0px 0px 0px 0px;
                margin: 0px;
            }
        """)
        # self.setStyleSheet("background-color: red")
        self.setFixedHeight(45)
        self.setContentsMargins(0, 0, 0, 0)

        self.layout = QHBoxLayout(self)
        self.title_btn = IconRightButton(text, qta.icon("mdi.chevron-down", color="#383838"))
        file_menu = QMenu(self)
        file_menu.setStyleSheet("""
            QMenu {
                padding: 4px 0px 4px 0px;
                border-radius: 6px;
                icon-size: 28px;
            }
            QMenu::icon {
                padding-left: 15px;
            }            
            QMenu::item#delete_action {
                color: #a31d1d;
            }
            QMenu::item {
                color: #383838;
                font-size: 16px;
                padding: 7px 60px 4px 8px;
                text-align: left;
            }
            QMenu::item:selected {
                background-color: #e6e6e6;
            }
        """)
        rename_action = QAction(qta.icon("mdi6.rename-outline", color="#383838"), "Rename", self)
        rename_action.triggered.connect(self.rename_conversation)
        file_menu.addAction(rename_action)
        file_menu.addSeparator()
        delete_action = QAction(qta.icon("mdi6.delete-outline", color="#a31d1d"), "Delete", self)
        delete_action.setObjectName("delete_action")
        delete_action.triggered.connect(self.delete_conversation)
        file_menu.addAction(delete_action)
        self.title_btn.set_menu(file_menu)
        self.title_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.title_btn.setFixedHeight(30)

        self.layout.addWidget(self.title_btn)
        self.title_btn.setVisible(len(text) > 0)


    def set_text(self, text: str):
        self.title_btn.set_text(text)
        self.title_btn.setVisible(len(text) > 0)

    def rename_conversation(self):
        self.conversation_ui.rename_conversation(None, name=self.title_btn.text)

    def delete_conversation(self):
        self.conversation_ui.delete_conversation(None)
