# -*- encoding: utf-8 -*-
"""
archie.ui.document_widgets module

Custom QWidget classes that use QTextDocument for rendering text content.
"""

import logging
import platform
import re
from PySide6.QtCore import Qt, QTimer, QSize, QRectF
import qtawesome as qta
from PySide6.QtGui import (
    QTextDocument,
    QPalette,
    QPainter,
    QAbstractTextDocumentLayout,
    QColor,
    QPainterPath,
    QAction
)
from PySide6.QtWidgets import QWidget, QSizePolicy, QTextBrowser, QVBoxLayout, QMenu, QApplication

logger = logging.getLogger(__name__)


class PlainTextDocumentWidget(QWidget):
    """
    A custom widget that uses QTextDocument to render plain text content.
    This provides better control and performance than QLabel for user messages.
    """

    def __init__(self, text="", parent=None):
        super().__init__(parent)

        # Store parent conversation widget to get available width
        self.conversation_parent = None

        # Create the QTextDocument
        self.document = QTextDocument(self)
        self.document.setDocumentMargin(0)

        # Set plain text content (not markdown)
        self.document.setPlainText(text)

        # Store the text for later recalculation
        self.text_content = text

        # Configure size policy - allow widget to size to content
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        # Will be calculated after widget is added to layout
        self.needs_size_calculation = True

        # Enable context menu
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)


    def _show_context_menu(self, position):
        """Show context menu with copy option"""
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: white;
                padding: 4px 0px 4px 0px;
                border-radius: 6px;
                icon-size: 24px;
            }
            QMenu::icon {
                padding-left: 15px;
            }
            QMenu::item {
                color: #383838;
                font-size: 14px;
                padding: 7px 8px 4px 8px;
                text-align: left;
            }
            QMenu::item:selected {
                background-color: #e6e6e6;
            }
        """)

        # Create copy action with icon
        copy_action = QAction(qta.icon("mdi6.content-copy", color="#383838"), "Copy", self)
        copy_action.triggered.connect(self._copy_text)
        menu.addAction(copy_action)

        # Show the menu at the cursor position
        menu.exec(self.mapToGlobal(position))

    def _copy_text(self):
        """Copy the text content to clipboard"""
        clipboard = QApplication.clipboard()
        clipboard.setText(self.text_content)

    def mousePressEvent(self, event):
        """Handle mouse press events for context menu"""
        if event.button() == Qt.MouseButton.RightButton:
            # The customContextMenuRequested signal will handle this
            pass
        super().mousePressEvent(event)

    def showEvent(self, event):
        """Called when widget is shown - calculate size based on available width"""
        super().showEvent(event)
        if self.needs_size_calculation:
            self._calculate_optimal_size()
            self.needs_size_calculation = False

    def _get_available_width(self):
        """Get the available width from the conversation area"""
        # Try to find the conversation scroll area width
        parent = self.parent()
        while parent:
            if hasattr(parent, 'width'):
                width = parent.width()
                if width > 0:
                    # Account for padding and margins (120px total from padded_container)
                    return width - 120
            parent = parent.parent()
        # Fallback to a reasonable default
        return 1200

    def _calculate_optimal_size(self):
        """Calculate and set optimal widget size based on text content and available space"""
        # Get available width (half of conversation area)
        available_width = self._get_available_width()
        min_wrap_width = available_width // 2  # Only wrap if text exceeds half screen width
        max_width = 600  # Maximum bubble width
        padding = 20  # 10px padding on each side

        # Calculate text width by asking the document directly
        # Set document to full width first to get unwrapped size
        if platform.system() == "Windows":
            self.document.setTextWidth(-1)  # -1 means no wrapping
            doc_ideal_size = self.document.size()
            text_width = int(doc_ideal_size.width())
        else:
            # Calculate text width with no wrapping
            font_metrics = self.fontMetrics()
            text_width = font_metrics.horizontalAdvance(self.text_content)

        logger.debug("=" * 80)
        logger.debug(f"PlainTextDocumentWidget._calculate_optimal_size()")
        logger.debug(f"Text content: '{self.text_content[:50]}{'...' if len(self.text_content) > 50 else ''}'")
        logger.debug(f"Text length: {len(self.text_content)} characters")
        logger.debug(f"available_width: {available_width}px")
        logger.debug(f"min_wrap_width: {min_wrap_width}px")
        logger.debug(f"max_width: {max_width}px")
        logger.debug(f"padding: {padding}px")
        logger.debug(f"text_width (from document.size with no wrap): {text_width}px")

        # Determine if we need to wrap
        if text_width + padding <= min_wrap_width:
            # Text fits without wrapping - size to content
            widget_width = text_width + padding
            self.setFixedWidth(widget_width)
            self.document.setTextWidth(widget_width - padding)
            logger.debug(f"NO WRAP: text_width + padding ({text_width + padding}) <= min_wrap_width ({min_wrap_width})")
            logger.debug(f"Setting widget_width to: {widget_width}px")
            logger.debug(f"Setting document.setTextWidth to: {widget_width - padding}px")
        else:
            # Text is long enough to wrap - use up to max_width
            wrap_width = min(max(text_width + padding, min_wrap_width), max_width)
            widget_width = wrap_width
            self.setFixedWidth(widget_width)
            self.document.setTextWidth(widget_width - padding)
            logger.debug(f"WRAP: text_width + padding ({text_width + padding}) > min_wrap_width ({min_wrap_width})")
            logger.debug(f"wrap_width calculation: {wrap_width}px")
            logger.debug(f"Setting widget_width to: {widget_width}px")
            logger.debug(f"Setting document.setTextWidth to: {widget_width - padding}px")

        # Now calculate and set the height based on the wrapped content
        doc_size = self.document.size()
        height = int(doc_size.height()) + padding  # Add padding (10px top + 10px bottom)

        logger.debug(f"Document size after setTextWidth: {doc_size.width()}px x {doc_size.height()}px")
        logger.debug(f"Final widget dimensions: {widget_width}px x {height}px")
        logger.debug(f"Actual widget width after setFixedWidth: {self.width()}px")
        logger.debug(f"Widget sizeHint: {self.sizeHint().width()}px x {self.sizeHint().height()}px")
        logger.debug("=" * 80)

        self.setFixedHeight(height)

    def setPlainText(self, text):
        """Set the plain text content of the document"""
        self.text_content = text
        self.document.setPlainText(text)
        self._calculate_optimal_size()
        self.updateGeometry()
        self.update()

    def sizeHint(self):
        """Calculate the ideal size based on document content"""
        # Get document size
        doc_size = self.document.size()

        # Width is already set in _calculate_optimal_size
        width = self.width() if self.width() > 0 else int(doc_size.width()) + 20

        # Height is based on document height plus padding
        height = int(doc_size.height()) + 20  # 10px padding top and bottom

        return QSize(width, height)

    def minimumSizeHint(self):
        """Return minimum size hint"""
        doc_size = self.document.size()
        return QSize(int(doc_size.width()) + 20, int(doc_size.height()) + 20)

    def paintEvent(self, event):
        """Paint the document content with background"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Draw rounded rectangle background
        background_rect = QRectF(0, 0, self.width(), self.height())
        path = QPainterPath()
        path.addRoundedRect(background_rect, 18, 18)  # 18px border radius

        # Fill with background color
        painter.fillPath(path, QColor("#F5F5F5"))

        # Set up the document layout context
        context = QAbstractTextDocumentLayout.PaintContext()

        # Set text color
        context.palette.setColor(QPalette.ColorRole.Text, QColor("#191C20"))

        # Translate painter to add padding (10px from edges)
        painter.translate(10, 10)

        # Draw the document
        self.document.documentLayout().draw(painter, context)

    def resizeEvent(self, event):
        """Handle resize events to update document layout"""
        super().resizeEvent(event)
        self.updateGeometry()

