# -*- encoding: utf-8 -*-
"""
archie.controls.carousel module

This module contains the Carousel control

"""

import qtawesome as qta
from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve, QSize
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QPushButton, QStackedWidget, QFrame


class PermissionCarousel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.seen = set()
        self.seen.add(0)
        layout = QHBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(""" 
            #PermissionCarousel {
                background: transparent;
                border: none;
            }
            QFrame#Card {
                background: #FFFFFF;            
                border-radius: 12px;
                border: 0px solid transparent;
            }
            QPushButton#direction {
                background-color: transparent;
                color: #ec6f27;
                border: none;
                border-radius: 8px;
                padding: 4px;
            }
            QPushButton#direction:hover {
                border: 1px solid #ec6f27;
            }
            QPushButton#direction:disabled {
                color: #d8d8d8;
            }
        """)

        # Stacked widget
        self.stack = QStackedWidget()
        self.stack.setStyleSheet("""
            QStackedWidget {
                background-color: transparent;
                border-radius: 12px;
                border: 0px solid transparent;
            }
        """)
        self.stack.setContentsMargins(0, 0, 0, 0)
        self.setFixedWidth(748)

        # Indicators (dots)
        self.prev_layout = QVBoxLayout()
        self.prev_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.prev_layout.setSpacing(10)
        self.prev_layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(self.prev_layout)

        self.prev_btn = QPushButton("")
        self.prev_btn.setIcon(qta.icon("mdi6.chevron-left", color="#ec6f27"))
        self.prev_btn.setIconSize(QSize(50, 50))
        self.prev_btn.setObjectName("direction")
        self.prev_btn.clicked.connect(self.previous_slide)
        self.prev_btn.setEnabled(False)
        self.prev_layout.addWidget(self.prev_btn)

        layout.addStretch()
        layout.addWidget(self.stack, 1)
        layout.addStretch()

        self.next_layout = QVBoxLayout()
        self.next_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.next_layout.setSpacing(10)
        self.next_layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(self.next_layout)

        self.next_btn = QPushButton()
        self.next_btn.setIcon(qta.icon("mdi6.chevron-right", color="#ec6f27"))
        self.next_btn.setIconSize(QSize(50, 50))
        self.next_btn.setObjectName("direction")
        self.next_btn.clicked.connect(self.next_slide)

        self.next_layout.addWidget(self.next_btn)

        # Animation
        self.animation = QPropertyAnimation(self.stack, b"currentIndex")
        self.animation.setDuration(300)
        self.animation.setEasingCurve(QEasingCurve.Type.InOutQuad)

    def add_slide(self, widget):
        """Add a slide to the carousel"""
        self.stack.addWidget(widget)

    def next_slide(self):
        """Go to next slide"""
        current = self.stack.currentIndex()
        if current == self.stack.count() - 1:
            return

        next_index = (current + 1) % self.stack.count()
        self.go_to_slide(next_index)
        self.seen.add(next_index)

        if next_index == self.stack.count() - 1:
            self.next_btn.setEnabled(False)
        else:
            self.next_btn.setEnabled(True)
        if next_index == 0:
            self.prev_btn.setEnabled(False)
        else:
            self.prev_btn.setEnabled(True)

    def previous_slide(self):
        """Go to previous slide"""
        current = self.stack.currentIndex()
        if current == 0:
            return

        prev_index = (current - 1) % self.stack.count()
        self.go_to_slide(prev_index)
        if prev_index == 0:
            self.prev_btn.setEnabled(False)
        else:
            self.prev_btn.setEnabled(True)
        if prev_index == self.stack.count() - 1:
            self.next_btn.setEnabled(False)
        else:
            self.next_btn.setEnabled(True)

    def go_to_slide(self, index):
        """Go to specific slide"""
        if 0 <= index < self.stack.count():
            self.stack.setCurrentIndex(index)
