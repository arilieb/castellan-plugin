# -*- encoding: utf-8 -*-
"""
castellan.issuers.view module

Dialog for viewing a peer-discovery identifier stored on the Castellan
server. Deliberately proportionate — no witnesses/rotate/resubmit sections.
"""
from typing import TYPE_CHECKING

import qasync
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QGridLayout
from keri import help
from keri.help import helping
from keri.core.serdering import Serdery, SerderKERI
from locksmith.ui import colors
from locksmith.ui.toolkit.widgets import LocksmithDialog, LocksmithInvertedButton
from locksmith.ui.toolkit.widgets.buttons import LocksmithCopyButton
from locksmith.ui.toolkit.widgets.fields import LocksmithPlainTextEdit

from ..core import remoting

if TYPE_CHECKING:
    from locksmith.core.apping import LocksmithApplication
    from locksmith.ui.vault.page import VaultPage

logger = help.ogler.getLogger(__name__)


class ViewIdentifierDialog(LocksmithDialog):
    """Read-only dialog displaying an identifier uploaded to the Castellan server."""

    def __init__(self, app, identifier: dict, parent: "VaultPage | None" = None):
        aid = identifier.get('aid', '')
        if not aid:
            raise ValueError("identifier dict has no usable 'aid'")

        self.app = app
        self.aid = aid

        alias = identifier.get('alias', '')
        oobi = identifier.get('oobi', '')

        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(5)

        self._add_aid_row(layout, aid)

        if oobi:
            self._add_field_row(layout, "OOBI:", oobi)

        created_at = identifier.get('created_at', '')
        if created_at:
            dt = helping.fromIso8601(created_at)
            self._add_field_row(layout, "Uploaded:", dt.strftime("%b %d, %Y %I:%M %p"))

        layout.addSpacing(15)
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

        layout.addWidget(key_state_frame)

        layout.addSpacing(15)

        kel_header = QHBoxLayout()
        kel_label = QLabel("Key Event Log")
        kel_label.setStyleSheet("font-weight: bold; font-size: 13px;")
        kel_header.addWidget(kel_label)
        kel_header.addStretch()
        self.kel_copy_button = LocksmithCopyButton(icon_size=24)
        kel_header.addWidget(self.kel_copy_button)

        layout.addLayout(kel_header)

        self._kel_field = LocksmithPlainTextEdit()
        self._kel_field.setPlainText("Loading...")
        self._kel_field.setReadOnly(True)
        self._kel_field.setMinimumHeight(140)
        layout.addWidget(self._kel_field)

        button_row = QHBoxLayout()
        button_row.addStretch()
        close_btn = LocksmithInvertedButton("Close")
        button_row.addWidget(close_btn)
        button_row.addStretch()

        title_content = QWidget()
        title_content_layout = QVBoxLayout(title_content)
        title_content_layout.setContentsMargins(0, 0, 0, 0)
        self.title_label = QLabel(alias or aid[:24] + "…")
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

        self._load_key_state()
        self._load_kel()

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
        hab = self.app.vault.hby.habs.get(self.aid) if self.app.vault else None
        if hab is not None:
            local_state = hab.kever.state()
            self._set_key_state_details(self._local_lines, [
                ("Sequence Number", str(int(local_state.s, 16))),
                ("Event Digest", local_state.d),
            ])
        else:
            self._set_key_state_details(self._local_lines, "not controlled by this vault")

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

    @qasync.asyncSlot()
    async def _load_kel(self):
        try:
            result = await remoting.fetch_identifier_kel(self.app, self.aid)
            if result.get('success'):
                kel_bytes = result.get('kel_bytes', b"")
                kel_text = self._format_kel(kel_bytes) if kel_bytes else "No KEL captured yet."
                self._kel_field.setPlainText(kel_text)
                if kel_bytes:
                    self.kel_copy_button.copy_content = kel_text
            else:
                self._kel_field.setPlainText(f"Error loading KEL: {result.get('error', 'Unknown error')}")
        except Exception as e:
            logger.exception(f"Error fetching KEL for {self.aid}: {e}")
            self._kel_field.setPlainText(f"Error loading KEL: {e}")

    @staticmethod
    def _format_kel(kel_bytes: bytes) -> str:
        """Pretty-print each event in a CESR stream of concatenated events."""
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