class MarkdownDocumentWidget(QWidget):
    """
    A custom widget that uses QTextDocument to render markdown content.
    This provides better control and performance than QTextEdit for read-only content.
    """

    def __init__(self, markdown_text="", parent=None, enable_typewriter=False):
        super().__init__(parent)

        # Typewriter effect properties
        self.enable_typewriter = enable_typewriter
        self.full_text = markdown_text
        self.current_position = 0
        self.typewriter_timer = None
        self.full_html = None  # Will store the complete HTML after initial render

        # Configure size policy
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        # Set minimum and maximum widths
        self.setMinimumWidth(750)
        self.setMaximumWidth(1200)

        # Create the text browser for selectable text
        self.text_browser = QTextBrowser()
        self.text_browser.setReadOnly(True)
        self.text_browser.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse |
            Qt.TextInteractionFlag.TextSelectableByKeyboard |
            Qt.TextInteractionFlag.LinksAccessibleByMouse |
            Qt.TextInteractionFlag.LinksAccessibleByKeyboard
        )

        # Remove borders and scrollbars
        self.text_browser.setFrameStyle(0)
        self.text_browser.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.text_browser.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # Set custom context menu policy
        self.text_browser.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.text_browser.customContextMenuRequested.connect(self._show_context_menu)

        # Set document stylesheet to ensure consistent paragraph spacing
        # Apply consistent margins to all block elements
        stylesheet = """
            p { margin-top: 0.5em; margin-bottom: 0.5em; line-height: 1.3; }
            h1 { margin-top: 0.8em; margin-bottom: 0.5em; }
            h2 { margin-top: 0.7em; margin-bottom: 0.5em; }
            h3 { margin-top: 0.6em; margin-bottom: 0.5em; }
            h4 { margin-top: 0.5em; margin-bottom: 0.5em; }
            h5 { margin-top: 0.5em; margin-bottom: 0.5em; }
            h6 { margin-top: 0.5em; margin-bottom: 0.5em; }
            ul { margin-top: 0.5em; margin-bottom: 0.5em; }
            ol { margin-top: 0.5em; margin-bottom: 0.5em; }
            li { margin-top: 0.2em; margin-bottom: 0.2em; }
            pre { margin-top: 0.5em; margin-bottom: 0.5em; }
            blockquote { margin-top: 0.5em; margin-bottom: 0.5em; }
        """
        self.text_browser.document().setDefaultStyleSheet(stylesheet)

        # Set the markdown content
        # Always render full markdown to get proper spacing, even for typewriter
        self.text_browser.setMarkdown(markdown_text)

        # Clean inline styles that Qt adds (applies to both typewriter and loaded conversations)
        html = self.text_browser.document().toHtml()

        logger.debug("=== LOADED CONVERSATION HTML BEFORE CLEANING ===")
        logger.debug(f"HTML excerpt (first 500 chars): {html[:500]}")

        html = clean_qt_inline_styles(html)

        logger.debug("=== LOADED CONVERSATION HTML AFTER CLEANING ===")
        logger.debug(f"HTML excerpt (first 500 chars): {html[:500]}")

        self.text_browser.setHtml(html)

        # For typewriter effect, we'll store the full HTML and reveal it character by character
        if enable_typewriter:
            self.full_html = self.text_browser.document().toHtml()
            self.text_browser.setHtml("")  # Start with empty content

        # Style the text browser
        self.text_browser.setStyleSheet("""
            QTextBrowser {
                background-color: transparent;
                border: none;
                padding: 15px;
                color: #191C20;
                font-size: 15px
            }
            QTextBrowser::selection {
                background-color: #B3D7FF;
                color: #000000;
            }
        """)

        # Create layout and add text browser
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.text_browser)

    def _show_context_menu(self, position):
        """Show context menu with copy option"""
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: white;
                padding: 4px 0px 4px 0px;
                border-radius: 6px;
                icon-size: 24px;
            }
            QMenu::icon {
                padding-left: 15px;
            }
            QMenu::item {
                color: #383838;
                font-size: 14px;
                padding: 7px 8px 4px 8px;
                text-align: left;
            }
            QMenu::item:selected {
                background-color: #e6e6e6;
            }
        """)

        # Create copy action with icon
        copy_action = QAction(qta.icon("mdi6.content-copy", color="#383838"), "Copy", self)
        copy_action.triggered.connect(self._copy_text)
        menu.addAction(copy_action)

        # Show the menu at the cursor position (map from text_browser to global)
        menu.exec(self.text_browser.mapToGlobal(position))

    def _copy_text(self):
        """Copy the selected text or full content to clipboard"""
        cursor = self.text_browser.textCursor()
        if cursor.hasSelection():
            # Copy selected text
            selected_text = cursor.selectedText()
            clipboard = QApplication.clipboard()
            clipboard.setText(selected_text)
        else:
            # Copy full text if nothing is selected
            clipboard = QApplication.clipboard()
            clipboard.setText(self.full_text)

    def setMarkdown(self, markdown_text):
        """Set the markdown content of the document"""
        self.full_text = markdown_text
        self.text_browser.setMarkdown(markdown_text)

        # Qt's setMarkdown adds inline styles that override our stylesheet
        # Remove those inline margin styles to allow stylesheet to take effect
        html = self.text_browser.document().toHtml()
        html = clean_qt_inline_styles(html)
        self.text_browser.setHtml(html)

        self.updateGeometry()
        self.update()

    def start_typewriter_effect(self, on_scroll_callback=None):
        """
        Start the typewriter effect animation.

        Args:
            on_scroll_callback: Callback function to trigger scrolling
        """
        if not self.enable_typewriter or not self.full_text:
            return

        self.on_scroll_callback = on_scroll_callback
        self.char_count = 0  # Track characters for scroll triggering

        # Start the timer for typewriter effect
        self.typewriter_timer = QTimer(self)
        self.typewriter_timer.timeout.connect(self._typewriter_step)
        self.typewriter_timer.start(5)  # Update every 5ms for smooth effect

    def _typewriter_step(self):
        """Execute one step of the typewriter effect"""
        if self.current_position < len(self.full_text):
            # Add one character at a time from the original markdown text
            self.current_position += 1
            current_markdown = self.full_text[:self.current_position]

            # Set document width BEFORE setting markdown to ensure proper line spacing
            width = self.width() if self.width() > 0 else self.minimumWidth()
            self.text_browser.document().setTextWidth(width - 30)

            # Render the partial markdown
            self.text_browser.setMarkdown(current_markdown)

            # Qt's setMarkdown adds inline styles that override our stylesheet
            # We need to remove those inline margin/line-height styles
            html = self.text_browser.document().toHtml()

            if self.current_position == len(self.full_text):  # Only log on last character
                logger.debug("=== TYPEWRITER HTML BEFORE CLEANING ===")
                logger.debug(f"HTML excerpt (first 500 chars): {html[:500]}")

            html = clean_qt_inline_styles(html)

            if self.current_position == len(self.full_text):  # Only log on last character
                logger.debug("=== TYPEWRITER HTML AFTER CLEANING ===")
                logger.debug(f"HTML excerpt (first 500 chars): {html[:500]}")

            # Set the cleaned HTML back
            self.text_browser.setHtml(html)

            # Update widget size and trigger repaint
            self.setFixedHeight(self.sizeHint().height())
            self.update()

            # Track character count for scroll triggering
            self.char_count += 1

            # Trigger scroll every 10 characters
            if self.char_count >= 10 and self.on_scroll_callback:
                self.on_scroll_callback()
                self.char_count = 0
        else:
            # Animation complete
            if self.typewriter_timer:
                self.typewriter_timer.stop()
                self.typewriter_timer = None

            # Final scroll to ensure we're at the bottom
            if self.on_scroll_callback:
                self.on_scroll_callback()

    def sizeHint(self):
        """Calculate the ideal size based on document content"""
        # Set document width to match widget width
        width = self.width() if self.width() > 0 else self.minimumWidth()
        self.text_browser.document().setTextWidth(width - 30)  # Account for padding

        # Get the document size
        doc_size = self.text_browser.document().size()
        height = int(doc_size.height()) + 30  # Add padding

        return QSize(width, max(height, 50))

    def minimumSizeHint(self):
        """Return minimum size hint"""
        return QSize(self.minimumWidth(), 50)


def clean_qt_inline_styles(html):
    """
    Remove inline styles that Qt adds when rendering markdown.

    This function removes margin, font-size, and font-weight inline styles
    to allow stylesheet rules to take precedence.

    Args:
        html: The HTML string to clean

    Returns:
        The cleaned HTML string with inline styles removed
    """
    html = re.sub(r'margin-top:\s*\d+px;?', '', html)
    html = re.sub(r'margin-bottom:\s*\d+px;?', '', html)
    html = re.sub(r'margin-left:\s*\d+px;?', '', html)
    html = re.sub(r'margin-right:\s*\d+px;?', '', html)
    html = re.sub(r'font-size:\s*\d+(?:px|pt);?', '', html)
    html = re.sub(r'font-weight:\s*\d+;?', '', html)
    return html