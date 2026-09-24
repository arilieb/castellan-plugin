import json

import qasync
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QGridLayout
)
from keri import help
from keri.core import parsing
from keri.db import basing
from keri.help import helping
from locksmith.ui import colors
from locksmith.ui.styles import get_monospace_font_family
from locksmith.ui.toolkit.widgets import (
    LocksmithDialog, LocksmithInvertedButton, LocksmithButton
)
from locksmith.ui.toolkit.widgets.buttons import LocksmithCopyButton

from ..core import remoting

logger = help.ogler.getLogger(__name__)


class ViewLiveMultisigIdentifierDialog(LocksmithDialog):
    """Dialog for viewing live multisig identifiers (synchronized or behind)."""

    closed = Signal()

    def __init__(self, app, identifier: dict, row_data: dict, parent=None):
        self.app = app
        self.identifier = identifier
        self.row_data = row_data
        self.state = identifier.get("_state")
        self.aid = identifier.get('aid')

        if not self.aid:
            raise ValueError("Live multisig must have an AID")

        # Build content
        content_widget = QWidget()
        self.content_layout = QVBoxLayout(content_widget)
        self.content_layout.setContentsMargins(0, 10, 0, 0)
        self.content_layout.setSpacing(8)

        self._build_live_content()

        # Close button
        button_row = QHBoxLayout()
        button_row.addStretch()
        close_btn = LocksmithInvertedButton("Close")
        button_row.addWidget(close_btn)
        button_row.addStretch()

        # Title
        alias = identifier.get('alias', '')
        title_content = QWidget()
        title_content_layout = QVBoxLayout(title_content)
        title_content_layout.setContentsMargins(0, 0, 0, 0)
        display_title = alias or (self.aid[:24] + "…")
        self.title_label = QLabel(display_title)
        self.title_label.setStyleSheet(
            f"font-size: 18px; font-weight: bold; color: {colors.TEXT_PRIMARY};"
        )
        title_content_layout.addWidget(self.title_label)

        super().__init__(
            parent=parent,
            title_content=title_content,
            title_icon=":/assets/material-icons/badge.svg",
            content=content_widget,
            buttons=button_row,
        )

        close_btn.clicked.connect(self._finished)
        self.setFixedSize(660, 900)

    def _finished(self):
        self.closed.emit()
        self.close()

    def _build_live_content(self):
        """Build content for live multisig identifier."""
        # AID field
        self._add_aid_field()

        # State badge
        self._add_state_badge()

        # Uploaded timestamp
        self._add_timestamp_field()

        self.content_layout.addSpacing(12)

        # Thresholds
        self._add_thresholds_display()

        # Members list (read-only, no status indicators)
        self._add_members_section()

        self.content_layout.addSpacing(16)

        # Key state section (different for live vs live_behind)
        if self.state == "live_behind":
            self._add_live_behind_section()
        else:
            self._add_live_section()

    def _add_aid_field(self):
        """Add AID field with copy button."""
        row = QHBoxLayout()
        label_widget = QLabel("AID:")
        label_widget.setStyleSheet("font-weight: bold; font-size: 13px;")
        row.addWidget(label_widget)

        value_widget = QLabel(self.aid)
        value_widget.setStyleSheet(
            f"font-family: {get_monospace_font_family()}; "
            "font-size: 12px; color: #636466;"
        )
        value_widget.setWordWrap(False)
        row.addWidget(value_widget)

        copy_btn = LocksmithCopyButton(copy_content=self.aid, icon_size=24)
        row.addWidget(copy_btn)
        row.addStretch()

        self.content_layout.addLayout(row)

    def _add_state_badge(self):
        """Add visual badge showing sync state."""
        if self.state == "live_behind":
            badge = QLabel("Local Behind Remote")
            badge.setStyleSheet("""
                QLabel {
                    background: #fef3c7;
                    color: #92400e;
                    padding: 4px 12px;
                    border-radius: 12px;
                    font-size: 11px;
                    font-weight: 600;
                }
            """)
        else:  # live
            badge = QLabel("Synchronized")
            badge.setStyleSheet("""
                QLabel {
                    background: #d1fae5;
                    color: #065f46;
                    padding: 4px 12px;
                    border-radius: 12px;
                    font-size: 11px;
                    font-weight: 600;
                }
            """)

        badge_layout = QHBoxLayout()
        badge_layout.addWidget(badge)
        badge_layout.addStretch()
        self.content_layout.addLayout(badge_layout)
        self.content_layout.addSpacing(8)

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

    def _add_thresholds_display(self):
        """Display multisig thresholds."""
        signing = self.identifier.get('signing_threshold', '—')
        rotation = self.identifier.get('rotation_threshold', '—')

        thresholds_layout = QHBoxLayout()
        thresholds_layout.setSpacing(24)

        # Signing threshold
        signing_layout = QVBoxLayout()
        signing_layout.setSpacing(6)
        signing_label = QLabel("Signing Threshold")
        signing_label.setStyleSheet(f"font-size: 11px; color: {colors.TEXT_SUBTLE};")
        signing_value = QLabel(str(signing))
        signing_value.setStyleSheet(
            f"font-size: 18px; font-weight: 600; color: {colors.TEXT_MENU};"
        )
        signing_layout.addWidget(signing_label)
        signing_layout.addWidget(signing_value)

        # Rotation threshold
        rotation_layout = QVBoxLayout()
        rotation_layout.setSpacing(6)
        rotation_label = QLabel("Rotation Threshold")
        rotation_label.setStyleSheet(f"font-size: 11px; color: {colors.TEXT_SUBTLE};")
        rotation_value = QLabel(str(rotation))
        rotation_value.setStyleSheet(
            f"font-size: 18px; font-weight: 600; color: {colors.TEXT_MENU};"
        )
        rotation_layout.addWidget(rotation_label)
        rotation_layout.addWidget(rotation_value)

        thresholds_layout.addLayout(signing_layout)
        thresholds_layout.addLayout(rotation_layout)
        thresholds_layout.addStretch()

        self.content_layout.addLayout(thresholds_layout)
        self.content_layout.addSpacing(16)

    def _add_members_section(self):
        """Display read-only list of multisig members."""
        section_label = QLabel("Members")
        section_label.setStyleSheet(
            "font-size: 15px; font-weight: 600; margin-top: 16px;"
        )
        self.content_layout.addWidget(section_label)
        self.content_layout.addSpacing(8)

        members = self.identifier.get('members', [])
        my_account_aid = self._get_current_account_aid()

        # Create table frame
        members_frame = QFrame()
        members_frame.setStyleSheet(f"""
            QFrame {{
                border: 1px solid {colors.BORDER};
                border-radius: 8px;
                background: {colors.BACKGROUND_CONTENT};
                padding: 12px;
            }}
        """)

        members_layout = QVBoxLayout(members_frame)
        members_layout.setContentsMargins(8, 8, 8, 8)
        members_layout.setSpacing(8)

        for member in members:
            member_row = self._create_member_row(member, my_account_aid)
            members_layout.addWidget(member_row)

        self.content_layout.addWidget(members_frame)

    def _create_member_row(self, member: dict, my_account_aid: str) -> QWidget:
        """Create a single member row (no status badges for live state)."""
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(12)

        # Username
        username = member.get('account_username', 'Unknown')
        is_me = member.get('account_aid') == my_account_aid

        name_label = QLabel(username + (" (You)" if is_me else ""))
        if is_me:
            name_label.setStyleSheet(f"font-weight: 600; color: {colors.PRIMARY};")
        else:
            name_label.setStyleSheet(f"color: {colors.TEXT_MENU};")

        row_layout.addWidget(name_label, stretch=1)

        return row

    def _get_current_account_aid(self) -> str:
        """Get the current user's Castellan account AID."""
        if not self.app or not self.app.vault:
            return ""

        account = self.app.vault.plugin_state.get("castellan", {}).get("account", {})
        return account.get("aid", "")

    def _add_live_section(self):
        """Add key state section for synchronized live state."""
        self._add_key_state_frame()
        self._load_key_state()

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
        key_state_header.setStyleSheet(
            "font-weight: bold; font-size: 14px; border: none;"
        )
        key_state_layout.addWidget(key_state_header)
        key_state_layout.addSpacing(5)

        self._local_lines = self._add_key_state_block(key_state_layout, "Local:")
        self._remote_lines = self._add_key_state_block(key_state_layout, "Remote:")

        self.content_layout.addWidget(key_state_frame)

    @staticmethod
    def _add_key_state_block(layout: QVBoxLayout, header: str) -> QGridLayout:
        """Add a key-state block with header and indented grid."""
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
    def _set_key_state_details(detail_layout: QGridLayout,
                              fields: "list[tuple[str, str]] | str"):
        """Replace contents of detail layout with given rows."""
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
            value_lbl.setStyleSheet(
                f"font-family: {get_monospace_font_family()}; "
                "font-size: 12px; color: #636466; border: none;"
            )
            detail_layout.addWidget(name_lbl, i, 0)
            detail_layout.addWidget(eq_lbl, i, 1)
            detail_layout.addWidget(value_lbl, i, 2)

    @qasync.asyncSlot()
    async def _load_key_state(self):
        """Load and display key state (local and remote)."""
        # Local key state
        hab = self.app.vault.hby.habs.get(self.aid) if self.app.vault else None
        if hab is not None:
            local_state = hab.kever.state()
            self._set_key_state_details(self._local_lines, [
                ("Sequence Number", str(int(local_state.s, 16))),
                ("Event Digest", local_state.d),
            ])
        else:
            self._set_key_state_details(
                self._local_lines,
                "not controlled by this vault"
            )

        # Remote key state
        try:
            result = await remoting.fetch_identifier_keystate(
                app=self.app,
                identifier_prefix=self.aid
            )
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
            self._set_key_state_details(
                self._remote_lines,
                "error fetching key state"
            )

    def _add_live_behind_section(self):
        """Add side-by-side key state comparison and catch-up button."""
        # Info message
        info = QLabel(
            "Your local key state is behind the remote. "
            "Click Catch Up to synchronize."
        )
        info.setStyleSheet(
            f"font-size: 13px; color: {colors.TEXT_MENU}; line-height: 1.5;"
        )
        info.setWordWrap(True)
        self.content_layout.addWidget(info)
        self.content_layout.addSpacing(12)

        # Side-by-side key state frames
        comparison_layout = QVBoxLayout()
        comparison_layout.setSpacing(8)

        # Local frame (left)
        local_frame = self._create_key_state_side("Local Key State", is_local=True)
        comparison_layout.addWidget(local_frame, stretch=1)

        # Remote frame (right)
        remote_frame = self._create_key_state_side("Remote Key State", is_local=False)
        comparison_layout.addWidget(remote_frame, stretch=1)

        self.content_layout.addLayout(comparison_layout)
        self.content_layout.addSpacing(16)

        # Catch Up button
        catch_up_btn_layout = QHBoxLayout()
        self.catch_up_btn = LocksmithButton("Catch Up")
        self.catch_up_btn.setFixedWidth(180)
        self.catch_up_btn.clicked.connect(self._on_catch_up_clicked)
        catch_up_btn_layout.addWidget(self.catch_up_btn)
        catch_up_btn_layout.addStretch()

        self.content_layout.addLayout(catch_up_btn_layout)

        # Load data
        self._load_key_state_comparison()

    def _create_key_state_side(self, title: str, is_local: bool) -> QFrame:
        """Create one side of the key state comparison (local or remote)."""
        frame = QFrame()

        # Highlight local frame if behind
        border_color = "#fbbf24" if is_local else "#d0d0d0"

        frame.setStyleSheet(
            f"QFrame {{ border: 2px solid {border_color}; "
            f"border-radius: 6px; }} "
            f"QLabel {{ border: none; }}"
        )

        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(12, 10, 12, 10)
        frame_layout.setSpacing(6)

        header = QLabel(title)
        color = "#92400e" if is_local else "#065f46"
        header.setStyleSheet(
            f"font-weight: bold; font-size: 13px; border: none; color: {color};"
        )
        frame_layout.addWidget(header)
        frame_layout.addSpacing(5)

        # Create detail grid
        detail_layout = QGridLayout()
        detail_layout.setVerticalSpacing(2)
        detail_layout.setHorizontalSpacing(6)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        frame_layout.addLayout(detail_layout)

        # Store reference to populate later
        if is_local:
            self._local_comparison = detail_layout
        else:
            self._remote_comparison = detail_layout

        return frame

    @qasync.asyncSlot()
    async def _load_key_state_comparison(self):
        """Load key state for side-by-side comparison."""
        # Local key state
        hab = self.app.vault.hby.habs.get(self.aid) if self.app.vault else None
        if hab is not None:
            local_state = hab.kever.state()
            local_sn = int(local_state.s, 16)
            self._set_key_state_details(self._local_comparison, [
                ("Sequence", str(local_sn)),
                ("Digest", local_state.d),
            ])
        else:
            self._set_key_state_details(
                self._local_comparison,
                "not controlled"
            )

        # Remote key state
        try:
            result = await remoting.fetch_identifier_keystate(
                app=self.app,
                identifier_prefix=self.aid
            )
            if result.get('success') and result.get('data') is not None:
                key_state = result['data'].get('key_state', {})
                remote_sn = int(key_state.get('s', '0'), 16)
                said = key_state.get('d', '')
                self._set_key_state_details(self._remote_comparison, [
                    ("Sequence", str(remote_sn)),
                    ("Digest", said),
                ])
            else:
                self._set_key_state_details(self._remote_comparison, "not found")
        except Exception as e:
            logger.exception(f"Error fetching remote key state: {e}")
            self._set_key_state_details(
                self._remote_comparison,
                "error fetching"
            )

    @qasync.asyncSlot()
    async def _on_catch_up_clicked(self):
        """Handle Catch Up button - fetch and parse remote KEL."""
        self.catch_up_btn.setEnabled(False)
        self.catch_up_btn.setText("Catching Up...")

        try:
            print(json.dumps(self.identifier, indent=2))
            # Oobi with witnesses if we don't already know about them:
            for witness in self.identifier['witnesses']:
                if witness.get('witness_aid') not in self.app.hby.kevers:
                    obr = basing.OobiRecord(date=helping.nowIso8601(), oobialias=witness.get('witness_alias'))
                    self.app.hby.db.oobis.put(keys=(witness.get('witness_oobi'),), val=obr)

            # Get all the KELS (group members and group itself)
            await remoting.load_multisig_member_kels(self.app, self.identifier)
            result = await remoting.fetch_identifier_kel(self.app, self.aid)
            if not result.get('success'):
                error_msg = result.get('error', 'Unknown error')
                logger.error(f"Failed to fetch KEL: {error_msg}")
                self.show_error(f"Failed to fetch remote KEL: {error_msg}")
                self.catch_up_btn.setEnabled(True)
                self.catch_up_btn.setText("Catch Up")
                return

            # Parse KEL
            kel_bytes = result.get('kel_bytes', b'')
            print(kel_bytes)
            if not kel_bytes:
                self.show_error("Remote KEL is empty")
                self.catch_up_btn.setEnabled(True)
                self.catch_up_btn.setText("Catch Up")
                return

            ims = bytearray(kel_bytes)
            parsing.Parser(
                kvy=self.app.vault.kvy,
                rvy=self.app.vault.hby.rvy,
                local=False
            ).parse(ims)
            self.app.vault.kvy.processEscrows()

            # Build group hab if needed
            if self.aid not in self.app.hby.habs:
                group = self.identifier.get("alias")
                smids = []
                rmids = []
                hab = None

                for member in self.identifier.get("members", []):
                    member_aid = member.get("member_aid")

                    if not member_aid:
                        raise ValueError("Member does not have a member_aid, multisig not ready to be completed.")

                    # Don't need to process our own KEL
                    if member_aid in self.app.vault.hby.habs:
                        hab = self.app.vault.hby.habs[member_aid]

                    smids.append(member_aid)
                    rmids.append(member_aid)

                self.app.hby.joinGroupHab(self.aid, group=group, mhab=hab, smids=smids, rmids=rmids)

            # Verify catch-up succeeded
            hab = self.app.vault.hby.habs.get(self.aid)
            if hab:
                local_state = hab.kever.state()
                local_sn = int(local_state.s, 16)

                # Fetch remote again to compare
                result = await remoting.fetch_identifier_keystate(
                    app=self.app,
                    identifier_prefix=self.aid
                )
                if result.get('success') and result.get('data'):
                    remote_sn = int(result['data']['key_state'].get('s', '0'), 16)

                    if local_sn >= remote_sn:
                        self.show_success("Successfully caught up!")
                        # Close and refresh parent list
                        self.closed.emit()
                        self.close()
                        return

            # If we got here, something went wrong
            self.show_error("Catch up completed but state still behind")
            self.catch_up_btn.setEnabled(True)
            self.catch_up_btn.setText("Catch Up")

        except Exception as e:
            logger.exception(f"Error during catch up: {e}")
            self.show_error(f"Error during catch up: {str(e)}")
            self.catch_up_btn.setEnabled(True)
            self.catch_up_btn.setText("Catch Up")
