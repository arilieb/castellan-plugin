# -*- encoding: utf-8 -*-
"""
archie.ui.prompts module

This module contains the PromptMenu class for managing the searchable prompt menu.
"""
import logging

from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QVBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QSizePolicy,
)

logger = logging.getLogger(__name__)


class PromptMenu:
    """
    Manages the searchable prompt menu that appears when typing '/' in the prompt box.
    """

    def __init__(self, parent_widget, base_page):
        """
        Initialize the PromptMenu.

        Parameters:
            parent_widget: The parent widget that contains the prompt_box
            base_page: The base page widget where the menu will be displayed
        """
        self.parent_widget = parent_widget
        self.base_page = base_page

        # Will be set by parent
        self.prompt_box = None
        self.padded_container = None
        self.conversation_started = False

        # Menu state
        self.prompt_menu_container = None
        self.prompt_menu_title = None
        self.prompt_list = None
        self.promptSearching = False
        self.promptFilter = None

        # Prompts data
        self.prompts = []
        self.load_prompts()

        # Callbacks
        self.on_prompt_selected_callback = None

    def load_prompts(self):
        """
        Temporary stub: returns a static list of available prompts.
        Replace later with loading from server(s).
        """
        self.prompts = []

    @staticmethod
    def get_prompt(name):
        """
        Temporary stub: returns a static singular prompt when given a prompt name.
        """
        return "Test prompt text"

    def build_prompt_menu(self, filter_text: str = ""):
        """
        Create/refresh a scrollable prompt filter menu from self.prompts.
        """
        if not hasattr(self, "padded_container") or self.padded_container is None:
            return

        if (
            not hasattr(self, "prompt_menu_container")
            or self.prompt_menu_container is None
        ):
            self.prompt_menu_container = QFrame(self.base_page)
            self.prompt_menu_container.setObjectName("promptMenu")
            self.prompt_menu_container.setAttribute(
                Qt.WidgetAttribute.WA_TranslucentBackground, False
            )
            self.prompt_menu_container.setStyleSheet(
                """
                #promptMenu {
                    background: #F7F8FF;
                    border-radius: 8px;
                    border: 1px solid rgba(0,0,0,0.12);
                }
                QLabel#promptMenuTitle {
                    font-weight: 600;
                    color: #4b4b4b;
                    background: #F7F8FF;
                    padding: 8px 10px;
                }
                QListWidget {
                    background: transparent;
                    border: none;
                    outline: none;
                    color: #2b2b2b;
                }
                QListWidget::item {
                    padding: 8px 10px;
                }
                QListWidget::item:selected {
                    background: #e9eefc;
                }
                QScrollBar:vertical {
                    background: transparent;
                    width: 8px;
                    border: none;
                }
                QScrollBar::handle:vertical {
                    background: rgba(0, 0, 0, 0.3);
                    border-radius: 4px;
                    min-height: 20px;
                }
                QScrollBar::handle:vertical:hover {
                    background: rgba(0, 0, 0, 0.5);
                }
                QScrollBar::handle:vertical:pressed {
                    background: rgba(0, 0, 0, 0.7);
                }
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                    height: 0px;
                    border: none;
                    background: transparent;
                }
                QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                    background: #F7F8FF;
                }
            """
            )
            self.prompt_menu_container.setSizePolicy(
                QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
            )

            container_layout = QVBoxLayout(self.prompt_menu_container)
            container_layout.setContentsMargins(2, 2, 2, 2)
            container_layout.setSpacing(0)

            self.prompt_menu_title = QLabel("Prompt Search", self.prompt_menu_container)
            self.prompt_menu_title.setObjectName("promptMenuTitle")
            container_layout.addWidget(self.prompt_menu_title, 0)

            self.prompt_list = QListWidget(self.prompt_menu_container)
            self.prompt_list.setUniformItemSizes(True)
            self.prompt_list.setVerticalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAsNeeded
            )
            self.prompt_list.setHorizontalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            )
            self.prompt_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
            self.prompt_list.setViewportMargins(0, 0, 0, 0)
            container_layout.addWidget(self.prompt_list, 1)

            self.prompt_list.itemClicked.connect(self._on_prompt_selected)

        # Populate items
        self.prompt_list.clear()
        f = (filter_text or "").strip().lower()
        for p in self.prompts:
            name = str(p.get("name", ""))
            desc = str(p.get("description", ""))
            if f and f not in name.lower() and f not in desc.lower():
                continue
            it = QListWidgetItem(name)
            it.setToolTip(desc)
            self.prompt_list.addItem(it)

        # Empty state: add a disabled item and shrink the list height to just that row
        empty_mode = False
        if self.prompt_list.count() == 0:
            empty_mode = True
            empty = QListWidgetItem(
                f"No prompts found matching {filter_text!r}"
                if filter_text
                else "No prompts found"
            )
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            empty.setForeground(Qt.GlobalColor.darkGray)
            self.prompt_list.addItem(empty)

        # Compute compact height
        count = self.prompt_list.count()

        # When in empty mode, show exactly one row height; otherwise up to 10
        visible_rows = 1 if empty_mode else min(count, 10)
        row_h = self.prompt_list.sizeHintForRow(0) if count > 0 else 28

        # Calculate the exact height needed
        list_h = visible_rows * row_h

        # Account for the frame width (if any) - 2px for top and bottom
        frame_width = self.prompt_list.frameWidth() * 2

        title_h = self.prompt_menu_title.sizeHint().height()
        list_w = 300

        self.prompt_list.setFixedHeight(list_h + frame_width)

        # Container margins (2+2 top/bottom)
        container_margins = 4
        self.prompt_menu_container.setFixedSize(
            QSize(list_w, title_h + list_h + frame_width + container_margins)
        )

        self._position_prompt_menu()
        self.prompt_menu_container.raise_()
        self.prompt_menu_container.show()
        QTimer.singleShot(0, self._position_prompt_menu)

    def _on_prompt_selected(self, item: QListWidgetItem):
        """
        Handle selecting a prompt:
        - Close the menu
        - Fetch prompt text via get_prompt(name)
        - Call the callback with the prompt text
        """
        if not item:
            return
        name = item.text()
        try:
            prompt_text = self.get_prompt(name) or ""
        except Exception as e:
            logger.error(f"Failed to load prompt '{name}': {e}")
            prompt_text = name

        self._end_prompt_search()

        # Call the callback if set
        if self.on_prompt_selected_callback:
            self.on_prompt_selected_callback(prompt_text)

    def _position_prompt_menu(self):
        """
        Position the prompt menu near the prompt_box without triggering mapTo warnings.
        We always map both widgets to self.base_page coordinates.
        """
        if (
            not hasattr(self, "prompt_menu_container")
            or self.prompt_menu_container is None
            or self.prompt_box is None
            or self.base_page is None
        ):
            return

        # If either widget is not in the same window yet, skip
        if self.prompt_box.window() is None or self.base_page.window() is None:
            return

        # Map prompt_box to base_page space
        prompt_top_left = self.prompt_box.mapTo(
            self.base_page, self.prompt_box.rect().topLeft()
        )
        prompt_geo = self.prompt_box.geometry()
        menu_w = self.prompt_menu_container.width()

        # Right-align to prompt_box
        x = prompt_top_left.x() + prompt_geo.width() - menu_w

        if self.conversation_started:
            y = prompt_top_left.y() - self.prompt_menu_container.height() - 8
        else:
            y = prompt_top_left.y() + prompt_geo.height() + 8

        # Clamp within base_page
        x = max(0, min(x, self.base_page.width() - menu_w - 1))
        y = max(
            0, min(y, self.base_page.height() - self.prompt_menu_container.height() - 1)
        )
        self.prompt_menu_container.move(x, y)

    def on_input_changed(self, input_value: str):
        """
        Handle prompt filtering logic, optimized for common non-search cases.

        Parameters:
            input_value: The current text from the input field

        Returns:
            bool: True if the input was handled by prompt search, False otherwise
        """
        if not input_value:
            self.promptSearching = False
            if hasattr(self, "prompt_menu_container") and self.prompt_menu_container:
                self.prompt_menu_container.hide()
            return False

        last_char = input_value[-1]

        if not self.promptSearching and last_char != "/":
            if hasattr(self, "prompt_menu_container") and self.prompt_menu_container:
                self.prompt_menu_container.hide()
            return False

        if last_char == "/":
            self._start_prompt_search()
            return True

        if self.promptSearching and last_char == " ":
            self._end_prompt_search()
            return True

        if self.promptSearching:
            self._update_prompt_filter(input_value)
            return True

        return False

    def _start_prompt_search(self):
        """Start prompt searching mode."""
        self.promptSearching = True
        self.promptFilter = None
        self.build_prompt_menu("")

    def _end_prompt_search(self):
        """End prompt searching mode."""
        self.promptSearching = False
        if hasattr(self, "prompt_menu_container") and self.prompt_menu_container:
            self.prompt_menu_container.hide()

    def _update_prompt_filter(self, input_value):
        """Update prompt filter based on current input."""
        self.promptFilter = input_value.rsplit("/", 1)[-1]
        self.build_prompt_menu(self.promptFilter)

    def handle_resize(self):
        """Handle parent widget resize events."""
        if hasattr(self, "prompt_menu_container") and self.prompt_menu_container:
            self._position_prompt_menu()

    def hide_menu(self):
        """Hide the prompt menu."""
        if hasattr(self, "prompt_menu_container") and self.prompt_menu_container:
            self.prompt_menu_container.hide()