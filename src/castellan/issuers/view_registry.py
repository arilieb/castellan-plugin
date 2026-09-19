# -*- encoding: utf-8 -*-
"""
castellan.issuers.view_registry module

Dialog for viewing a registry that is being created for a multisig identifier.
Shows registry details, member signature status, and allows signing the IXN event.
"""
import qasync
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame
from keri import help
from keri.help import helping
from locksmith.ui import colors
from locksmith.ui.toolkit.widgets import LocksmithDialog, LocksmithInvertedButton, LocksmithButton

logger = help.ogler.getLogger(__name__)


class ViewRegistryCreationDialog(LocksmithDialog):
    """Dialog for viewing a registry being created for a multisig identifier."""

    closed = Signal()

    def __init__(self, app, identifier: dict, row_data: dict, parent=None):
        self.app = app
        self.identifier = identifier
        self.row_data = row_data
        self.state = identifier.get("_state")
        self.aid = identifier.get('aid')
        alias = identifier.get('alias', '')

        # Create content widget and layout
        content_widget = QWidget()
        self.content_layout = QVBoxLayout(content_widget)
        self.content_layout.setContentsMargins(0, 10, 0, 0)
        self.content_layout.setSpacing(5)

        # Build content
        self._build_content()

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
        display_title = alias or (self.aid[:24] + "…" if self.aid else "Registry Creation")
        self.title_label = QLabel(display_title)
        self.title_label.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {colors.TEXT_PRIMARY};")
        title_content_layout.addWidget(self.title_label)

        super().__init__(
            parent=parent,
            title_content=title_content,
            title_icon=":/assets/material-icons/shield_lock.svg",
            content=content_widget,
            buttons=button_row,
        )

        close_btn.clicked.connect(self._finished)
        self.setFixedSize(650, 840)

    def _finished(self):
        self.closed.emit()
        self.close()

    def _build_content(self):
        """Build the dialog content."""
        # AID field
        self._add_aid_field()

        # State badge
        self._add_state_badge()

        # Uploaded timestamp
        self._add_timestamp_field()

        self.content_layout.addSpacing(12)

        # Registry details
        self._add_registry_details()

        self.content_layout.addSpacing(16)

        # Members section
        self._add_members_section()

        self.content_layout.addSpacing(16)

        # Signing section
        if self.state == "registry_created":
            self._add_signing_section()
        elif self.state == "registry_signed":
            self._add_signed_message()

    def _add_aid_field(self):
        """Add AID field."""
        field_layout = QHBoxLayout()
        field_layout.setSpacing(8)

        label = QLabel("AID:")
        label.setStyleSheet(f"font-weight: 600; color: {colors.TEXT_MENU};")
        field_layout.addWidget(label)

        value_label = QLabel(self.aid or "Unknown")
        value_label.setStyleSheet(f"color: {colors.TEXT_MENU};")
        value_label.setWordWrap(True)
        field_layout.addWidget(value_label)

        field_layout.addStretch()
        self.content_layout.addLayout(field_layout)
        self.content_layout.addSpacing(12)

    def _add_state_badge(self):
        """Add visual badge showing registry creation state."""
        match self.state:
            case "registry_created":
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
                """)
            case "registry_signed":
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
                """)
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

    def _add_registry_details(self):
        """Display registry details."""
        section_label = QLabel("Registry Details")
        section_label.setStyleSheet("font-size: 15px; font-weight: 600; margin-top: 16px;")
        self.content_layout.addWidget(section_label)
        self.content_layout.addSpacing(8)

        # Get registry info from vcp field
        vcp = self.identifier.get('vcp', {})
        registry_name = vcp.get('name', 'Unknown')
        registry_id = vcp.get('registry_id', vcp.get('i', 'Unknown'))

        # Create details frame
        details_frame = QFrame()
        details_frame.setStyleSheet(f"""
            QFrame {{
                border: 1px solid {colors.BORDER};
                border-radius: 8px;
                background: {colors.BACKGROUND_CONTENT};
                padding: 12px;
            }}
        """)

        details_layout = QVBoxLayout(details_frame)
        details_layout.setContentsMargins(12, 12, 12, 12)
        details_layout.setSpacing(12)

        # Registry name
        name_row = QHBoxLayout()
        name_label = QLabel("Registry Name:")
        name_label.setStyleSheet(f"font-weight: 600; color: {colors.TEXT_MENU};")
        name_label.setFixedWidth(135)
        name_row.addWidget(name_label)
        name_value = QLabel(registry_name)
        name_value.setStyleSheet(f"color: {colors.TEXT_MENU};")
        name_value.setWordWrap(False)
        name_row.addWidget(name_value, stretch=1)
        details_layout.addLayout(name_row)

        # Registry ID
        id_row = QHBoxLayout()
        id_label = QLabel("Registry ID:")
        id_label.setStyleSheet(f"font-weight: 600; color: {colors.TEXT_MENU};")
        id_label.setFixedWidth(135)
        id_row.addWidget(id_label)
        id_value = QLabel(registry_id)
        id_value.setStyleSheet(f"color: {colors.TEXT_MENU};")
        id_value.setWordWrap(False)
        id_row.addWidget(id_value, stretch=1)
        details_layout.addLayout(id_row)

        self.content_layout.addWidget(details_frame)

    def _add_members_section(self):
        """Display table of multisig members with their signature status."""
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

        # Status badge - check if member has signed the registry
        has_signed = member.get('signature_received', False)
        status_label = QLabel("Signed" if has_signed else "Not Signed")
        status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        if has_signed:
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

    def _add_signing_section(self):
        """Add signing button and instructions."""
        info = QLabel(
            "The registry is ready to sign. Click the button below to sign the registry "
            "creation event and notify other members."
        )
        info.setStyleSheet(f"font-size: 13px; color: {colors.TEXT_MENU}; line-height: 1.5;")
        info.setWordWrap(True)
        self.content_layout.addWidget(info)
        self.content_layout.addSpacing(12)

        # Sign button
        sign_btn_layout = QHBoxLayout()
        self.sign_btn = LocksmithButton("Sign Registry")
        self.sign_btn.setFixedWidth(200)
        self.sign_btn.clicked.connect(self._on_sign_clicked)
        sign_btn_layout.addWidget(self.sign_btn)
        sign_btn_layout.addStretch()

        self.content_layout.addLayout(sign_btn_layout)

    def _add_signed_message(self):
        """Add message indicating user has already signed."""
        success = QLabel("✓ You have signed this registry.")
        success.setStyleSheet(f"font-size: 13px; color: #065f46; font-weight: 600;")
        self.content_layout.addWidget(success)

    def _get_current_account_aid(self) -> str:
        """Get the current user's Castellan account AID."""
        if not self.app or not self.app.vault:
            return ""

        account = self.app.vault.plugin_state.get("castellan", {}).get("account", {})
        return account.get("aid", "")

    @qasync.asyncSlot()
    async def _on_sign_clicked(self):
        """Handle Sign button click - sign the registry IXN event."""
        self.sign_btn.setEnabled(False)
        self.sign_btn.setText("Signing...")

        try:
            # Get the hab for this identifier
            hab = self.app.vault.hby.habs.get(self.aid)
            if not hab:
                self.show_error(f"Identifier {self.aid} is not controlled locally")
                return

            # Get VCP data
            vcp_data = self.identifier.get('vcp', {})
            if not vcp_data:
                self.show_error("No registry VCP data found")
                return

            # For now, show a placeholder message
            logger.info(f"Signing registry for identifier {self.aid}")
            self.show_error("Registry signing not yet implemented")

        except Exception as e:
            logger.exception(f"Error signing registry: {e}")
            self.show_error(f"Error signing registry: {str(e)}")

        finally:
            # Restore button state
            self.sign_btn.setEnabled(True)
            self.sign_btn.setText("Sign Registry")
