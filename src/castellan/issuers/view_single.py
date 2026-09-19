# -*- encoding: utf-8 -*-
"""
castellan.issuers.view module

Dialog for viewing a peer-discovery identifier stored on the Castellan
server. Deliberately proportionate — no witnesses/rotate/resubmit sections.
"""

import qasync
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QGridLayout
from keri import help
from keri.core.serdering import Serdery
from keri.help import helping
from locksmith.ui import colors
from locksmith.ui.toolkit.widgets import LocksmithDialog, LocksmithInvertedButton
from locksmith.ui.toolkit.widgets.buttons import LocksmithCopyButton
from locksmith.ui.toolkit.widgets.fields import LocksmithPlainTextEdit

from ..core import remoting

logger = help.ogler.getLogger(__name__)


class ViewSingleIdentifierDialog(LocksmithDialog):
    """Read-only dialog displaying an identifier uploaded to the Castellan server."""

    def __init__(self, app, identifier: dict, parent = None):
        self.app = app
        self.identifier = identifier

        # For multisig pending state, aid can be None
        self.aid = identifier.get('aid', None)
        alias = identifier.get('alias', '')

        # Create content widget and layout
        content_widget = QWidget()
        self.content_layout = QVBoxLayout(content_widget)
        self.content_layout.setContentsMargins(0, 10, 0, 0)
        self.content_layout.setSpacing(5)

        # Route to appropriate builder based on type
        self._build_singlesig_content()

        # Add close button
        button_row = QHBoxLayout()
        button_row.addStretch()
        close_btn = LocksmithInvertedButton("Close")
        button_row.addWidget(close_btn)
        button_row.addStretch()

        # Create title
        title_content = QWidget()
        title_content_layout = QVBoxLayout(title_content)
        title_content_layout.setContentsMargins(0, 0, 0, 0)
        display_title = alias or (self.aid[:24] + "…" if self.aid else "Multisig Identifier")
        self.title_label = QLabel(display_title)
        self.title_label.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {colors.TEXT_PRIMARY};")
        title_content_layout.addWidget(self.title_label)

        super().__init__(
            parent=parent,
            title_content=title_content,
            title_icon=":/assets/material-icons/badge.svg",
            content=content_widget,
            buttons=button_row,
        )

        close_btn.clicked.connect(self.close)

        self.setFixedSize(630, 670)

    def _build_singlesig_content(self):
        """Build content for single-sig identifier (existing behavior)."""
        # Validate AID exists for single-sig
        if not self.aid:
            raise ValueError("Single-sig identifier dict has no usable 'aid'")

        # AID field
        self._add_aid_field()

        # OOBI field (if present)
        if self.identifier.get('oobi'):
            self._add_oobi_field()

        # Uploaded timestamp
        self._add_timestamp_field()

        self.content_layout.addSpacing(15)

        # Key state frame
        self._add_key_state_frame()

        self.content_layout.addSpacing(15)

        # KEL display
        self._add_kel_display()

        # Load data asynchronously
        self._load_key_state()
        self._load_kel()

    def _add_aid_field(self):
        """Add AID field with copy button (single-sig)."""
        row = QHBoxLayout()
        label_widget = QLabel("AID:")
        label_widget.setStyleSheet("font-weight: bold; font-size: 13px;")
        row.addWidget(label_widget)
        value_widget = QLabel(self.aid)
        value_widget.setStyleSheet(
            "font-family: 'Menlo', 'SF Mono', monospace; font-size: 12px; color: #636466;"
        )
        value_widget.setWordWrap(False)
        row.addWidget(value_widget)
        copy_btn = LocksmithCopyButton(copy_content=self.aid, icon_size=24)
        row.addWidget(copy_btn)
        row.addStretch()
        self.content_layout.addLayout(row)

    def _add_oobi_field(self):
        """Add OOBI field (single-sig)."""
        row = QHBoxLayout()
        label_widget = QLabel("OOBI:")
        label_widget.setStyleSheet("font-weight: 500; font-size: 13px;")
        row.addWidget(label_widget)
        value_widget = QLabel(self.identifier.get('oobi', ''))
        value_widget.setStyleSheet("font-size: 13px;")
        value_widget.setWordWrap(True)
        row.addWidget(value_widget)
        row.addStretch()
        self.content_layout.addLayout(row)

    def _add_timestamp_field(self):
        """Add uploaded timestamp field."""
        created_at = self.identifier.get('created_at', '')
        if created_at:
            dt = helping.fromIso8601(created_at)
            row = QHBoxLayout()
            label_widget = QLabel("Uploaded:")
            label_widget.setStyleSheet("font-weight: 500; font-size: 13px;")
            row.addWidget(label_widget)
            value_widget = QLabel(dt.strftime("%b %d, %Y %I:%M %p"))
            value_widget.setStyleSheet("font-size: 13px;")
            value_widget.setWordWrap(True)
            row.addWidget(value_widget)
            row.addStretch()
            self.content_layout.addLayout(row)

    def _add_key_state_frame(self):
        """Add key state frame with local and remote sections."""
        key_state_frame = QFrame()
        key_state_frame.setStyleSheet(
            "QFrame { border: 2px solid #d0d0d0; border-radius: 6px; }"
            "QLabel { border: none; }"
        )
        key_state_layout = QVBoxLayout(key_state_frame)
        key_state_layout.setContentsMargins(12, 10, 12, 10)
        key_state_layout.setSpacing(6)

        key_state_header = QLabel("Key State")
        key_state_header.setStyleSheet("font-weight: bold; font-size: 14px; border: none;")
        key_state_layout.addWidget(key_state_header)
        key_state_layout.addSpacing(5)

        self._local_lines = self._add_key_state_block(key_state_layout, "Local:")
        self._remote_lines = self._add_key_state_block(key_state_layout, "Remote")

        self.content_layout.addWidget(key_state_frame)

    def _add_kel_display(self):
        """Add KEL display section."""
        kel_header = QHBoxLayout()
        kel_label = QLabel("Key Event Log")
        kel_label.setStyleSheet("font-weight: bold; font-size: 13px;")
        kel_header.addWidget(kel_label)
        kel_header.addStretch()
        self.kel_copy_button = LocksmithCopyButton(icon_size=24)
        kel_header.addWidget(self.kel_copy_button)

        self.content_layout.addLayout(kel_header)

        self._kel_field = LocksmithPlainTextEdit()
        self._kel_field.setPlainText("Loading...")
        self._kel_field.setReadOnly(True)
        self._kel_field.setMinimumHeight(140)
        self.content_layout.addWidget(self._kel_field)

    # ==================== Multi-sig Helper Methods ====================

    def _clear_layout(self, layout):
        """Recursively clear a layout and all its children."""
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

    # ==================== Static Helper Methods ====================

    @staticmethod
    def _add_field_row(layout: QVBoxLayout, label: str, value: str):
        row = QHBoxLayout()
        label_widget = QLabel(label)
        label_widget.setStyleSheet("font-weight: 500; font-size: 13px;")
        row.addWidget(label_widget)
        value_widget = QLabel(value)
        value_widget.setStyleSheet("font-size: 13px;")
        value_widget.setWordWrap(True)
        row.addWidget(value_widget)
        row.addStretch()
        layout.addLayout(row)

    @staticmethod
    def _add_aid_row(layout: QVBoxLayout, aid: str):
        row = QHBoxLayout()
        label_widget = QLabel("AID:")
        label_widget.setStyleSheet("font-weight: bold; font-size: 13px;")
        row.addWidget(label_widget)
        value_widget = QLabel(aid)
        value_widget.setStyleSheet(
            "font-family: 'Menlo', 'SF Mono', monospace; font-size: 12px; color: #636466;"
        )
        value_widget.setWordWrap(True)
        row.addWidget(value_widget)
        copy_btn = LocksmithCopyButton(copy_content=aid, icon_size=24)
        row.addWidget(copy_btn)
        row.addStretch()
        layout.addLayout(row)

    @staticmethod
    def _add_key_state_block(layout: QVBoxLayout, header: str) -> QGridLayout:
        """Add a key-state block: a bold header label plus an indented grid.

        Returns the inner (indented) QGridLayout so detail rows can be added later.
        """
        header_lbl = QLabel(header)
        header_lbl.setStyleSheet("font-weight: bold; font-size: 13px; border: none;")
        layout.addWidget(header_lbl)

        indented_row = QHBoxLayout()
        indented_row.addSpacing(20)
        detail_layout = QGridLayout()
        detail_layout.setVerticalSpacing(2)
        detail_layout.setHorizontalSpacing(6)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        indented_row.addLayout(detail_layout)
        indented_row.addStretch()
        layout.addLayout(indented_row)
        return detail_layout

    @staticmethod
    def _set_key_state_details(detail_layout: QGridLayout, fields: "list[tuple[str, str]] | str"):
        """Replace the contents of a detail layout with the given rows.

        ``fields`` is either a list of (name, value) pairs or a single string note.
        Rows are laid out in a grid so the ``=`` signs align vertically.
        """
        while detail_layout.count():
            item = detail_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        if isinstance(fields, str):
            note = QLabel(fields)
            note.setStyleSheet("font-size: 13px; border: none;")
            detail_layout.addWidget(note, 0, 0, 1, 3)
            return

        for i, (name, value) in enumerate(fields):
            name_lbl = QLabel(name)
            name_lbl.setStyleSheet("font-size: 13px; border: none; font-weight: 500;")
            eq_lbl = QLabel(":")
            eq_lbl.setStyleSheet("font-size: 13px; border: none; font-weight: bold;")
            value_lbl = QLabel(value)
            value_lbl.setStyleSheet("font-family: 'Menlo', 'SF Mono', monospace; font-size: 12px; color: #636466; border: none;")
            detail_layout.addWidget(name_lbl, i, 0)
            detail_layout.addWidget(eq_lbl, i, 1)
            detail_layout.addWidget(value_lbl, i, 2)

    @qasync.asyncSlot()
    async def _load_key_state(self):
        # Skip if aid is None (pending multisig)
        if not self.aid:
            return

        # Check if identifier has key_state and current_event from server
        stored_key_state = self.identifier.get('key_state')
        current_event = self.identifier.get('current_event')

        # Determine if we should show key state or current event
        if stored_key_state and current_event:
            # Compare sequence numbers
            key_state_sn = stored_key_state.get('sn', 0)
            current_event_sn = int(current_event.get('s', '0'), 16)

            if current_event_sn > key_state_sn:
                # Current event is ahead - show current event section instead
                self._show_current_event_section(current_event)
                return
            # Otherwise fall through to show key state normally

        # Show local key state
        hab = self.app.vault.hby.habs.get(self.aid) if self.app.vault else None
        if hab is not None:
            local_state = hab.kever.state()  # type: ignore
            self._set_key_state_details(self._local_lines, [
                ("Sequence Number", str(int(local_state.s, 16))),
                ("Event Digest", local_state.d),
            ])
        else:
            self._set_key_state_details(self._local_lines, "not controlled by this vault")

        # Show remote key state - use stored key_state if available and matches
        if stored_key_state and current_event:
            key_state_sn = stored_key_state.get('sn', 0)
            current_event_sn = int(current_event.get('s', '0'), 16)

            if current_event_sn == key_state_sn:
                # Use stored key state from identifier
                self._set_key_state_details(self._remote_lines, [
                    ("Sequence Number", str(key_state_sn)),
                    ("Event Digest", stored_key_state.get('d', '')),
                ])
                return

        # Otherwise fetch from server
        try:
            result = await remoting.fetch_identifier_keystate(app=self.app, identifier_prefix=self.aid)
            if result.get('success') and result.get('data') is not None:
                key_state = result['data'].get('key_state', {})
                sn = int(key_state.get('s', '0'), 16)
                said = key_state.get('d', '')
                self._set_key_state_details(self._remote_lines, [
                    ("Sequence Number", str(sn)),
                    ("Event Digest", said),
                ])
            else:
                self._set_key_state_details(self._remote_lines, "not found")
        except Exception as e:
            logger.exception(f"Error fetching remote key state for {self.aid}: {e}")
            self._set_key_state_details(self._remote_lines, "error fetching key state")

    def _show_current_event_section(self, current_event: dict):
        """Replace key state frame with current event frame when event is ahead of key state."""
        # Find and remove the existing key state frame
        for i in range(self.content_layout.count()):
            item = self.content_layout.itemAt(i)
            if item and item.widget() and isinstance(item.widget(), QFrame):
                widget = item.widget()
                # Check if this is the key state frame by checking its first label
                layout = widget.layout()
                if layout and layout.count() > 0:
                    first_item = layout.itemAt(0)
                    if first_item and first_item.widget() and isinstance(first_item.widget(), QLabel):
                        label = first_item.widget()
                        if label.text() == "Key State":
                            # Remove this frame and add current event frame
                            self.content_layout.removeWidget(widget)
                            widget.deleteLater()
                            self._add_current_event_frame(current_event, i)
                            return

    def _add_current_event_frame(self, current_event: dict, position: int = -1):
        """Add current event frame showing event ahead of key state."""
        event_frame = QFrame()
        event_frame.setStyleSheet(
            "QFrame { border: 2px solid #fbbf24; border-radius: 6px; }"
            "QLabel { border: none; }"
        )
        event_layout = QVBoxLayout(event_frame)
        event_layout.setContentsMargins(12, 10, 12, 10)
        event_layout.setSpacing(6)

        # Header
        header = QLabel("Current Event (Pending)")
        header.setStyleSheet("font-weight: bold; font-size: 14px; border: none; color: #92400e;")
        event_layout.addWidget(header)
        event_layout.addSpacing(5)

        # Event details
        detail_layout = QGridLayout()
        detail_layout.setVerticalSpacing(2)
        detail_layout.setHorizontalSpacing(6)
        detail_layout.setContentsMargins(0, 0, 0, 0)

        # Event type
        event_type = current_event.get('t', 'Unknown')
        type_label = QLabel("Event Type")
        type_label.setStyleSheet("font-size: 13px; border: none; font-weight: 500;")
        type_colon = QLabel(":")
        type_colon.setStyleSheet("font-size: 13px; border: none; font-weight: bold;")
        type_value = QLabel(event_type)
        type_value.setStyleSheet("font-family: 'Menlo', 'SF Mono', monospace; font-size: 12px; color: #636466; border: none;")
        detail_layout.addWidget(type_label, 0, 0)
        detail_layout.addWidget(type_colon, 0, 1)
        detail_layout.addWidget(type_value, 0, 2)

        # Sequence Number
        event_sn = int(current_event.get('s', '0'), 16)
        sn_label = QLabel("Sequence Number")
        sn_label.setStyleSheet("font-size: 13px; border: none; font-weight: 500;")
        sn_colon = QLabel(":")
        sn_colon.setStyleSheet("font-size: 13px; border: none; font-weight: bold;")
        sn_value = QLabel(str(event_sn))
        sn_value.setStyleSheet("font-family: 'Menlo', 'SF Mono', monospace; font-size: 12px; color: #636466; border: none;")
        detail_layout.addWidget(sn_label, 1, 0)
        detail_layout.addWidget(sn_colon, 1, 1)
        detail_layout.addWidget(sn_value, 1, 2)

        # Event Digest
        event_digest = current_event.get('d', '')
        digest_label = QLabel("Event Digest")
        digest_label.setStyleSheet("font-size: 13px; border: none; font-weight: 500;")
        digest_colon = QLabel(":")
        digest_colon.setStyleSheet("font-size: 13px; border: none; font-weight: bold;")
        digest_value = QLabel(event_digest)
        digest_value.setStyleSheet("font-family: 'Menlo', 'SF Mono', monospace; font-size: 12px; color: #636466; border: none;")
        detail_layout.addWidget(digest_label, 2, 0)
        detail_layout.addWidget(digest_colon, 2, 1)
        detail_layout.addWidget(digest_value, 2, 2)

        event_layout.addLayout(detail_layout)

        # Add to content layout at specified position
        if position >= 0:
            self.content_layout.insertWidget(position, event_frame)
        else:
            self.content_layout.addWidget(event_frame)

    @qasync.asyncSlot()
    async def _load_kel(self):
        # Skip if aid is None (pending multisig)
        if not self.aid:
            return

        try:
            result = await remoting.fetch_identifier_kel(self.app, self.aid)
            if result.get('success'):
                kel_bytes = result.get('kel_bytes', b"")
                kel_text = self._format_kel(kel_bytes) if kel_bytes else "No KEL captured yet."
                self._kel_field.setPlainText(kel_text)
                if kel_bytes:
                    self.kel_copy_button.copy_content = kel_text  # type: ignore
            else:
                self._kel_field.setPlainText(f"Error loading KEL: {result.get('error', 'Unknown error')}")
        except Exception as e:
            logger.exception(f"Error fetching KEL for {self.aid}: {e}")
            self._kel_field.setPlainText(f"Error loading KEL: {e}")

    @staticmethod
    def _format_kel(kel_bytes: bytes) -> str:
        """ Pretty-print each event in a CESR stream of concatenated events. """
        blocks = []
        serdery = Serdery()
        ims = bytearray(kel_bytes)
        while ims:
            serder = serdery.reap(ims)  # strips this event's raw off the front

            # What remains starts with this event's attachment, running until
            # the next event's JSON ('{') or the end of the stream.
            next_event = ims.find(b"{")
            attach_end = next_event if next_event != -1 else len(ims)
            attachment = ims[:attach_end]
            del ims[:attach_end]

            blocks.append(f"{serder.pretty()}\n{attachment.decode('utf-8', errors='replace')}")

        return "\n\n".join(blocks)