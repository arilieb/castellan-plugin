# -*- encoding: utf-8 -*-
"""
archie.controls.spinner module

A customizable waiting/loading spinner widget for PySide6
Based on pyqtspinner but adapted for PySide6
"""
import math
from PySide6.QtCore import Qt, QTimer, QRect
from PySide6.QtGui import QPainter, QColor
from PySide6.QtWidgets import QWidget


class WaitingSpinner(QWidget):
    """
    A customizable animated spinner widget showing a loading/waiting indicator.
    """

    def __init__(
        self,
        parent=None,
        roundness=100.0,
        opacity=3.141592653589793,
        fade=80.0,
        radius=10,
        lines=20,
        line_length=10,
        line_width=20,
        speed=1.5707963267948966,
        color=(249, 115, 21),
    ):
        super().__init__(parent)

        self._roundness = roundness
        self._opacity = opacity
        self._fade_percentage = fade
        self._lines = lines
        self._line_length = line_length
        self._line_width = line_width
        self._inner_radius = radius
        self._current_counter = 0
        self._color = QColor(*color)

        # Calculate rotation speed (speed is in radians)
        # Convert to timer interval in milliseconds
        self._timer_interval = int(1000 / (speed * 10))

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._rotate)

        # Set widget properties
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # Set minimum size based on spinner dimensions
        spinner_size = int((self._inner_radius + self._line_length) * 2)
        self.setMinimumSize(spinner_size, spinner_size)

    def start(self):
        """Start the spinner animation"""
        self._timer.start(self._timer_interval)
        self.show()

    def stop(self):
        """Stop the spinner animation"""
        self._timer.stop()
        self.hide()

    def isSpinning(self):
        """Check if the spinner is currently animating"""
        return self._timer.isActive()

    def _rotate(self):
        """Rotate the spinner by one step"""
        self._current_counter += 1
        if self._current_counter >= self._lines:
            self._current_counter = 0
        self.update()

    def paintEvent(self, event):
        """Paint the spinner"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Calculate dimensions
        width = self.width()
        height = self.height()

        # Center the spinner
        painter.translate(width / 2, height / 2)

        # Draw each line
        for i in range(self._lines):
            # Calculate opacity based on position
            adjusted_index = (self._current_counter + i) % self._lines
            line_opacity = 1.0 - (adjusted_index / self._lines) * (self._fade_percentage / 100.0)

            # Set line color with opacity
            color = QColor(self._color)
            color.setAlphaF(line_opacity * (self._opacity / math.pi))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)

            # Rotate to line position
            painter.save()
            painter.rotate(360.0 * i / self._lines)

            # Calculate line rectangle
            line_rect = QRect(
                int(self._inner_radius),
                int(-self._line_width / 2),
                int(self._line_length),
                int(self._line_width)
            )

            # Draw rounded rectangle for the line
            painter.drawRoundedRect(
                line_rect,
                self._roundness,
                self._roundness,
                Qt.SizeMode.RelativeSize
            )

            painter.restore()

    def sizeHint(self):
        """Return the recommended size for the widget"""
        size = int((self._inner_radius + self._line_length) * 2)
        from PySide6.QtCore import QSize
        return QSize(size, size)