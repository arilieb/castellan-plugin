# -*- encoding: utf-8 -*-
"""
archie.ui.permission module

This module contains code for tool permission ui

"""

import ast

import qtawesome as qta
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QColor, QBrush
from PySide6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QHBoxLayout, QVBoxLayout,
    QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView,
    QLineEdit, QToolButton, QSizePolicy, QDialog, QStyle )
from qasync import asyncSlot


class ToolConfirmationWidget(QFrame):
    """
    A PySide6 replica of the Flet makeToolConfirmationContainer UI.
    - Inline editing per argument (pencil -> check).
    - 'Yes' disabled until a sensitive arg is changed.
    - Emits callbacks with edited args.
    """

    def __init__(
            self,
            tool_name: str,
            tool_title: str = "",
            tool_args: dict | None = None,
            on_yes=None,
            on_no=None,
            sensitive_args: list[str] | None = None,
            parent: QWidget | None = None,
            init_state: bool | None = None,
            history_idx:int = 0,
            tool_idx: int = 0,
            tool_count: int = 1,
            tool_response: list[dict] | None = None,
    ):
        super().__init__(parent)

        self.tool_name = tool_name
        self.tool_title = tool_title
        self.original_args = dict(tool_args or {})
        self.edited_args = dict(self.original_args)
        self.on_yes = on_yes
        self.on_no = on_no
        self.sensitive_args = set(sensitive_args or [])
        self.init_state = init_state  # None=requesting, True=called, False=denied
        self.history_idx = history_idx
        self.tool_idx = tool_idx
        self.tool_count = tool_count
        self.tool_response = tool_response
        self._pending_edits = {}
        
        self.setObjectName("ToolConfirmationWidget")
        self.setStyleSheet("""
        #ToolConfirmationWidget {
            background: transparent;
            border: none;
        }
        QFrame#Card {
            background: #FFFFFF;            
            border-radius: 12px;
            border: 0px solid transparent;
        }
        /* Titles: ensure transparent bg and normal (non-white) text */
        QLabel.title-strong, QLabel.title, QLabel.toolname {
            background-color: rgba(0,0,0,0);
        }
        QLabel.title-strong {
            font-weight: 700;
            font-size: 17px;
            color: #191C20;
        }
        QLabel.title {
            font-size: 17px;
            color: #191C20;
        }
        QLabel.count {
            background-color: transparent;   /* no grey backdrop */
            font-size: 16px;
            color: #888;
        }
        QLabel.toolresponse {
            background-color: transparent;   /* no grey backdrop */
            font-size: 14px;
            color: #444;
        }
        QLabel.toolname {
            font-size: 22px;
            color: #ec6f27;
            font-weight: 600;
        }
        QLabel.success {
            background-color: transparent;   /* no grey backdrop */
            font-size: 22px;
            color: #3fa16f;
            font-weight: 700;
        }
        QLabel.error {
            background-color: transparent;   /* no grey backdrop */
            font-size: 22px;
            color: red;
            font-weight: 600;
        }
        /* Limit styles to our table instance only */
        QTableWidget#tool-args-table {
            background: #FFFFFF;
            border-radius: 8px;
            gridline-color: #E0E0E0;
            outline: none;
            selection-background-color: rgba(0,0,0,0);
            selection-color: #191C20;
        }
        QTableWidget#tool-args-table QHeaderView::section {
            background: #FFFFFF;
            color: #6B7280;
            font-weight: 600;
            border: none;
            border-bottom: 1px solid #E0E0E0;
            padding: 8px 12px;
        }
        /* Value labels in table cells */
        QLabel.value-label {
            background-color: transparent;   /* no grey backdrop */
            color: #191C20;                  /* normal dark text */
        }
        QLabel.value-label[sensitive="true"] {
            color: red;                      /* only sensitive red */
        }

        /* Buttons */
        QPushButton#YesBtn {
            background: #ec6f27;
            color: white;
            border-radius: 8px;
            padding: 8px 18px;
            border: none;
        }
        QPushButton#YesBtn:disabled {
            background: #E2E8F0;
            color: #A0AEC0;
        }
        QPushButton#NoBtn {
            background: #F5F5F5;
            color: #6B7280;
            border-radius: 8px;
            padding: 6px 16px;
            border: 2px solid #D1D5DB;
        }
        QLineEdit.inline-editor {
            border: 1px solid #DADADA;
            background: #FFFFFF;
            padding: 4px 8px;
            border-radius: 8px;
            font-size: 13px;
            color: #191C20;                 /* ensure black text while editing */
        }
        """)
        self._build_ui()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        fixed_width = 600
        self.setFixedWidth(fixed_width)

        # Card with shadow-like border
        card = QFrame(self)
        card.setObjectName("Card")
        card.setStyleSheet(card.styleSheet() + """
        QFrame#Card {
            background: #FFFFFF;
            border-radius: 12px;
            border: 1px solid rgba(0,0,0,0.06);
        }
        """)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(24, 18, 24, 18)
        card_layout.setSpacing(15)

        # Headline (centered, two-row)
        row1 = self._row([
            self._label("Archimedes ", "title-strong"),
            self._label("is requesting permission ", "title"),
        ], center=True)

        tool = "tools" if self.tool_count > 1 else "tool"
        row2 = self._row([self._label(f"to use the following {tool}: ", "title")], center=True)

        # Tool row (icon + orange link-like name)
        tool_row = self._row([
            self._tool_icon(),
            self._label(self.tool_title, "toolname"),
        ], center=True, spacing=10)

        # Table refined
        self.table = self._make_table()

        # Buttons row (pill style)
        btns = self._row([], center=True, spacing=24)
        self.no_btn = QPushButton("Reject", self)
        # keep a reference to reuse later (hide/show)
        self._btns_row_layout = btns
        self._row1_layout = row1
        self._row2_layout = row2
        self._tool_row_layout = tool_row
        self._card_layout = None  # set below after creation
        self.no_btn.setObjectName("NoBtn")
        self.no_btn.setFixedHeight(34)
        self.no_btn.setMinimumWidth(64)
        self.no_btn.clicked.connect(self._handle_no)

        self.yes_btn = QPushButton("Approve", self)
        self.yes_btn.setObjectName("YesBtn")
        self.yes_btn.setFixedHeight(34)
        self.yes_btn.setMinimumWidth(64)
        self.yes_btn.clicked.connect(self._handle_yes)
        self.yes_btn.setEnabled(False if self.sensitive_args else True)

        btns.addStretch(1)
        btns.addWidget(self.no_btn, 0, Qt.AlignmentFlag.AlignHCenter)
        btns.addWidget(self.yes_btn, 0, Qt.AlignmentFlag.AlignHCenter)
        btns.addStretch(1)

        # Assemble
        card_layout.addLayout(row1)
        card_layout.addStretch(1)
        card_layout.addLayout(row2)
        card_layout.addStretch(2)
        card_layout.addLayout(tool_row)

        if self.tool_count > 1:
            card_layout.addLayout(self._row([self._label(f"(Tool {self.tool_idx + 1} of {self.tool_count})", "count")], center=True))

        card_layout.addStretch(4)
        card_layout.addWidget(self.table)
        card_layout.addStretch(8)
        card_layout.addLayout(btns)
        self._card_layout = card_layout  # save for later updates

        holder = QHBoxLayout()
        holder.setContentsMargins(0, 0, 0, 0)

        wrap = QWidget(self)
        wrap_layout = QVBoxLayout(wrap)
        wrap_layout.setContentsMargins(0, 0, 0, 0)
        wrap_layout.addWidget(card)

        card.setMinimumWidth(fixed_width - 30)
        card.setMaximumWidth(fixed_width - 30)

        holder.addWidget(wrap, 0, Qt.AlignmentFlag.AlignLeft)
        holder.addStretch()

        outer.addLayout(holder)
        outer.addSpacing(10)

        # Apply initial state if specified (for reconstruction)
        if self.init_state is not None:
            if self.init_state is True:
                # Called state
                self._apply_called_state()
            elif self.init_state is False:
                # Denied state
                self._apply_denied_state()

    def _apply_called_state(self):
        """Apply the called state without triggering callbacks"""
        self.no_btn.hide()
        self.yes_btn.hide()
        self._update_headers_for_called_state()
        self._update_footers_for_called_state()
        self._remove_edit_column()

    def _apply_denied_state(self):
        """Apply the denied state without triggering callbacks"""
        self.no_btn.hide()
        self.yes_btn.hide()
        self._show_denied_state()

    def _row(self, widgets, center=False, spacing=0):
        lay = QHBoxLayout()
        lay.setSpacing(spacing)
        lay.setContentsMargins(0, 0, 0, 0)
        if center:
            lay.addStretch()
        for w in widgets:
            lay.addWidget(w)
        if center:
            lay.addStretch()
        return lay

    def _label(self, text, cls):
        lbl = QLabel(text, self)
        lbl.setObjectName(cls)
        lbl.setProperty("class", cls)
        # allow stylesheet by class name
        lbl.setStyleSheet("")
        return lbl

    def _tool_icon(self):
        lbl = QLabel(self)
        lbl.setFixedSize(QSize(55, 55))
        lbl.setStyleSheet("""
            /* keep rounded border and subtle outline */
            border-radius: 8px;
            background: transparent;
        """)

        from PySide6.QtGui import QPixmap
        pix = QPixmap(":/assets/icons/icon_macos.png")
        if not pix.isNull():
            # Scale with aspect ratio and smooth transform
            lbl.setPixmap(pix.scaled(
                lbl.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            ))
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        else:
            # Fallback: subtle placeholder if image not found
            lbl.setStyleSheet(lbl.styleSheet() + "background: #FFE8CC;")
        return lbl

    def _make_table(self):
        table = QTableWidget(self)
        table.setObjectName("tool-args-table")

        table.setStyleSheet("""
        QTableWidget#tool-args-table {
            background: #FFFFFF;
            border-radius: 8px;
        }
        QTableWidget#tool-args-table::item {
            padding: 6px 10px;
            border-bottom: 1px solid #EFEFEF;
            background: transparent;
            selection-background-color: transparent;
        }
        QTableWidget#tool-args-table QHeaderView::section {
            background: #FFFFFF;
            color: #6B7280;
            font-weight: 600;
            font-size: 14px;
            border: none;
            border-bottom: 1px solid #E0E0E0;
            padding: 8px 12px;
            text-align: left;
        }
        QLabel.value-label { background-color: transparent; color: #191C20; }
        QLabel.value-label[sensitive="true"] { color: red; }
        QToolButton { background: transparent; border: none; padding: 0; }
        QToolButton:pressed { background: rgba(0,0,0,0.06); border-radius: 4px; }
        """)

        # Determine if we need the edit column based on init_state
        show_edit_column = self.init_state is None
        num_columns = 3 if show_edit_column else 2

        table.setColumnCount(num_columns)
        if show_edit_column:
            table.setHorizontalHeaderLabels(["Parameters", " Values", "Edit "])
        else:
            table.setHorizontalHeaderLabels(["Parameters", " Values"])

        table.verticalHeader().setVisible(False)
        table.setShowGrid(False)
        table.setAlternatingRowColors(False)
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        hdr = table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)

        if show_edit_column:
            hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
            item_edit = table.horizontalHeaderItem(2)
            if item_edit:
                item_edit.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        params_min = 155
        edit_width = 65

        table.setColumnWidth(0, params_min)
        if show_edit_column:
            table.setColumnWidth(2, edit_width)

        hdr.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        args = list(self.original_args.items())
        table.setRowCount(len(args))
        row_h = 42

        for r, (arg, val) in enumerate(args):
            name = QTableWidgetItem(arg.capitalize().replace("_", " "))

            # ~Qt.ItemFlag.ItemIsSelectable produces the inverse bitmask (all bits 1 except ItemIsSelectable's bit).
            # So the line means: take the current flags and remove the "selectable" flag from them.
            name.setFlags(name.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            name.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

            # Explicitly set a dark color (do not rely on palette)
            name.setForeground(QBrush(QColor("#191C20")))
            # Also ensure background is transparent
            name.setBackground(QBrush(Qt.GlobalColor.transparent))

            table.setItem(r, 0, name)

            # Value label inside transparent wrapper
            value_wrap = QFrame(self)
            value_wrap.setStyleSheet("background: transparent;")
            value_layout = QHBoxLayout(value_wrap)
            value_layout.setContentsMargins(8, 0, 0, 0)
            value_layout.setSpacing(0)

            value_lbl = QLabel(self._value_to_str(val))
            value_lbl.setObjectName("value-label")
            value_lbl.setProperty("class", "value-label")
            value_lbl.setProperty("sensitive", "true" if arg in self.sensitive_args else "false")
            value_lbl.setStyleSheet("")  # pick up rules above
            value_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            value_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

            value_layout.addWidget(value_lbl, 1)
            table.setCellWidget(r, 1, value_wrap)

            # Only add edit button if we're showing the edit column
            if show_edit_column:
                edit_btn = QToolButton(self)
                edit_btn.setIcon(qta.icon("mdi6.pencil-outline", color="#36618e"))
                edit_btn.setAutoRaise(True)
                edit_btn.setToolTip("Edit")
                edit_btn.clicked.connect(lambda _, rr=r, a=arg: self._start_edit(rr, a))

                edit_wrap = QFrame(self)
                edit_wrap.setStyleSheet("background: transparent;")
                edit_l = QHBoxLayout(edit_wrap)
                edit_l.setContentsMargins(0, 0, 6, 0)
                edit_l.addStretch()
                edit_l.addWidget(edit_btn)
                table.setCellWidget(r, 2, edit_wrap)

            table.setRowHeight(r, row_h)

        header_h = table.horizontalHeader().height() or 34
        total_h = header_h + (row_h * max(1, len(args))) + 12
        table.setFixedHeight(total_h)
        return table

    def _start_edit(self, row: int, arg_name: str):
        value_wrap = self.table.cellWidget(row, 1)
        if value_wrap is None:
            return

        current_label = None
        for i in range(value_wrap.layout().count()):
            w = value_wrap.layout().itemAt(i).widget()
            if isinstance(w, QLabel):
                current_label = w
                break
        if current_label is None:
            return

        current_text = current_label.text()

        editor = QLineEdit(current_text, self)
        editor.setObjectName("InlineEditor")
        editor.setProperty("class", "inline-editor")
        editor.setMinimumHeight(28)
        editor.setStyleSheet("""
            QLineEdit.inline-editor {
                border: 1px solid #DADADA;
                background: #FFFFFF;
                padding: 4px 8px;
                border-radius: 8px;
                font-size: 13px;
                color: #191C20;
            }
        """)
        
        self._pending_edits[(row, arg_name)] = editor

        while value_wrap.layout().count():
            item = value_wrap.layout().takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        value_wrap.layout().addWidget(editor, 1)

        editor.setFocus()
        editor.selectAll()

        save_btn = QToolButton(self)
        save_btn.setIcon(qta.icon("mdi6.check-outline", color="green"))
        save_btn.setAutoRaise(True)
        save_btn.setToolTip("Save")
        save_btn.clicked.connect(lambda _, rr=row, a=arg_name, ed=editor: self._save_edit(rr, a, ed))

        edit_wrap = self.table.cellWidget(row, 2)
        if isinstance(edit_wrap, QFrame):
            while edit_wrap.layout().count():
                item = edit_wrap.layout().takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            l = edit_wrap.layout()
            l.addStretch()
            l.addWidget(save_btn)

    def _save_edit(self, row: int, arg_name: str, editor: QLineEdit):
        new_text = editor.text()
        parsed = self._parse_value_like_original(arg_name, new_text)
        self.edited_args[arg_name] = parsed

        value_lbl = QLabel(new_text, self)
        value_lbl.setObjectName("value-label")
        value_lbl.setProperty("class", "value-label")
        value_lbl.setProperty("sensitive", "true" if arg_name in self.sensitive_args else "false")
        value_lbl.setStyleSheet("")
        value_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        del self._pending_edits[(row, arg_name)]

        value_wrap = self.table.cellWidget(row, 1)
        if isinstance(value_wrap, QFrame):
            while value_wrap.layout().count():
                item = value_wrap.layout().takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            value_wrap.layout().addWidget(value_lbl, 1)

        edit_btn = QToolButton(self)
        edit_btn.setIcon(qta.icon("mdi6.pencil-outline", color="#36618e"))
        edit_btn.setToolTip("Edit")
        edit_btn.setAutoRaise(True)
        edit_btn.clicked.connect(lambda _, rr=row, a=arg_name: self._start_edit(rr, a))

        edit_wrap = self.table.cellWidget(row, 2)
        if isinstance(edit_wrap, QFrame):
            while edit_wrap.layout().count():
                item = edit_wrap.layout().takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            l = edit_wrap.layout()
            l.addStretch()
            l.addWidget(edit_btn)

        if arg_name in self.sensitive_args and (self.original_args.get(arg_name) != parsed):
            self.yes_btn.setEnabled(True)

    def _parse_value_like_original(self, arg_name: str, text: str):
        original = self.original_args.get(arg_name)
        parsed = text
        if isinstance(original, list):
            try:
                parsed = ast.literal_eval(text)
                if not isinstance(parsed, list):
                    parsed = [text]
            except Exception:
                parsed = [item.strip().strip("'\"") for item in text.split(",") if item.strip()]
        return parsed

    def _value_to_str(self, v):
        if isinstance(v, list):
            return str(v)
        return f"{v}"

    def _confirm_pending_edits(self) -> bool:
        if not self._pending_edits:
            return True

        dialog = QDialog(self)
        dialog.setObjectName("ConfirmEditsDialog")
        dialog.setWindowTitle("Finish Editing")
        dialog.setWindowFlags(dialog.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        dialog.setModal(True)
        dialog.setStyleSheet("""
            QDialog#ConfirmEditsDialog {
                background: #FFFFFF;
                border-radius: 16px;
                border: 1px solid #E5E7EB;
            }
            QLabel#ConfirmDialogTitle {
                color: #111827;
                font-size: 22px;
                font-weight: 700;
                qproperty-alignment: AlignHCenter;
            }
            QLabel#ConfirmDialogInfo {
                color: #6B7280;
                font-size: 16px;
                qproperty-alignment: AlignHCenter;
            }
            QFrame#ConfirmDialogSeparator {
                background: #E5E7EB;
                max-height: 1px;
                min-height: 1px;
            }
            QPushButton#primary {
                min-width: 92px;
                min-height: 36px;
                padding: 6px 14px;
                border-radius: 8px;
                border: 2px solid transparent;
                font-weight: 600;
                background: #EC6F27;
                color: #FFFFFF;
            }
            QPushButton#primary:hover { background: #F98948; }
            QPushButton#primary:pressed { background: #D65F18; }
            QPushButton#cancel {
                min-width: 92px;
                min-height: 36px;
                padding: 6px 14px;
                border-radius: 8px;
                border: 1px solid #EC6F27;
                font-weight: 600;
                color: #EC6F27;
                background: transparent;
            }
            QPushButton#cancel:hover {
                background: rgba(236,111,39,0.08);
            }
            QPushButton#cancel:pressed {
                background: rgba(236,111,39,0.16);
            }
            QPushButton:focus {
                outline: none;
                border-color: rgba(236,111,39,0.45);
            }
        """)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(28, 28, 28, 24)
        layout.setSpacing(18)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(12)
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon_label = QLabel(dialog)
        icon_label.setObjectName("ConfirmDialogIcon")
        warning_icon = dialog.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning)
        icon_label.setPixmap(warning_icon.pixmap(36, 36))
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title_label = QLabel("Finish Editing", dialog)
        title_label.setObjectName("ConfirmDialogTitle")
        title_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        title_label.setFixedWidth(title_label.sizeHint().width())

        header.addWidget(icon_label)
        header.addWidget(title_label)
        layout.addLayout(header)

        separator = QFrame(dialog)
        separator.setObjectName("ConfirmDialogSeparator")
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(separator)

        info_label = QLabel("Select Approve to apply edits or Cancel to keep editing", dialog)
        info_label.setObjectName("ConfirmDialogInfo")
        info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info_label.setWordWrap(False)
        info_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        layout.addWidget(info_label)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 12, 0, 0)
        buttons.setSpacing(18)
        buttons.addStretch()

        cancel_btn = QPushButton("Cancel", dialog)
        cancel_btn.setObjectName("cancel")
        cancel_btn.clicked.connect(dialog.reject)
        buttons.addWidget(cancel_btn)

        approve_btn = QPushButton("Approve", dialog)
        approve_btn.setObjectName("primary")
        approve_btn.clicked.connect(dialog.accept)
        buttons.addWidget(approve_btn)

        buttons.addStretch()
        layout.addLayout(buttons)

        dialog.adjustSize()
        dialog.resize(max(dialog.width(), 360), dialog.height())

        if dialog.exec() != QDialog.DialogCode.Accepted:
            if self._pending_edits:
                (_, editor) = next(iter(self._pending_edits.items()))
                editor.setFocus()
                editor.selectAll()
            return False

        for (row, arg_name), editor in list(self._pending_edits.items()):
            self._save_edit(row, arg_name, editor)

        return True

    @asyncSlot()
    async def _handle_yes(self):
        if not self._confirm_pending_edits():
            return
        
        self.no_btn.hide()
        self.yes_btn.hide()

        tool_response = await self.on_yes(self.tool_name, self.history_idx, self.tool_idx, self.edited_args)
        self.tool_response = tool_response

        self._update_headers_for_called_state()
        self._update_footers_for_called_state()

        self._remove_edit_column()

    def _handle_no(self):
        self.on_no(self.history_idx, self.tool_idx)  # Needed an argument here to make asyncSlot work.

        self.no_btn.hide()
        self.yes_btn.hide()

        self._show_denied_state()

    def _remove_edit_column(self):
        if self.table is None:
            return
        if self.table.columnCount() == 3:
            # Remove the entire column instead of hiding it
            self.table.removeColumn(2)

            # Set the Values column to stretch to fill available space
            hdr = self.table.horizontalHeader()
            hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)

    def _update_footers_for_called_state(self):

        if self.tool_response:
            # Assume one result for now, this may have to change in the future
            tool_response = self.tool_response[0]
            if tool_response.get("status") == "error":
                self._card_layout.addLayout(self._row([self._label(f"Error", "error")], center=True))
            else:
                self._card_layout.addLayout(self._row([self._label(f"Success", "success")], center=True))

            self.tool_response_label = self._label(tool_response.get("message", ""), "toolresponse")
            self.tool_response_label.setFixedWidth(500)
            self.tool_response_label.setWordWrap(True)
            self.tool_response_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
            lay = QHBoxLayout()
            lay.setSpacing(24)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.addWidget(self.tool_response_label)
            lay.addStretch(1)
            self._card_layout.addLayout(lay)
            self._card_layout.addStretch(1)

    def _update_headers_for_called_state(self):

        def _move_all_widgets(src_layout, dst_layout):
            items = []
            while src_layout.count():
                items.append(src_layout.takeAt(0))

            dst_layout.addStretch()
            for it in items:
                w = it.widget()
                if w is not None:
                    dst_layout.addWidget(w)

            dst_layout.addStretch()

        def _clear_layout(layout):
            while layout.count():
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().setParent(None)

        _clear_layout(self._row1_layout)
        _clear_layout(self._row2_layout)

        _move_all_widgets(self._tool_row_layout, self._row1_layout)

        called_lbl = self._label("was called with the following parameters", "title")
        self._row2_layout.addStretch()
        self._row2_layout.addWidget(called_lbl)
        self._row2_layout.addStretch()


    def _show_denied_state(self):
        def _clear_layout(layout):
            while layout.count():
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()

        _clear_layout(self._row1_layout)
        _clear_layout(self._row2_layout)

        # Remove the previously added tool_row (prevents duplicate icon/name)
        if self._tool_row_layout is not None:
            _clear_layout(self._tool_row_layout)

        # Row1: {icon} {tool_name} centered within the card
        icon = self._tool_icon()
        name = self._label(self.tool_name, "toolname")
        self._row1_layout.addStretch()
        self._row1_layout.addWidget(icon, 0, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        self._row1_layout.addWidget(name, 0, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        self._row1_layout.addStretch()

        # Row2: centered message
        denied_lbl = self._label("Permission to call tool was denied", "title")
        self._row2_layout.addStretch()
        self._row2_layout.addWidget(denied_lbl, 0, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        self._row2_layout.addStretch()

        # Remove the table entirely
        if self.table is not None:
            self._card_layout.removeWidget(self.table)
            self.table.deleteLater()
            self.table = None

        # Shrink the outer box (card) and keep it left-aligned inside holder
        if self._card_layout:
            self._card_layout.setContentsMargins(16, 12, 16, 12)
            self._card_layout.setSpacing(10)

        card_widget = self._card_layout.parent() if hasattr(self._card_layout, 'parent') else None
        if isinstance(card_widget, QFrame):
            card_widget.setMaximumWidth(420)
            card_widget.setMinimumWidth(380)
            card_widget.updateGeometry()

    def _show_result(self, called: bool, args: dict):
        for i in range(self.layout().count()):
            item = self.layout().itemAt(i)
            if item and item.widget():
                item.widget().deleteLater()

        result = QFrame(self)
        result.setObjectName("Card")
        lay = QVBoxLayout(result)
        lay.setContentsMargins(14, 10, 14, 10)
        title = QLabel(
            f"{self.tool_name} {'was called' if called else 'was not called'}",
            self
        )
        title.setProperty("class", "toolname")
        title.setStyleSheet("")
        lay.addWidget(title)
        details = QLabel(f"Args: {args}", self)
        details.setWordWrap(True)
        lay.addWidget(details)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(result)
        self.setLayout(outer)