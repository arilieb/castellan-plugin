# -*- encoding: utf-8 -*-
"""
archie.ui.conversation module

This module contains the Conversation class for managing conversation UI.
"""
import asyncio
import logging
import random

from PySide6.QtCore import Qt, QEvent, QTimer, QMargins, QPropertyAnimation, QEasingCurve, QRect, \
    QPoint, QEventLoop
from PySide6.QtGui import QTextOption
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QFrame,
    QScrollArea,
    QSizePolicy,
    QGraphicsOpacityEffect,
    QApplication, QDialog,
    QStackedWidget, QPlainTextEdit)
from qasync import asyncSlot
import qtawesome as qta
from .controls.carousel import PermissionCarousel
from .controls.labels import ClickableLabel
from .controls.spinner import WaitingSpinner
from .delete import ConfirmDeleteDialog
from .documents import PlainTextDocumentWidget, MarkdownDocumentWidget
from .permission import ToolConfirmationWidget
from .prompts import PromptMenu
from .rename import RenameDialog
from .topbar import TopBar

logger = logging.getLogger(__name__)

AGENT_PROMPT = """If there is an unfinished todo list in process, please continue processing the todo list,
                move on to the next step and update the todo list progress  **IMPORTANT** Please be sure to correctly use
                the results from previous tool calls in subsequent tool calls.  The value is in the content element
                of successful tool calls.  If there is no todo list or it is
                finished, please indicate that the current request has been satified."""


