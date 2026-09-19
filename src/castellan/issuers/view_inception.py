# -*- encoding: utf-8 -*-
"""
castellan.issuers.view module

Dialog for viewing a multisig AID that is being created.

"""
import json

import qasync
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QGridLayout
from keri import help
from keri.core.coring import randomNonce
from keri.help import helping
from locksmith.ui import colors
from locksmith.ui.toolkit.widgets import LocksmithDialog, LocksmithInvertedButton, LocksmithButton

from ..core import remoting

logger = help.ogler.getLogger(__name__)


class ViewIceptionMultisigIdentifierDialog(LocksmithDialog):
    """Read-only dialog displaying an identifier uploaded to the Castellan server."""

    closed = Signal()

    def __init__(self, app, identifier: dict, row_data: dict, parent = None):
        self.app = app
        self.identifier = identifier
        self.row_data = row_data
        self.state = identifier.get("_state")

        # For multisig pending state, aid can be None
        self.aid = identifier.get('aid', None)
        alias = identifier.get('alias', '')

        # Create content widget and layout
        content_widget = QWidget()
        self.content_layout = QVBoxLayout(content_widget)
        self.content_layout.setContentsMargins(0, 10, 0, 0)
        self.content_layout.setSpacing(5)

        # Route to appropriate builder based on type
        self._build_multisig_content()

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

        close_btn.clicked.connect(self._finished)
        self.setFixedSize(650, 775)

    def _finished(self):
        self.closed.emit()
        self.close()

    def _build_multisig_content(self):
        """Build content for multi-sig identifier."""
        # AID field (might be "Pending" if null)
        self._add_multisig_aid_field()

        # State badge (Pending vs Active)
        self._add_state_badge()

        # Uploaded timestamp
        self._add_timestamp_field()

        self.content_layout.addSpacing(12)

        # Thresholds display
        self._add_thresholds_display()
        self._add_members_section()

        self.content_layout.addSpacing(16)

        if self.state in ("inception_ready", "inception_signed", "inception_created"):
            self._add_complete_section()
        else:
            self._add_membership_section()

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

    # ==================== Multi-sig Helper Methods ====================

    def _add_state_badge(self):
        """Add visual badge showing multisig state."""
        match self.state:
            case "inception":
                badge = QLabel("Pending your approval")
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
            case "inception_joined":
                badge = QLabel("Pending other approvals")
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
            case "inception_created" | "inception_ready":
                badge = QLabel("Pending your signature")
                badge.setStyleSheet("""
                    QLabel {
                        background: #fef3c7;
                        color: #92400e;
                        padding: 4px 12px;
                        border-radius: 12px;
                        font-size: 11px;
                        font-weight: 600;
                    }
                """)  # YELLOW BACKGROUND, RED TEXT
            case "inception_signed":
                badge = QLabel("Pending other signatures")
                badge.setStyleSheet("""
                    QLabel {
                        background: #d1fae5;
                        color: #065f46;
                        padding: 2px 8px;
                        border-radius: 8px;
                        font-size: 10px;
                        font-weight: 600;
                    }
                """)  # BLUE
            case _:
                badge = QLabel("Unknown")
                badge.setStyleSheet("""
                    QLabel {
                        background: #dbeafe;
                        color: #1e40af;
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

    def _add_multisig_aid_field(self):
        """Add AID field for multisig (show 'Pending' if null)."""
        field_layout = QHBoxLayout()
        field_layout.setSpacing(8)

        label = QLabel("AID:")
        label.setStyleSheet(f"font-weight: 600; color: {colors.TEXT_MENU};")
        field_layout.addWidget(label)

        value_label = QLabel("Pending")
        value_label.setStyleSheet(f"color: {colors.TEXT_SUBTLE}; font-style: italic;")
        field_layout.addWidget(value_label)

        field_layout.addStretch()
        self.content_layout.addLayout(field_layout)
        self.content_layout.addSpacing(12)

    def _add_thresholds_display(self):
        """Display multisig thresholds."""
        signing = self.identifier.get('signing_threshold', '—')
        rotation = self.identifier.get('rotation_threshold', '—')

        thresholds_layout = QHBoxLayout()
        thresholds_layout.setSpacing(24)

        # Signing threshold
        signing_layout = QVBoxLayout()
        signing_label = QLabel("Signing Threshold")
        signing_label.setStyleSheet(f"font-size: 11px; color: {colors.TEXT_SUBTLE};")
        signing_value = QLabel(str(signing))
        signing_value.setStyleSheet(f"font-size: 18px; font-weight: 600; color: {colors.TEXT_MENU};")
        signing_layout.addWidget(signing_label)
        signing_layout.addWidget(signing_value)

        # Rotation threshold
        rotation_layout = QVBoxLayout()
        rotation_label = QLabel("Rotation Threshold")
        rotation_label.setStyleSheet(f"font-size: 11px; color: {colors.TEXT_SUBTLE};")
        rotation_value = QLabel(str(rotation))
        rotation_value.setStyleSheet(f"font-size: 18px; font-weight: 600; color: {colors.TEXT_MENU};")
        rotation_layout.addWidget(rotation_label)
        rotation_layout.addWidget(rotation_value)

        thresholds_layout.addLayout(signing_layout)
        thresholds_layout.addLayout(rotation_layout)
        thresholds_layout.addStretch()

        self.content_layout.addLayout(thresholds_layout)
        self.content_layout.addSpacing(16)

    def _get_current_account_aid(self) -> str:
        """Get the current user's Castellan account AID."""
        if not self.app or not self.app.vault:
            return ""

        account = self.app.vault.plugin_state.get("castellan", {}).get("account", {})
        return account.get("aid", "")

    def _get_my_member(self) -> dict | None:
        """Find current user's member object in the multisig, if present."""
        my_account_aid = self._get_current_account_aid()
        if not my_account_aid:
            return None

        members = self.identifier.get('members', [])
        for member in members:
            if member.get('account_aid') == my_account_aid:
                return member

        return None

    def _is_member(self) -> bool:
        """Check if current user is a member of this multisig."""
        return self._get_my_member() is not None

    def _has_approved(self) -> bool:
        """Check if current user has joined the multisig."""
        my_member = self._get_my_member()
        return my_member is not None and my_member.get('member_aid') is not None

    def _has_joined(self) -> bool:
        """Check if current user has joined the multisig."""
        my_member = self._get_my_member()
        return self._has_approved() and my_member.get('signature_received', False)

    def _add_members_section(self):
        """Display table of multisig members with their status."""
        section_label = QLabel("Members")
        section_label.setStyleSheet("font-size: 15px; font-weight: 600; margin-top: 16px;")
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
        """Create a single member row display."""
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

        row_layout.addWidget(name_label, stretch=3)

        # Status badge - use "Approved" terminology for pending/ready states
        if self.identifier.get("aid", None) is None:
            label_flag = member.get("member_aid", None)
            status_label = QLabel("Approved" if label_flag else "Not Approved")
        else:
            label_flag = member.get('public_key', None)
            status_label = QLabel("Signed" if label_flag else "Not Signed")

        status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        if label_flag:
            # Yellow for approved in pending/ready states, green for joined in active state
            status_label.setStyleSheet("""
                QLabel {
                    background: #d1fae5;
                    color: #065f46;
                    padding: 2px 8px;
                    border-radius: 8px;
                    font-size: 10px;
                    font-weight: 600;
                }
            """)
        else:
            status_label.setStyleSheet("""
                QLabel {
                    background: #fee2e2;
                    color: #991b1b;
                    padding: 2px 8px;
                    border-radius: 8px;
                    font-size: 10px;
                    font-weight: 600;
                }
            """)

        status_label.setFixedWidth(105)
        row_layout.addWidget(status_label)

        return row

    def _add_membership_section(self):
        """Add membership status and Approve/Join button if applicable."""
        state = self.state

        if not self._is_member():
            # Not a member - show info message
            info = QLabel("You are not a member of this multisig.")
            info.setStyleSheet(f"font-size: 13px; color: {colors.TEXT_SUBTLE}; font-style: italic;")
            self.content_layout.addWidget(info)
            return

        if self._has_joined():
            # Already joined/approved - show success message with appropriate terminology
            success = QLabel("✓ You have approved this multisig.")
            success.setStyleSheet(f"font-size: 13px; color: #065f46; font-weight: 600;")
            self.content_layout.addWidget(success)
            return

        # Member but not joined - show Approve/Join button with appropriate terminology
        self.content_layout.addSpacing(4)

        button_text = None
        if state in ("inception",):
            info = QLabel("You have been requested as a member of this multisig event. Click Approve to participate.")
            button_text = "Approve Multisig"
        else:
            info = QLabel("You are waiting on others to approve this multisig.")


        info.setStyleSheet(f"font-size: 13px; color: {colors.TEXT_MENU};")
        self.content_layout.addWidget(info)
        self.content_layout.addSpacing(8)

        if button_text is not None:
            join_btn_layout = QHBoxLayout()
            self.join_btn = LocksmithButton(button_text)
            self.join_btn.setFixedWidth(180)
            self.join_btn.clicked.connect(self._on_join_clicked)
            join_btn_layout.addWidget(self.join_btn)
            join_btn_layout.addStretch()

            self.content_layout.addLayout(join_btn_layout)

    def _add_complete_section(self):
        """Add Complete button and instructions when all members have joined."""
        # Instruction text
        # Already joined/approved - show success message with appropriate terminology
        if self.state == "inception_signed":
            success = QLabel("✓ You have signed this multisig.")
            success.setStyleSheet(f"font-size: 13px; color: #065f46; font-weight: 600;")
            self.content_layout.addWidget(success)
            return

        info = QLabel("The AID is ready to complete. Click the button below to create and sign the"
                      " inception event and share with other members.")
        info.setStyleSheet(f"font-size: 13px; color: {colors.TEXT_MENU}; line-height: 1.5;")
        info.setWordWrap(True)
        self.content_layout.addWidget(info)
        self.content_layout.addSpacing(12)

        # Complete button
        complete_btn_layout = QHBoxLayout()
        self.complete_btn = LocksmithButton("Sign Multisig")
        self.complete_btn.setFixedWidth(200)
        self.complete_btn.clicked.connect(self._on_complete_clicked)
        complete_btn_layout.addWidget(self.complete_btn)
        complete_btn_layout.addStretch()

        self.content_layout.addLayout(complete_btn_layout)

    @qasync.asyncSlot()
    async def _on_complete_clicked(self):
        """Handle Complete button click - initiate multisig inception."""
        self.complete_btn.setEnabled(False)
        self.complete_btn.setText("Joining...")

        await remoting.load_multisig_member_kels(self.app, self.identifier)
        ghab = await self._complete_multisig_inception()
        await self._publish_multisig_inception(ghab)

        multisig_id = self.identifier.get('id')
        alias = self.identifier.get('alias')

        logger.info(f"Join multisig clicked for: {alias} (ID: {multisig_id})")

        # Placeholder - re-enable button for now
        self.complete_btn.setEnabled(True)
        self.complete_btn.setText("Join Multisig")

    @qasync.asyncSlot()
    async def _on_join_clicked(self):
        """Handle Approve/Join button click - initiate multisig join process."""
        state = self.state
        self.join_btn.setEnabled(False)

        # Use appropriate button text based on state
        if state in ('pending', 'ready'):
            self.join_btn.setText("Approving...")
        else:
            self.join_btn.setText("Joining...")

        multisig_id = self.identifier.get('id')
        alias = self.identifier.get('alias')

        nonce = randomNonce()
        local_member_hab = self.app.vault.hby.makeHab(f"{alias}_local_aid_{nonce}", ns="_castellan_multisig",
                                                      icount=1, isith="1",
                                                      ncount=1, nsith="1",
                                                      toad=0, transferable=True)
        kel = local_member_hab.replay()
        data = {'member_aid': local_member_hab.pre}

        await self._join_multisig(multisig_id, kel, data)


    async def _join_multisig(self, multisig_id: str, kel: bytes, multisig_data: dict):
        """Store threshold configuration and create multisig identifier on server."""
        logger.debug(f"Joining multisig {multisig_id} with: {multisig_data}")

        # Create multisig identifier on Castellan server
        result = await remoting.join_multisig_identifier(
            app=self.app,
            multisig_id=multisig_id,
            kel=kel,
            multisig_data=multisig_data
        )

        if not result.get('success'):
            error_msg = result.get('error', 'Unknown error')
            logger.error(f"Failed to join multisig identifier: {error_msg}")
            self.show_error(f"Failed to join multisig on server: {error_msg}")
            # Re-enable button on failure with appropriate text based on state
            state = self.state
            self.join_btn.setEnabled(True)
            if state in ('pending', 'ready'):
                self.join_btn.setText("Approve Multisig")
            else:
                self.join_btn.setText("Join Multisig")
            return

        logger.info(f"Successfully approved multisig identifier on server: {result.get('data')}")

        # Show success banner
        self.show_success("Successfully approved the multisig!")

        # Update the identifier with the new data from the server
        self.identifier.update(result)
        self.state = remoting.get_multisig_state(self.app, self.identifier)
        self.identifier["_state"] = self.state

        # Refresh the UI to show updated state
        await self._refresh_membership_section()

    async def _refresh_membership_section(self):
        """Refresh the membership section to reflect updated join status."""
        # Clear all content from the layout
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

        # Rebuild the multisig content with updated data
        self._build_multisig_content()

    def _clear_layout(self, layout):
        """Recursively clear a layout and all its children."""
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

    # ==================== Static Helper Methods ====================

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

    async def _complete_multisig_inception(self):
        """ Create the GroupHab from the members of the multisig identifier. """
        group = self.identifier.get("alias")
        signing_threshold = self.identifier.get("signing_threshold", 0)
        rotation_threshold = self.identifier.get("rotation_threshold", 0)

        signing_fractional = []
        rotation_fractional = []

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

            if member.get("signing_fractional"):
                signing_fractional.append(member_aid)
            if member.get("rotation_fractional"):
                rotation_fractional.append(member_aid)

        if signing_threshold == 0 and len(signing_fractional) != len(smids):
            raise ValueError("signing_threshold is greater than the number of members")

        if rotation_threshold == 0 and len(rotation_fractional) != len(smids):
            raise ValueError("rotation_threshold is greater than the number of members")


        if signing_threshold != 0:
            if signing_threshold > len(smids):
                raise ValueError("signing_threshold is greater than the number of members")

            isith = str(signing_threshold)

        else:
            isith = f"[{','.join(signing_fractional)}]"

        if rotation_threshold != 0:
            if rotation_threshold > len(rmids):
                raise ValueError("signing_threshold is greater than the number of members")

            nsith = str(rotation_threshold)

        else:
            nsith = f"[{','.join(rotation_fractional)}]"

        ghab = self.app.vault.hby.makeGroupHab(group=group, mhab=hab, smids=smids, rmids=rmids,
                                               isith=isith, nsith=nsith, toad=0)

        return ghab

    async def _publish_multisig_inception(self, ghab):
        multisig_id = self.identifier.get('id')
        icp = ghab.makeOwnInception(allowPartiallySigned=True)

        logger.debug(f"Joining multisig {multisig_id} with {ghab.pre}.")

        # Create multisig identifier on Castellan server
        result = await remoting.add_multisig_signature_identifier(
            app=self.app,
            multisig_id=multisig_id,
            icp=icp,
            multisig_data=dict(aid=ghab.pre)
        )

        if not result.get('success'):
            error_msg = result.get('error', 'Unknown error')
            logger.error(f"Failed to join multisig identifier: {error_msg}")
            self.show_error(f"Failed to join multisig on server: {error_msg}")
            # Re-enable button on failure
            self.complete_btn.setEnabled(True)
            self.complete_btn.setText("Join Multisig")
            return

        logger.info(f"Successfully joined multisig identifier on server: {result.get('data')}")

        # Show success banner
        self.show_success("Successfully joined the multisig!")

        # Update the identifier with the new data from the server
        self.identifier.update(result)
        self.state = remoting.get_multisig_state(self.app, self.identifier)
        self.identifier["_state"] = self.state

        # Refresh the UI to show updated state
        await self._refresh_membership_section()