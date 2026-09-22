from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QLabel
from PySide6.QtCore import Signal, Qt


class ClickableLabel(QLabel):
    clicked = Signal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))  # Optional: show hand cursor

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()