class SynchronizationUI(QWidget):
    """
    Manages the conversation UI including initial view, conversation view,
    prompt box, message handling, and prompt menu integration.
    """

    def __init__(self, parent=None, base_page=None, app=None):
        super().__init__(parent)

        self.app = app
        self.conversation_started = False
        self.base_page = base_page
        self.sidebar = None  # This will be set from the sidebar once it's created
        self.id = None

        # Main layout for this widget
        self.main_area_layout = QVBoxLayout(self)
        self.main_area_layout.setContentsMargins(0, 0, 0, 20)
        self.main_area_layout.setSpacing(0)

        self.top_bar = TopBar(self)
        self.main_area_layout.addWidget(self.top_bar)

        # Initialize prompt menu
        self.prompt_menu = PromptMenu(parent_widget=self, base_page=base_page)
        self.prompt_menu.on_prompt_selected_callback = self.on_prompt_selected

        self.prompt_box = None
        # Setup unified layout
        self.setup_unified_layout()

        # Wire up prompt menu to containers after setup
        self.prompt_menu.prompt_box = self.prompt_box
        self.prompt_menu.conversation_started = self.conversation_started

        # Create loading indicator
        self.loading_container = None
        self.loading_spinner = None
        self.loading_label = None

    def on_prompt_selected(self, prompt_text):
        """Callback when a prompt is selected from the menu."""
        self.text_edit.setPlainText(prompt_text)

    def setup_unified_layout(self):
        """Setup the unified layout with stacked content area and fixed prompt box"""
        # Create stacked widget for top content area
        self.content_stack = QStackedWidget()
        self.content_stack.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        # Page 0: Initial welcome view with prompt box
        self.welcome_page = self.create_welcome_page()
        self.content_stack.addWidget(self.welcome_page)

        # Page 1: Conversation view
        self.conversation_page = self.create_conversation_page()
        self.content_stack.addWidget(self.conversation_page)

        # Add stacked content to main layout
        self.main_area_layout.addWidget(self.content_stack, 1)

        # Add spacing
        self.main_area_layout.addSpacing(10)

        # Create bottom container for prompt box (used during conversation mode)
        self.bottom_input_container = QWidget()
        # Start with 0 height - will expand during animation
        self.bottom_input_container.setMinimumHeight(0)
        self.bottom_input_container.setMaximumHeight(0)
        self.bottom_input_container.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )

        self.bottom_input_layout = QVBoxLayout(self.bottom_input_container)
        self.bottom_input_layout.setContentsMargins(QMargins(60, 0, 60, 45))
        self.bottom_input_layout.addStretch()

        # Create centering layout for prompt box
        self.prompt_centering_layout = QHBoxLayout()
        self.prompt_centering_layout.setContentsMargins(0, 0, 0, 0)

        left_spacer = QWidget()
        right_spacer = QWidget()

        self.prompt_centering_layout.addWidget(left_spacer, 1)
        # Prompt box will be added here by create_welcome_page
        self.prompt_centering_layout.addWidget(right_spacer, 1)

        self.bottom_input_layout.addLayout(self.prompt_centering_layout)

        # Add bottom container to main layout
        self.main_area_layout.addWidget(self.bottom_input_container)

    def resizeEvent(self, event):
        """Handle window resize events."""
        super().resizeEvent(event)
        self.prompt_menu.handle_resize()

    def switch_to_conversation_view(self):
        """Switch from welcome view to conversation view with animation"""
        if not self.conversation_started:
            # Create opacity effect for welcome label fade out
            welcome_opacity_effect = QGraphicsOpacityEffect(self.welcome_label)
            self.welcome_label.setGraphicsEffect(welcome_opacity_effect)

            # Get current position of prompt box in absolute coordinates
            start_geometry = self.prompt_box.mapTo(self, QPoint(0, 0))
            start_rect = QRect(
                start_geometry.x(),
                start_geometry.y(),
                self.prompt_box.width(),
                self.prompt_box.height()
            )

            # Reparent welcome label to self for absolute positioning during animation
            # This keeps it visible when we switch the stack
            label_geometry = self.welcome_label.mapTo(self, QPoint(0, 0))
            self.welcome_label.setParent(self)
            self.welcome_label.move(label_geometry)
            self.welcome_label.show()
            self.welcome_label.raise_()

            # Reparent prompt box to self for absolute positioning during animation
            self.prompt_box.setParent(self)
            self.prompt_box.setGeometry(start_rect)
            self.prompt_box.show()
            self.prompt_box.raise_()

            # Create welcome label fade animation
            self.welcome_fade_animation = QPropertyAnimation(welcome_opacity_effect, b"opacity")
            self.welcome_fade_animation.setDuration(400)
            self.welcome_fade_animation.setStartValue(1.0)
            self.welcome_fade_animation.setEndValue(0.0)
            self.welcome_fade_animation.setEasingCurve(QEasingCurve.Type.InOutQuad)

            # Start fade animation immediately
            self.welcome_fade_animation.start()

            # Switch the layout (now safe since label is reparented)
            self.content_stack.setCurrentIndex(1)
            self.conversation_started = True
            self.prompt_menu.conversation_started = True

            # Expand the bottom container to its final size
            self.bottom_input_container.setMinimumHeight(200)
            self.bottom_input_container.setMaximumHeight(16777215)  # Remove max height constraint

            # Force layout update to get final position
            self.bottom_input_container.updateGeometry()

            # Start animation after layout is settled
            QTimer.singleShot(50, lambda: self._start_prompt_slide_animation(start_rect))

    def _start_prompt_slide_animation(self, start_geometry):
        """Start the prompt box slide down animation"""
        # Calculate where the prompt box should end up in the bottom container
        # We need to figure out the final position by temporarily adding a dummy widget

        # Get bottom container position
        bottom_container_pos = self.bottom_input_container.mapTo(self, QPoint(0, 0))

        # Calculate final position based on layout margins and centering
        # The prompt box should be horizontally centered with 60px margins
        widget_width = self.width()
        prompt_width = start_geometry.width()

        # Account for the 60px left margin in bottom_input_layout
        final_x = (widget_width - prompt_width) // 2

        # The Y position should be at the bottom container position plus stretch spacing
        # Since we have addStretch() before the prompt, and the container has margins
        final_y = bottom_container_pos.y() + 10  # Small top padding from stretch

        # Calculate end geometry
        end_geometry = QRect(
            final_x,
            final_y,
            prompt_width,
            self.prompt_box.height()
        )

        # Keep prompt box as direct child during animation
        self.prompt_box.raise_()
        self.prompt_box.setGeometry(start_geometry)

        # Create geometry animation for prompt box sliding down
        self.prompt_box_animation = QPropertyAnimation(self.prompt_box, b"geometry")
        self.prompt_box_animation.setDuration(600)
        self.prompt_box_animation.setStartValue(start_geometry)
        self.prompt_box_animation.setEndValue(end_geometry)
        self.prompt_box_animation.setEasingCurve(QEasingCurve.Type.InOutCubic)

        # Clean up after animation finishes
        def on_animation_finished():
            # Hide welcome label completely
            self.welcome_label.hide()
            self.welcome_label.setGraphicsEffect(None)  # type: ignore

            # Now reparent the prompt box back to the layout for proper management
            # Remove from centering layout first
            for i in range(self.prompt_centering_layout.count()):
                item = self.prompt_centering_layout.itemAt(i)
                if item and item.widget() == self.prompt_box:
                    self.prompt_centering_layout.removeWidget(self.prompt_box)
                    break

            # Re-add to layout
            left_spacer = QWidget()
            right_spacer = QWidget()

            # Clear layout
            while self.prompt_centering_layout.count():
                item = self.prompt_centering_layout.takeAt(0)
                if item.widget():
                    w = item.widget()
                    if w != self.prompt_box:
                        w.setParent(None)

            # Rebuild layout with prompt box
            self.prompt_centering_layout.addWidget(left_spacer, 1)
            self.prompt_centering_layout.addWidget(self.prompt_box, 10)
            self.prompt_centering_layout.addWidget(right_spacer, 1)

        self.prompt_box_animation.finished.connect(on_animation_finished)

        # Start the animation
        self.prompt_box_animation.start()

    def _show_prompt_context_menu(self, pos):
        menu = self.text_edit.createStandardContextMenu()
        for action in menu.actions():
            action.setIconVisibleInMenu(action.isEnabled())
        menu.setStyleSheet("""
            QMenu {
                padding: 4px 0px;
                border-radius: 6px;
                icon-size: 24px;
            }
            QMenu::icon {
                padding-left: 15px;
            }
            QMenu::item {
                color: #383838;
                font-size: 14px;
                padding: 7px 12px 4px 12px;
                text-align: left;
            }
            QMenu::item:selected { background-color: #e6e6e6; }
            QMenu::item:disabled {
                color: #b0b0b0;
                background: transparent;
            }
            """)
        
        icon_map = {
            "Undo": "mdi6.undo-variant",
            "Redo": "mdi6.redo-variant",
            "Cut": "mdi6.content-cut",
            "Copy": "mdi6.content-copy",
            "Paste": "mdi6.content-paste",
            "Delete": "mdi6.delete-outline",
            "Select All": "mdi6.select-all"
        }
        for action in menu.actions():
            label = action.text().split("\t", 1)[0].replace("&", "")
            icon_name = icon_map.get(label)
            if icon_name:
                action.setIcon(qta.icon(icon_name, color="#383838"))

        menu.exec(self.text_edit.mapToGlobal(pos))

    def create_welcome_page(self):
        """Create the welcome page with centered label and prompt box"""
        welcome_widget = QWidget()
        welcome_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        welcome_layout = QVBoxLayout(welcome_widget)
        welcome_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        welcome_layout.setContentsMargins(60, 0, 60, 0)
        welcome_layout.setSpacing(30)

        # Welcome label
        self.welcome_label = QLabel("How can I help you secure your data?")
        self.welcome_label.setStyleSheet("font: 36px; color: #565656;")
        self.welcome_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.welcome_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        welcome_layout.addWidget(self.welcome_label)

        # Create prompt box and add to welcome layout
        self.create_prompt_box()

        # Create horizontal centering layout for prompt box
        prompt_h_layout = QHBoxLayout()
        prompt_h_layout.addStretch(1)
        prompt_h_layout.addWidget(self.prompt_box, 10)
        prompt_h_layout.addStretch(1)

        welcome_layout.addLayout(prompt_h_layout)

        return welcome_widget

    def create_conversation_page(self):
        """Create the conversation page with scrollable message area"""
        conversation_widget = QWidget()
        conversation_layout = QVBoxLayout(conversation_widget)
        conversation_layout.setContentsMargins(0, 0, 0, 0)

        self.conversation_scroll = QScrollArea()
        self.conversation_scroll.setWidgetResizable(True)
        self.conversation_scroll.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.conversation_scroll.setStyleSheet(
            """
            QScrollArea {
                border: none;
                background-color: transparent;
            }
            QScrollBar:vertical {
                background-color: transparent;
                width: 8px;
                border: none;
            }
            QScrollBar::handle:vertical {
                background-color: rgba(0, 0, 0, 0.3);
                border-radius: 4px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: rgba(0, 0, 0, 0.5);
            }
            QScrollBar::handle:vertical:pressed {
                background-color: rgba(0, 0, 0, 0.7);
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: transparent;
            }
        """
        )

        self.padded_container = QWidget()
        padded_container_layout = QHBoxLayout(self.padded_container)
        padded_container_layout.setContentsMargins(60, 0, 60, 0)

        self.conversation_widget = QWidget()
        self.conversation_layout = QVBoxLayout(self.conversation_widget)
        self.conversation_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.conversation_layout.setSpacing(10)

        padded_container_layout.addWidget(self.conversation_widget)
        self.conversation_scroll.setWidget(self.padded_container)
        conversation_layout.addWidget(self.conversation_scroll)

        return conversation_widget

    def create_prompt_box(self):
        """Create the prompt input box"""
        self.prompt_box = QFrame()
        self.prompt_box.setStyleSheet("background-color: #F7F8FF; border-radius: 10px;")
        self.prompt_box.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.prompt_box.setMinimumWidth(730)
        self.prompt_box.setMaximumWidth(16777215)

        self.prompt_box_layout = QVBoxLayout(self.prompt_box)
        self.prompt_box_layout.setContentsMargins(15, 10, 15, 10)
        self.prompt_box_layout.setSpacing(5)

        # Prompt text
        self.text_edit = QPlainTextEdit()
        self.text_edit.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.text_edit.customContextMenuRequested.connect(self._show_prompt_context_menu)
        self.text_edit.setPlaceholderText(
            "Ask a question or type '/' for a list of predefined prompts; hover over a prompt for more information."
        )
        self.text_edit.setStyleSheet(
            """
            QPlainTextEdit {
                font: 17px;
                color: #0e0e0e;
                padding-top: 10px;
                font-weight: 300;
                letter-spacing: 2px;
                border: none;
                background-color: transparent;
            }
            QScrollBar:vertical {
                background-color: transparent;
                width: 8px;
                border: none;
            }
            QScrollBar::handle:vertical {
                background-color: rgba(0, 0, 0, 0.3);
                border-radius: 4px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: rgba(0, 0, 0, 0.5);
            }
            QScrollBar::handle:vertical:pressed {
                background-color: rgba(0, 0, 0, 0.7);
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: transparent;
            }
        """
        )

        # Configure text wrapping and initial scrolling behavior
        self.text_edit.setWordWrapMode(QTextOption.WrapMode.WordWrap)
        self.text_edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.text_edit.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        # Store initial dimensions
        self.initial_prompt_height = 150
        self.initial_textedit_height = 105
        self.max_prompt_height = 300
        self.max_textedit_height = 255

        # Set initial height for text edit to ensure proper space allocation
        self.text_edit.setFixedHeight(self.initial_textedit_height)
        self.prompt_box.setFixedHeight(self.initial_prompt_height)

        self.text_edit.textChanged.connect(self.adjust_prompt_height)
        self.text_edit.textChanged.connect(self.on_input_changed)

        # Add text edit with stretch factor to take up available space
        self.prompt_box_layout.addWidget(self.text_edit, 1)

        # Up arrow container
        arrow_container = QWidget()
        arrow_container.setFixedHeight(25)
        arrow_layout = QHBoxLayout(arrow_container)
        arrow_layout.setContentsMargins(0, 0, 0, 0)
        arrow_layout.addStretch()

        # Install event filter to handle Enter key
        self.text_edit.installEventFilter(self)

        up_arrow = ClickableLabel("↑")
        up_arrow.setStyleSheet("font: 24px; color: #676767; padding-bottom: 5px;")
        up_arrow.setCursor(Qt.CursorShape.PointingHandCursor)
        up_arrow.clicked.connect(self.label_clicked)
        up_arrow.clicked.connect(self.on_query)
        arrow_layout.addWidget(up_arrow)

        self.prompt_box_layout.addWidget(arrow_container, 0)

    def eventFilter(self, obj, event):
        """Handle key events for the text edit"""
        if obj == self.text_edit and event.type() == QEvent.Type.KeyPress:
            # Check for Enter without Shift (Shift+Enter allows new lines)
            if event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter:
                if not event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    # Trigger the same logic as clicking the up arrow
                    self.label_clicked()
                    self.on_query()
                    return True  # Event handled, don't insert newline

        return super().eventFilter(obj, event)

    def adjust_prompt_height(self):
        """Adjust the height of the prompt box based on content"""
        # Get the current document and set its text width to match the text edit's width
        document = self.text_edit.document()

        # Set the document's text width to match the actual available width in the text edit
        available_width = self.text_edit.viewport().width()
        document.setTextWidth(available_width)

        # Get the content height after setting the proper text width
        content_height = document.size().height()

        # Calculate the height changes
        old_prompt_height = self.prompt_box.height()

        # Only start expanding if content exceeds the initial height
        if content_height <= self.initial_textedit_height:
            # Content fits in initial size - keep original dimensions
            new_prompt_height = self.initial_prompt_height
            new_textedit_height = self.initial_textedit_height
            self.text_edit.setVerticalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            )
        else:
            # Content exceeds initial size - calculate new height
            needed_textedit_height = int(content_height)

            if needed_textedit_height <= self.max_textedit_height:
                # Content fits within expansion limit - resize
                new_textedit_height = needed_textedit_height
                new_prompt_height = (
                        new_textedit_height + 45
                )  # Add padding + arrow space
                self.text_edit.setVerticalScrollBarPolicy(
                    Qt.ScrollBarPolicy.ScrollBarAlwaysOff
                )
            else:
                # Content exceeds max height - stop expanding and enable scroll
                new_textedit_height = self.max_textedit_height
                new_prompt_height = self.max_prompt_height
                self.text_edit.setVerticalScrollBarPolicy(
                    Qt.ScrollBarPolicy.ScrollBarAsNeeded
                )

        # Set the new heights
        self.text_edit.setFixedHeight(new_textedit_height)
        self.prompt_box.setFixedHeight(new_prompt_height)

        # If we're in conversation view, adjust the bottom container height to accommodate growth
        if self.conversation_started:
            height_change = new_prompt_height - old_prompt_height
            if height_change != 0:
                current_container_height = self.bottom_input_container.height()
                new_container_height = max(
                    200, current_container_height + height_change
                )
                self.bottom_input_container.setMinimumHeight(new_container_height)
                # Force a layout update
                self.bottom_input_container.updateGeometry()
                self.scroll_to_bottom()

    def on_input_changed(self):
        """Handle prompt filtering logic by delegating to PromptMenu."""
        input_value = self.text_edit.toPlainText()
        # Update the prompt menu's padded_container reference
        self.prompt_menu.padded_container = self.padded_container
        self.prompt_menu.conversation_started = self.conversation_started
        self.prompt_menu.on_input_changed(input_value)

    @asyncSlot()
    async def on_query(self):
        # self.sidebar.set_thinking(True)
        query = self.text_edit.toPlainText().strip()
        if not query:
            return

        # Clear the input immediately
        self.text_edit.clear()

        if self.conversation_layout.count() == 0:
            self.switch_to_conversation_view()
            self.add_message_to_conversation(query, message_type="user")
            await asyncio.sleep(0.6)  # Non-blocking wait
            self.setLoading(True)

            conversation = await self.app.new_conversation()
            self.id = conversation.id
            await self.sidebar.update_conversations(reselect=True, conversation_id=self.id)
        else:
            self.add_message_to_conversation(query, message_type="user")
            await asyncio.sleep(1)
            self.setLoading(True)
            # Non-blocking wait

        conversation = await self.app.send_query(query, self.id)

        await self.sidebar.update_conversations(reselect=True, conversation_id=self.id)
        self.top_bar.set_text(conversation.title)

        # Hide loading spinner
        self.setLoading(False)

        # Investigate error here if the first query results in a validation error
        (user_query, agent_response) = conversation.history[-2:]
        agent_response_idx = len(conversation.history) - 1

        # Here we need to search through the conversation history and find all agent responses that exist after the
        # last user query.
        self.add_message_to_conversation(agent_response.content, message_type="agent", todo_list=agent_response.todo_list)

        # Add any tool calls
        if agent_response.tool_calls:
            if len(agent_response.tool_calls) == 1:
                tool_call = agent_response.tool_calls[0]
                self._add_tool_call_widget(tool_call, agent_response_idx, 0, 1)
                if (response_content := tool_call.response_content) is not None:
                    self.add_message_to_conversation(message=response_content, message_type="agent",
                                                     enable_typewriter=False)
            elif len(agent_response.tool_calls) > 1:
                self.add_tool_call_widgets(agent_response.tool_calls, agent_response_idx)
                for tool_call in agent_response.tool_calls:
                    if (response_content := tool_call.response_content) is not None:
                        self.add_message_to_conversation(message=response_content, message_type="agent",
                                                         enable_typewriter=False)

    @asyncSlot()
    async def add_agent_query(self, query):

        conversation = await self.app.send_query(query, self.id, "agent")

        await self.sidebar.update_conversations()

        # Hide loading spinner
        self.setLoading(False)

        # Investigate error here if the first query results in a validation error
        (user_query, agent_response) = conversation.history[-2:]
        agent_response_idx = len(conversation.history) - 1

        # Here we need to search through the conversation history and find all agent responses that exist after the
        # last user query.
        self.add_message_to_conversation(agent_response.content, message_type="agent")

        if agent_response.tool_calls:
            if len(agent_response.tool_calls) == 1:
                tool_call = agent_response.tool_calls[0]
                self._add_tool_call_widget(tool_call, agent_response_idx, 0, 1)
                if (response_content := tool_call.response_content) is not None:
                    self.add_message_to_conversation(message=response_content, message_type="agent",
                                                     enable_typewriter=False)
            elif len(agent_response.tool_calls) > 1:
                self.add_tool_call_widgets(agent_response.tool_calls, agent_response_idx)
                for tool_call in agent_response.tool_calls:
                    if (response_content := tool_call.response_content) is not None:
                        self.add_message_to_conversation(message=response_content, message_type="agent",
                                                         enable_typewriter=False)

        # self.sidebar.set_thinking(False)

    def add_message_to_conversation(self, message, message_type="user", todo_list=None, animate=True, **kwargs):
        """Add a message to the conversation area"""
        message_widget = QFrame()
        message_widget.setStyleSheet("background-color: transparent; border: none;")
        message_layout = QHBoxLayout(message_widget)
        message_layout.setContentsMargins(20, 10, 20, 10)

        if message_type == "user":
            # User messages use PlainTextDocumentWidget with QTextDocument
            text_widget = PlainTextDocumentWidget(message)

            # Apply styling to the widget
            text_widget.setStyleSheet(
                """
                PlainTextDocumentWidget {
                    background-color: #F5F5F5;
                    color: #191C20;
                    border-radius: 10px;
                    font-size: 14px;
                }
            """
            )

            # Use QTimer to ensure proper sizing after layout
            QTimer.singleShot(0, lambda: text_widget.setFixedHeight(text_widget.sizeHint().height()))

            message_layout.addWidget(text_widget)

            # Add the message to the conversation layout
            self.conversation_layout.addWidget(message_widget, 0, Qt.AlignmentFlag.AlignRight)


            logger.debug("=" * 80)
            logger.debug(f"USER MESSAGE LAYOUT DEBUG")
            logger.debug(f"message_widget geometry: {message_widget.geometry()}")
            logger.debug(f"message_widget width: {message_widget.width()}px")
            logger.debug(f"message_widget sizeHint: {message_widget.sizeHint()}")
            logger.debug(f"message_layout contentsMargins: {message_layout.contentsMargins()}")
            logger.debug(f"text_widget geometry: {text_widget.geometry()}")
            logger.debug(f"text_widget width: {text_widget.width()}px")
            logger.debug(f"text_widget sizeHint: {text_widget.sizeHint()}")
            logger.debug(f"text_widget minimumWidth: {text_widget.minimumWidth()}px")
            logger.debug(f"text_widget maximumWidth: {text_widget.maximumWidth()}px")
            logger.debug(f"text_widget sizePolicy: H={text_widget.sizePolicy().horizontalPolicy()}, V={text_widget.sizePolicy().verticalPolicy()}")
            logger.debug("=" * 80)


            # Animate the user message sliding in from the right (only if  animate=True)
            if animate:
                self._animate_message_fade_in(message_widget)  # type: ignore

        elif message_type == "agent":
            # Check if we should enable typewriter (enabled for new messages, not historical ones)
            enable_typewriter = kwargs.get("enable_typewriter", True)

            # Create custom markdown widget using QTextDocument
            markdown_widget = MarkdownDocumentWidget(message, enable_typewriter=enable_typewriter)

            message_layout.addWidget(markdown_widget)
            message_layout.addStretch()

            # Add the message to the conversation layout
            self.conversation_layout.addWidget(message_widget)

            # Start typewriter effect if enabled
            if enable_typewriter:
                # Use QTimer to start typewriter effect after widget is added to layout
                QTimer.singleShot(50, lambda: markdown_widget.start_typewriter_effect(
                    on_scroll_callback=self.scroll_to_bottom
                ))
            else:
                # For historical messages, set height immediately
                QTimer.singleShot(0, lambda: markdown_widget.setFixedHeight(markdown_widget.sizeHint().height()))

        elif message_type == "permission":
            # message: dict like {"toolName": "...", "toolTitle": "...", "toolArgs": {...}, "sensitive_args": [...]}
            data = kwargs or {}
            tool_name = data.get("toolName", "")
            tool_title = data.get("toolTitle", "")
            tool_args = data.get("toolArgs", {}) or {}
            sensitive_args = data.get("sensitive_args", []) or []
            init_state = data.get("init_state", None)  # None, True, or False
            history_idx = data.get("history_idx", -1)
            tool_idx = data.get("tool_idx", -1)
            tool_count = data.get("tool_count", 0)
            tool_response = data.get("tool_response", None)

            perm_widget = ToolConfirmationWidget(
                tool_name=tool_name,
                tool_title=tool_title,
                tool_args=tool_args,
                on_yes=self.on_tool_allow,
                on_no=self.on_tool_deny,
                sensitive_args=sensitive_args,
                parent=message_widget,
                init_state=init_state,
                history_idx=history_idx,
                tool_idx=tool_idx,
                tool_count=tool_count,
                tool_response=tool_response
            )

            # Make it expand horizontally similarly to your agent message
            perm_widget.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum
            )
            message_layout.addWidget(perm_widget)
            message_layout.addStretch()

            # Add the message to the conversation layout
            self.conversation_layout.addWidget(message_widget)

        # Scroll to the bottom to show the latest message
        QTimer.singleShot(10, self.scroll_to_bottom)

    @asyncSlot()
    async def on_tool_allow(self, tool_name: str, history_idx, tool_idx, edited_args: dict):
        data = dict(
            tool_name=tool_name,
            tool_args=edited_args,
        )
        self.setLoading(True)
        QApplication.processEvents()
        tool_response = await self.app.process_tool_call(self.id, data, history_idx, tool_idx)
        if tool_response and "content" in tool_response[0] and tool_response[0]["content"]:
            self.add_message_to_conversation(message=tool_response[0]["content"], message_type="agent",
                                             enable_typewriter=False)

        if self.tool_calls_finished(history_idx):
            await self.add_agent_query(AGENT_PROMPT)

        self.setLoading(False)

        return tool_response

    @asyncSlot()
    async def on_tool_deny(self, history_idx, tool_idx):
        await self.app.deny_tool_call(self.id, history_idx, tool_idx)

        if self.tool_calls_finished(history_idx):
            await self.add_agent_query(AGENT_PROMPT)

        self.setLoading(False)

    def tool_calls_finished(self, history_idx):
        conversation = self.app.db.convs.get(self.id)

        history_item = conversation.history[history_idx]
        for tool_call in history_item.tool_calls:
            if tool_call.permission_granted is None:
                return False

        return True

    @staticmethod
    def _animate_message_fade_in(message_widget):
        """Animate a message widget sliding in from the right with fade"""
        # Create opacity effect for fade-in
        opacity_effect = QGraphicsOpacityEffect(message_widget)
        message_widget.setGraphicsEffect(opacity_effect)

        # Start with invisible
        opacity_effect.setOpacity(0.0)

        # Create opacity animation
        opacity_animation = QPropertyAnimation(opacity_effect, b"opacity")
        opacity_animation.setDuration(300)
        opacity_animation.setStartValue(0.0)
        opacity_animation.setEndValue(1.0)
        opacity_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        # Store animation reference to prevent garbage collection
        message_widget._opacity_animation = opacity_animation

        # Clean up after animation
        def on_finished():
            message_widget.setGraphicsEffect(None)
            if hasattr(message_widget, '_opacity_animation'):
                delattr(message_widget, '_opacity_animation')

        opacity_animation.finished.connect(on_finished)
        opacity_animation.start()

    @staticmethod
    def adjust_text_edit_height(text_edit):
        """Adjust the height of a QTextEdit to fit its content exactly"""
        # Get the actual width available for text
        available_width = text_edit.viewport().width()

        # Set the document's text width to match the viewport width
        document = text_edit.document()
        document.setTextWidth(available_width)

        # Force the document to layout with the current width
        document.adjustSize()

        # Get the document height and add minimal padding
        content_height = int(document.size().height())

        # Account for the padding in the stylesheet (15px top + 15px bottom = 30px)
        total_height = content_height + 30

        # Set a minimum height to prevent too-small text edits
        final_height = max(total_height, 50)

        # Set the fixed height
        text_edit.setFixedHeight(final_height)

    def scroll_to_bottom(self):
        """Scroll the conversation area to the bottom"""
        scrollbar = self.conversation_scroll.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        QTimer.singleShot(0, self.prompt_menu._position_prompt_menu)

    def label_clicked(self):
        pass

    @asyncSlot()
    async def delete_conversation(self, conversation_id):
        new_conversation_flag = True if self.id == conversation_id else False
        conversation_id = conversation_id or self.id
        dialog = ConfirmDeleteDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            await self.sidebar.app.delete_conversation(conversation_id)
            await self.sidebar.update_conversations(reselect=True)
            if new_conversation_flag:
                self.sidebar.clear_selection()
                self.sidebar.new_conversation()

    @asyncSlot()
    async def rename_conversation(self, conversation_id, name):
        conversation_id = conversation_id or self.id
        dialog = RenameDialog(name, self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.new_name:
            if await self.app.rename_conversation(conversation_id, dialog.new_name):
                await self.sidebar.update_conversations()
                if self.id == conversation_id:
                    self.top_bar.set_text(dialog.new_name)

    def load_conversation(self, conversation):
        """
        Load and reconstruct a conversation from a Conversation dataclass.

        Parameters:
            conversation: Conversation dataclass from basing.py
        """
        self.id = conversation.id
        self.top_bar.set_text(conversation.title)
        # Clear any existing conversation
        while self.conversation_layout.count():
            item = self.conversation_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Switch to conversation view if we have history
        if conversation.history:
            # Don't animate when loading existing conversation
            if not self.conversation_started:
                self.content_stack.setCurrentIndex(1)
                self.welcome_label.hide()
                self.conversation_started = True
                self.prompt_menu.conversation_started = True

                # Expand bottom container to show prompt box
                self.bottom_input_container.setMinimumHeight(200)
                self.bottom_input_container.setMaximumHeight(16777215)

                # Move prompt box to bottom container if not already there
                # Remove from welcome page layout
                welcome_layout = self.welcome_page.layout()
                for i in range(welcome_layout.count()):
                    item = welcome_layout.itemAt(i)
                    if item and isinstance(item, QHBoxLayout):
                        # Check if this layout contains our prompt box
                        for j in range(item.count()):
                            if item.itemAt(j) and item.itemAt(j).widget() == self.prompt_box:
                                # Found it, remove from welcome layout
                                item.removeWidget(self.prompt_box)
                                break

                # Add to bottom container layout
                left_spacer = QWidget()
                right_spacer = QWidget()

                # Clear existing centering layout
                while self.prompt_centering_layout.count():
                    item = self.prompt_centering_layout.takeAt(0)
                    if item.widget() and item.widget() != self.prompt_box:
                        item.widget().setParent(None)

                # Add prompt box to centering layout
                self.prompt_centering_layout.addWidget(left_spacer, 1)
                self.prompt_centering_layout.addWidget(self.prompt_box, 10)
                self.prompt_centering_layout.addWidget(right_spacer, 1)

        # Reconstruct each history item
        for history_idx, item in enumerate(conversation.history):
            if item.source == "agent":
                continue
            if item.role == "user":
                # Add user message without animation for historical messages
                self.add_message_to_conversation(item.content, message_type="user", animate=False)
            elif item.role == "assistant":
                # Add agent response without typewriter for historical messages
                self.add_message_to_conversation(item.content, message_type="agent", enable_typewriter=False, todo_list=item.todo_list)

                # Add any tool calls
                if len(item.tool_calls) == 1:
                    tool_call = item.tool_calls[0]
                    self._add_tool_call_widget(tool_call, history_idx, 0, 1)
                    if (response_content := tool_call.response_content) is not None:
                        self.add_message_to_conversation(message=response_content, message_type="agent",
                                                         enable_typewriter=False)
                elif len(item.tool_calls) > 1:
                    self.add_tool_call_widgets(item.tool_calls, history_idx)
                    for tool_call in item.tool_calls:
                        if (response_content := tool_call.response_content) is not None:
                            self.add_message_to_conversation(message=response_content, message_type="agent",
                                                             enable_typewriter=False)

    def load_blank_conversation(self):
        """
        Clear the conversation and reset to the initial empty state.
        """
        # Clear all messages from the conversation layout
        while self.conversation_layout.count():
            item = self.conversation_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Clear the input text
        self.text_edit.clear()
        self.top_bar.set_text("")

        # Reset to initial view if conversation was started
        if self.conversation_started:
            # Remove prompt box from bottom container layout
            for i in range(self.prompt_centering_layout.count()):
                item = self.prompt_centering_layout.itemAt(i)
                if item and item.widget() == self.prompt_box:
                    self.prompt_centering_layout.removeWidget(self.prompt_box)
                    break

            # Clear the bottom container layout
            while self.prompt_centering_layout.count():
                item = self.prompt_centering_layout.takeAt(0)
                if item.widget():
                    item.widget().setParent(None)

            # Reset bottom container to hidden state
            self.bottom_input_container.setMinimumHeight(0)
            self.bottom_input_container.setMaximumHeight(0)

            # Show welcome label again
            self.welcome_label.show()
            # Reset opacity if it had been animated
            self.welcome_label.setGraphicsEffect(None)  # type: ignore

            # Reparent welcome label back to welcome page if needed
            welcome_layout = self.welcome_page.layout()
            if self.welcome_label.parent() != self.welcome_page:
                # Find and re-add welcome label to the welcome page layout
                self.welcome_label.setParent(self.welcome_page)
                # Insert at position 0 (before the prompt box layout)
                welcome_layout.insertWidget(0, self.welcome_label)

            # Reparent prompt box back to welcome page layout
            if self.prompt_box.parent() != self.welcome_page:
                self.prompt_box.setParent(self.welcome_page)
                # Re-add to welcome page with centering
                prompt_h_layout = QHBoxLayout()
                prompt_h_layout.addStretch(1)
                prompt_h_layout.addWidget(self.prompt_box, 10)
                prompt_h_layout.addStretch(1)
                welcome_layout.addLayout(prompt_h_layout)

            # Switch back to welcome page (after reparenting so widgets are visible)
            self.content_stack.setCurrentIndex(0)

            # Reset the conversation state
            self.conversation_started = False
            self.prompt_menu.conversation_started = False

            # Reset prompt box height
            self.text_edit.setFixedHeight(self.initial_textedit_height)
            self.prompt_box.setFixedHeight(self.initial_prompt_height)

    def _add_tool_call_widget(self, tool_call, history_idx, tool_idx, tool_count):
        """
        Add a ToolConfirmationWidget based on a ToolCall dataclass.

        Parameters:
            tool_call: ToolCall dataclass from basing.py
        """

        self.add_message_to_conversation(
            message=None,
            message_type="permission",
            toolName=tool_call.tool_name,
            toolTitle=tool_call.tool_name,
            toolArgs=tool_call.tool_args,
            history_idx=history_idx,
            tool_idx=tool_idx,
            tool_count=tool_count,
            sensitive_args=[],  # Don't mark as sensitive for historical display
            init_state=tool_call.permission_granted,  # None, True, or False
            tool_response=tool_call.tool_response,
        )

    def add_tool_call_widgets(self, tool_calls, history_idx):
        """
        Add a ToolConfirmationWidget based on a ToolCall dataclass.

        Parameters:
            tool_calls: ToolCall dataclass from basing.py
        """

        message_widget = PermissionCarousel()

        for tool_idx, tool_call in enumerate(tool_calls):

            tool = self.app.find_tool(tool_call.tool_name)
            title = tool.get("title", "Unnamed Tool")

            perm_widget = ToolConfirmationWidget(
                tool_name=tool_call.tool_name,
                tool_title=title,
                tool_args=tool_call.tool_args,
                on_yes=self.on_tool_allow,
                on_no=self.on_tool_deny,
                sensitive_args=[],
                parent=message_widget,
                init_state=tool_call.permission_granted,
                history_idx=history_idx,
                tool_idx=tool_idx,
                tool_count=len(tool_calls),
                tool_response=tool_call.tool_response
            )

            message_widget.add_slide(perm_widget)

        # message_layout.addStretch()
        self.conversation_layout.addWidget(message_widget)

    def setLoading(self, toggle, gerunds=None):
        """
        Show or hide loading indicator with spinner and random gerund text.

        Args:
            toggle: True to show loading, False to hide
            gerunds: Optional list of custom loading messages. If None, uses default list.
        """
        # Default gerunds matching the Flet implementation
        if gerunds is None:
            gerunds = [
                "Pontificating...",
                "Philosophizing...",
                "Counting Sand...",
                "Using a Lever...",
                "Finding a Fulcrum...",
                "Discombobulating...",
                "Sipping Tea...",
                "Crossing The Road...",
                "Plotting...",
                "Scheming...",
                "Choreographing...",
                "Finding Inner Peace...",
                "Interpolating...",
            ]

        if toggle:
            # Choose a random gerund
            gerund_choice = random.choice(gerunds)

            # Create loading container if it doesn't exist
            if self.loading_container is None:
                self.loading_container = QFrame()
                self.loading_container.setStyleSheet(
                    """
                    QFrame {
                        background-color: transparent;
                        border: none;
                    }
                    """
                )

                loading_layout = QHBoxLayout(self.loading_container)
                loading_layout.setContentsMargins(20, 10, 20, 10)
                loading_layout.setSpacing(10)

                # Create spinner
                self.loading_spinner = WaitingSpinner(
                    self.loading_container,
                    roundness=100.0,
                    opacity=3.141592653589793,
                    fade=70.0,
                    radius=5,
                    lines=12,
                    line_length=5,
                    line_width=3,
                    speed=1.5707963267948966,
                    color=(249, 115, 21)
                )
                # Set a reasonable size for visibility
                self.loading_spinner.setFixedSize(20, 20)

                # Create label
                self.loading_label = QLabel(gerund_choice)
                self.loading_label.setStyleSheet("color: #676767; font-size: 16px;")

                loading_layout.addWidget(self.loading_spinner)
                loading_layout.addWidget(self.loading_label)
                loading_layout.addStretch()

            else:
                # Update the label text with new gerund
                self.loading_label.setText(gerund_choice)

            # Add to conversation if not already present
            if self.loading_container not in [
                self.conversation_layout.itemAt(i).widget()
                for i in range(self.conversation_layout.count())
            ]:
                self.conversation_layout.addWidget(self.loading_container)

            # Start spinner animation
            self.loading_spinner.start()

            # Scroll to bottom
            QTimer.singleShot(10, self.scroll_to_bottom)

        else:
            # Hide and remove loading indicator
            if self.loading_container is not None:
                if self.loading_spinner is not None:
                    self.loading_spinner.stop()

                # Remove from layout
                self.conversation_layout.removeWidget(self.loading_container)
                self.loading_container.setParent(None)
                self.loading_container = None


def wait(ms):
    """Wait for ms milliseconds"""
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()
