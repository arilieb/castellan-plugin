# -*- encoding: utf-8 -*-
"""
castellan.issuers.multisig.initiate module

InitiateMultisigPage — single LocksmithFormPage with four progressive sections
that reveal themselves as each step completes (mirrors locksmith's
WitnessCreatePage pattern; adapted from whisper's init/setup.py).

Sections:
  1. Choose and Upload Identifier   — always visible
  2. Wait for Peers                 — hidden until section 1 complete
  3. Create Group Identifier        — hidden until section 2 continue
  4. Initialization Progress        — hidden until section 3 complete

Differences from the whisper original:
  - No delegator selection (was dead UI in whisper, never wired up).
  - No propagation-mode picker — every multisig EXN is always sent via both
    the castellan /messages relay and the standard KERI mailbox (best-effort).
  - The resulting credential registry is self-backed (noBackers=True, baks=[],
    toad=0) — castellan's registrar API no longer supports registering a new
    TEL registry or acting as a backer for one.
  - Persisted progress is split: a singleton MultisigIdentityState tracks the
    locally-chosen peer-discovery identity (section 1/2), while a keyed
    MultisigInitState (keyed by group_alias) tracks each group-setup attempt
    (section 3/4) — so multiple past/concurrent attempts can coexist once
    surfaced through an issuers CRUD.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Optional

import qasync
from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton,
)
from keri.core.coring import randomNonce
from locksmith.ui import colors
from locksmith.ui.styles import get_monospace_font_family
from locksmith.ui.toolkit.widgets.buttons import (
    LocksmithButton,
    LocksmithInvertedButton,
)
from locksmith.ui.toolkit.widgets.fields import FloatingLabelLineEdit, FloatingLabelComboBox
from locksmith.ui.toolkit.widgets.page import LocksmithFormPage

from .doers import CreateRegistryDoer
from ...core import remoting
from ...db.basing import MultisigIdentityState, MultisigInitState
from ...setup import SegmentedToggle

from keri import help

logger = help.ogler.getLogger(__name__)


def _build_header(title: str, icon_path: str) -> QWidget:
    """Replicates LocksmithFormPage's default header layout (icon + title)."""
    header_container = QWidget()
    header_container.setStyleSheet(f"background-color: {colors.BACKGROUND_CONTENT};")

    header_layout = QHBoxLayout(header_container)
    header_layout.setContentsMargins(20, 30, 20, 20)
    header_layout.setSpacing(10)

    icon_label = QLabel()
    icon_label.setPixmap(QIcon(icon_path).pixmap(52, 52))
    header_layout.addWidget(icon_label)

    title_label = QLabel(title)
    title_label.setStyleSheet("font-size: 42px; font-weight: 200;")
    header_layout.addWidget(title_label)

    header_layout.addStretch()

    return header_container


class InitiateMultisigPage(LocksmithFormPage):
    """
    Single-page multi-step initialization wizard for a Castellan multisig
    group identifier.

    All four steps are sections within this one page.  Sections are QWidget
    containers that start hidden and are revealed (with scroll) as each step
    completes.  `on_show()` resumes any in-progress group-setup attempt so
    users returning mid-setup land at the correct section.
    """

    closed = Signal()

    def __init__(
        self,
        app,
        on_complete: Callable[[str], None] | None = None,
        parent = None,
    ):
        header_content = _build_header(
            "Create a Castellan Multisig", ":/assets/custom/logos/castellan-lightmode.png"
        )
        super().__init__(
            title="Create a Castellan Multisig",
            icon_path=":/assets/material-icons/passport.svg",
            parent=parent,
            header_content=header_content,
        )
        self._reset_button = LocksmithInvertedButton("Cancel")
        self._reset_button.setFixedWidth(100)
        self._reset_button.clicked.connect(self._on_reset_clicked)
        self._parent = parent
        self.app = app
        self.on_complete = on_complete
        self._castellan_identifiers: list[dict] = []
        self._current_group_alias: str | None = None

        # Threshold configuration tracking
        self._account_rows: dict[str, QWidget] = {}
        self._current_account_aid: str = ""

        self._setup_content()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_content(self):
        layout = self.content_layout

        desc = QLabel(
            "Initiate a Castellan multi-participant issuer.  Please select other Users to join and once they do, complete"
            " the setup process."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"font-size: 15px; color: {colors.TEXT_SUBTLE};")
        layout.addWidget(desc)
        layout.addSpacing(20)

        self._build_threshold_section()
        self._current_account_row = self._create_account_row(
            account_name="",  # Will be set when current account is loaded
            account_aid="",
            is_current_account=True,
            show_delete=False
        )
        self._accounts_layout.addWidget(self._current_account_row)


        # Footer — home for the Reset button whenever Create Group Identifier
        self._reset_footer = QWidget()
        reset_footer_layout = QHBoxLayout(self._reset_footer)
        reset_footer_layout.addStretch()
        reset_footer_layout.setContentsMargins(0, 0, 0, 0)
        self._reset_footer_layout = reset_footer_layout
        reset_footer_layout.addWidget(self._reset_button)
        reset_footer_layout.addSpacing(10)
        # Continue button
        continue_layout = QHBoxLayout()
        continue_layout.addStretch()

        self._continue_btn = LocksmithButton("Create")
        self._continue_btn.setFixedWidth(100)
        self._continue_btn.clicked.connect(self._on_threshold_continue)
        self._reset_footer_layout.addWidget(self._continue_btn)
        self._reset_footer_layout.addStretch()

        layout.addStretch()
        layout.addWidget(self._reset_footer)
        layout.addSpacing(20)

    # ------------------------------------------------------------------
    # Section 1.5: Configure Account Thresholds
    # ------------------------------------------------------------------

    def _build_threshold_section(self):
        """Build the threshold configuration section (revealed after Section 1)."""
        self._threshold_section = QWidget()
        section_layout = QVBoxLayout(self._threshold_section)
        section_layout.setContentsMargins(0, 0, 0, 0)
        section_layout.setSpacing(16)

        selector_label = QLabel("Enter name for Multisig Issuer")
        selector_label.setStyleSheet(f"font-weight: 600; font-size: 13px; color: {colors.TEXT_MENU};")
        section_layout.addWidget(selector_label)
        section_layout.addSpacing(6)
        self.multisig_alias = FloatingLabelLineEdit(label_text="Multisig Issuer Name")
        self.multisig_alias.setFixedWidth(240)
        section_layout.addWidget(self.multisig_alias)
        section_layout.addSpacing(12)

        # Description
        desc = QLabel(
            "Configure signing and rotation thresholds for each account participating "
            "in this multisig or for the entire multisig. Use simple thresholds for whole numbers (e.g., '2') or "
            "fractional thresholds for ratios (e.g., '1/3')."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"font-size: 13px; color: {colors.TEXT_SUBTLE};")
        section_layout.addWidget(desc)
        section_layout.addSpacing(12)

        # Threshold mode toggle
        self._threshold_toggle = SegmentedToggle([
            ("simple", "Simple Signing Thresholds",
             ":/assets/material-icons/tag.svg",
             ":/assets/material-icons/tag-dark.svg"),
            ("fractional", "Fractional Signing Thresholds",
             ":/assets/material-icons/donut-small.svg",
             ":/assets/material-icons/donut-small-dark.svg"),
        ])
        self._threshold_toggle.setFixedWidth(525)
        self._threshold_toggle.valueChanged.connect(self._on_threshold_mode_changed)
        section_layout.addWidget(self._threshold_toggle)
        section_layout.addSpacing(20)

        # Account selector
        add_account_header_layout = QHBoxLayout()
        add_account_header_layout.setSpacing(12)

        selector_label = QLabel("Add Account to Multisig")
        selector_label.setStyleSheet(f"font-weight: 600; font-size: 13px; color: {colors.TEXT_MENU};")
        add_account_header_layout.addWidget(selector_label)
        add_account_header_layout.addSpacing(324)

        self._simple_threshold_label = QLabel("Signing Threshold")
        self._simple_threshold_label.setStyleSheet(f"font-weight: 600; font-size: 13px; color: {colors.TEXT_MENU};")
        self._simple_threshold_label.setFixedWidth(150)
        add_account_header_layout.addWidget(self._simple_threshold_label)

        self._rotation_threshold_label = QLabel("Rotation Threshold")
        self._rotation_threshold_label.setStyleSheet(f"font-weight: 600; font-size: 13px; color: {colors.TEXT_MENU};")
        self._rotation_threshold_label.setFixedWidth(150)
        add_account_header_layout.addWidget(self._rotation_threshold_label)
        add_account_header_layout.addStretch()

        section_layout.addLayout(add_account_header_layout)

        section_layout.addSpacing(6)

        add_account_body_layout = QHBoxLayout()
        add_account_body_layout.setSpacing(12)

        self._account_dropdown = FloatingLabelComboBox(label_text="Select Account")
        self._account_dropdown.setFixedWidth(450)
        self._account_dropdown.currentIndexChanged.connect(self._on_account_selected)
        add_account_body_layout.addWidget(self._account_dropdown)
        add_account_body_layout.addSpacing(50)

        self.signing_input = FloatingLabelLineEdit(label_text="")
        self.signing_input.setFixedWidth(120)
        self.signing_input.setPlaceholderText("e.g., 1, 2, etc")
        self.signing_input.line_edit.textChanged.connect(lambda: self._validate_threshold_input(self.signing_input))
        add_account_body_layout.addWidget(self.signing_input)
        add_account_body_layout.addSpacing(34)

        self.rotation_input = FloatingLabelLineEdit(label_text="")
        self.rotation_input.setFixedWidth(120)
        self.rotation_input.setPlaceholderText("e.g., 1, 2, etc")
        self.rotation_input.line_edit.textChanged.connect(lambda: self._validate_threshold_input(self.rotation_input))
        add_account_body_layout.addWidget(self.rotation_input)
        add_account_body_layout.addStretch()

        section_layout.addLayout(add_account_body_layout)


        instruction = QLabel("Select an account from the dropdown to add them to the multisig group.")
        instruction.setStyleSheet(f"font-size: 12px; color: {colors.TEXT_SUBTLE}; font-style: italic;")
        section_layout.addWidget(instruction)

        section_layout.addSpacing(20)

        # Column headers
        headers_layout = QHBoxLayout()
        headers_layout.setSpacing(12)

        # Account Name header (flex width)
        name_header = QLabel("Account Name")
        name_header.setStyleSheet(f"font-weight: 600; font-size: 13px; color: {colors.TEXT_MENU};")
        headers_layout.addWidget(name_header)
        headers_layout.addSpacing(105)

        # Signing Threshold header (fixed width: 150px)
        self.signing_header = QLabel("Signing Threshold")
        self.signing_header.setStyleSheet(f"font-weight: 600; font-size: 13px; color: {colors.TEXT_MENU};")
        self.signing_header.setFixedWidth(150)
        self.signing_header.setVisible(False)
        headers_layout.addWidget(self.signing_header)

        # Rotation Threshold header (fixed width: 150px)
        self.rotation_header = QLabel("Rotation Threshold")
        self.rotation_header.setStyleSheet(f"font-weight: 600; font-size: 13px; color: {colors.TEXT_MENU};")
        self.rotation_header.setFixedWidth(150)
        self.rotation_header.setVisible(False)
        headers_layout.addWidget(self.rotation_header)

        # Spacer for delete icon column (40px)
        headers_layout.addStretch()

        section_layout.addLayout(headers_layout)
        section_layout.addSpacing(8)


        # Container for dynamically added account rows
        self._accounts_container = QWidget()
        self._accounts_layout = QVBoxLayout(self._accounts_container)
        self._accounts_layout.setContentsMargins(0, 0, 0, 0)
        self._accounts_layout.setSpacing(4)
        section_layout.addWidget(self._accounts_container)
        section_layout.addSpacing(16)


        self.content_layout.addWidget(self._threshold_section)

    def _create_account_row(
        self,
        account_name: str,
        account_aid: str = "",
        is_current_account: bool = False,
        show_delete: bool = True
    ) -> QWidget:
        """Create a single account row with threshold inputs and optional delete button."""
        row_widget = QWidget()
        row_widget.setFixedHeight(66)
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 8, 0, 8)
        row_layout.setSpacing(12)

        # Account name label
        name_label = QLabel(account_name + (" (You)" if is_current_account else ""))
        if is_current_account:
            name_label.setStyleSheet(f"font-weight: 600; font-size: 13px; color: {colors.PRIMARY};")
        else:
            name_label.setStyleSheet(f"font-size: 13px; color: {colors.TEXT_MENU};")
        name_label.setFixedWidth(150)
        row_layout.addWidget(name_label)
        row_layout.addSpacing(63)

        # Signing threshold input
        signing_input = FloatingLabelLineEdit(label_text="")
        signing_input.setFixedWidth(120)
        signing_input.setPlaceholderText("e.g., 2 or 1/3")
        signing_input.line_edit.textChanged.connect(lambda: self._validate_threshold_input(signing_input))
        row_layout.addWidget(signing_input)
        row_layout.addSpacing(35)

        # Rotation threshold input
        rotation_input = FloatingLabelLineEdit(label_text="")
        rotation_input.setFixedWidth(120)
        rotation_input.setPlaceholderText("e.g., 2 or 1/3")
        rotation_input.line_edit.textChanged.connect(lambda: self._validate_threshold_input(rotation_input))
        row_layout.addWidget(rotation_input)
        row_layout.addStretch()

                # Delete button (or spacer if current account)
        if show_delete:
            delete_btn = QPushButton()
            delete_btn.setIcon(QIcon(":/assets/material-icons/delete.svg"))
            delete_btn.setFixedSize(32, 32)
            delete_btn.setFlat(True)
            delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            delete_btn.setStyleSheet("""
                QPushButton {
                    border: none;
                    background: transparent;
                }
                QPushButton:hover {
                    background: #f0f0f0;
                    border-radius: 16px;
                }
            """)
            delete_btn.clicked.connect(lambda: self._remove_account_row(row_widget))
            row_layout.addWidget(delete_btn)
        else:
            row_layout.addSpacing(40)

        row_widget.setFixedWidth(540)

        # Store references for threshold visibility toggling
        row_widget._signing_input = signing_input  # type: ignore
        row_widget._rotation_input = rotation_input  # type: ignore
        row_widget._account_aid = account_aid  # type: ignore
        row_widget._is_current = is_current_account  # type: ignore
        row_widget._name_label = name_label  # type: ignore

        # Initially hide threshold inputs (simple mode by default)
        signing_input.setVisible(False)
        rotation_input.setVisible(False)

        return row_widget

    @qasync.asyncSlot()
    async def _load_accounts(self):
        """Load accounts from Castellan server and populate dropdown."""
        if not self.app or not self.app.vault:
            return

        try:
            # Fetch all accounts (unpaginated for simplicity)
            result = await remoting.fetch_accounts(
                app=self.app,
                page=0,
                page_size=100,  # Assume reasonable limit
                filter_term=None,
                order=None
            )

            if not result.get('success'):
                logger.error(f"Failed to load accounts: {result.get('error')}")
                self.show_error("Failed to load accounts from server")
                return

            accounts = result.get('accounts', [])

            # Clear dropdown
            self._account_dropdown.clear()
            self._account_dropdown.addItem("Select account...", userData=None)

            # Get current account AID (from vault state or ESSR context)
            current_aid = self._get_current_account_aid()
            self._current_account_aid = current_aid

            # Populate dropdown (excluding current account)
            for account in accounts:
                aid = account.get('aid', '')
                print(f"looking for {aid}")
                username = account.get('username', '')

                # Skip current account (it's always shown in the fixed row)
                if aid == current_aid:
                    # Set current account row name
                    self._set_current_account_name(username, aid)
                    continue

                # Add to dropdown
                display_name = f"{username} — {aid[:12]}..."
                self._account_dropdown.addItem(display_name, userData=account)

        except Exception as e:
            logger.exception(f"Error loading accounts: {e}")
            self.show_error(f"Error loading accounts: {str(e)}")

    def _get_current_account_aid(self) -> str:
        """Get the AID of the currently authenticated account."""
        # Strategy 1: Check plugin state for current account
        if self.app and self.app.vault:
            state = self.app.vault.plugin_state.get("castellan", {})
            settings = state.get("settings")
            if settings and hasattr(settings, 'issuer_aid') and settings.issuer_aid:
                return settings.issuer_aid

        return ""

    def _set_current_account_name(self, username: str, aid: str):
        """Update the current account row with the username."""
        if hasattr(self, '_current_account_row'):
            # Find the name label in the row and update it
            name_label = self._current_account_row._name_label  # type: ignore
            if name_label:
                name_label.setText(f"{username} (You)")
            # Store the AID
            self._current_account_row._account_aid = aid  # type: ignore

    def _on_account_selected(self, index: int):
        """Handle account selection from dropdown - add as new row."""
        if index <= 0:  # Skip placeholder
            return

        account = self._account_dropdown.currentData()
        if not account or not isinstance(account, dict):
            return

        aid = account.get('aid', '')
        username = account.get('username', '')

        # Prevent duplicates
        if aid in self._account_rows:
            logger.warning(f"Account {username} already added")
            self._account_dropdown.setCurrentIndex(0)
            return

        # Create and add the row
        row = self._create_account_row(
            account_name=username,
            account_aid=aid,
            is_current_account=False,
            show_delete=True
        )

        self._accounts_layout.addWidget(row)
        self._account_rows[aid] = row

        # Apply current threshold visibility mode
        self._update_threshold_visibility(row)

        # Reset dropdown to placeholder
        self._account_dropdown.setCurrentIndex(0)

        logger.info(f"Added account: {username} ({aid})")

    def _remove_account_row(self, row_widget: QWidget):
        """Remove an account row from the UI and state."""
        # Find the AID for this row
        aid_to_remove: str = ""
        for aid, row in self._account_rows.items():
            if row == row_widget:
                aid_to_remove = aid
                break

        if aid_to_remove:
            # Remove from layout
            self._accounts_layout.removeWidget(row_widget)
            row_widget.deleteLater()

            # Remove from tracking dict
            del self._account_rows[aid_to_remove]

            logger.info(f"Removed account: {aid_to_remove}")

    def _on_threshold_mode_changed(self, mode: str):
        """Handle threshold mode toggle - show/hide threshold inputs."""
        show_thresholds = (mode == "fractional")

        self._simple_threshold_label.setVisible(not show_thresholds)
        self._rotation_threshold_label.setVisible(not show_thresholds)

        self.signing_input.setVisible(not show_thresholds)
        self.rotation_input.setVisible(not show_thresholds)

        # Update current account row
        self._update_threshold_visibility(self._current_account_row, show_thresholds)

        # Update all added account rows
        for row in self._account_rows.values():
            self._update_threshold_visibility(row, show_thresholds)

        logger.debug(f"Threshold mode changed to: {mode}")

    def _update_threshold_visibility(self, row_widget: QWidget, show: Optional[bool] = None):
        """Show or hide threshold inputs for a single row."""
        if show is None:
            # Determine from toggle state
            show = (self._threshold_toggle.value() == "fractional")

        # Access stored input references
        self.signing_header.setVisible(show)
        self.rotation_header.setVisible(show)
        
        if hasattr(row_widget, '_signing_input') and hasattr(row_widget, '_rotation_input'):
            row_widget._signing_input.setVisible(show)
            row_widget._rotation_input.setVisible(show)

    def _validate_threshold_input(self, input_field: FloatingLabelLineEdit):
        """Validate threshold input - accept integers or fractions (e.g., '2' or '1/3')."""
        text = input_field.text().strip()

        if not text:
            # Empty is OK (will be validated on submit)
            input_field.setStyleSheet("")
            return True

        # Check for integer
        if text.isdigit():
            input_field.setStyleSheet("")
            return True

        # Check for fraction (numerator/denominator)
        if '/' in text:
            parts = text.split('/')
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                numerator = int(parts[0])
                denominator = int(parts[1])
                if denominator > 0 and numerator <= denominator:
                    input_field.setStyleSheet("")
                    return True

        # Invalid format
        input_field.setStyleSheet("border: 1px solid #ff0000;")
        return False

    def _collect_threshold_data(self) -> dict[str, dict]:
        """Collect threshold configuration for all accounts.

        Returns:
            Dict mapping AID to {'signing': str, 'rotation': str}
        """
        threshold_data = {}

        # Collect from current account row
        if hasattr(self, '_current_account_row'):
            aid = self._current_account_row._account_aid  # type: ignore
            if aid:
                threshold_data[aid] = {
                    'signing': self._current_account_row._signing_input.text().strip(),  # type: ignore
                    'rotation': self._current_account_row._rotation_input.text().strip(),  # type: ignore
                }

        # Collect from added account rows
        for aid, row in self._account_rows.items():
            threshold_data[aid] = {
                'signing': row._signing_input.text().strip(),
                'rotation': row._rotation_input.text().strip(),
            }

        return threshold_data

    @qasync.asyncSlot()
    async def _on_threshold_continue(self):
        """Validate threshold configuration and proceed to Section 2."""
        # Validate all threshold inputs
        alias = self.multisig_alias.text()
        if not alias:
            self.show_error("Please enter a multisig alias.")
            return

        threshold_type = self._threshold_toggle.value()
        threshold_data = self._collect_threshold_data()

        if threshold_type == "simple":
            try:
                simple_signing_threshold = int(self.signing_input.text().strip())
                if simple_signing_threshold < 1:
                    self.show_error("Please enter a simple signing threshold greater than 0.")
                    return
            except ValueError:
                self.show_error("Please enter a valid simple signing threshold.")
                return

            try:
                simple_rotation_threshold = int(self.rotation_input.text().strip())
                if simple_rotation_threshold < 1:
                    self.show_error("Please enter a simple rotation threshold greater than 0.")
                    return
            except ValueError:
                self.show_error("Please enter a valid simple rotation threshold.")
                return
        else:
            simple_signing_threshold = ""
            simple_rotation_threshold = ""

            if len(threshold_data) < 2:
                self.show_error("Please add at least one other account to the multisig group.")
                return

            errors = []
            for aid, thresholds in threshold_data.items():
                aid_display = aid[:12] + "..." if len(aid) > 12 else aid

                if not thresholds['signing']:
                    errors.append(f"Missing signing threshold for account {aid_display}")
                elif not self._validate_threshold_format(thresholds['signing']):
                    errors.append(f"Invalid signing threshold format for account {aid_display}")

                if not thresholds['rotation']:
                    errors.append(f"Missing rotation threshold for account {aid_display}")
                elif not self._validate_threshold_format(thresholds['rotation']):
                    errors.append(f"Invalid rotation threshold format for account {aid_display}")

            if errors:
                self.show_error("\n".join(errors))
                return

        nonce = randomNonce()
        local_member_hab = self.app.vault.hby.makeHab(f"{alias}_local_aid_{nonce}", ns="_castellan_multisig",
                                                      icount=1, isith="1",
                                                      ncount=1, nsith="1",
                                                      toad=0, transferable=True)
        kel = local_member_hab.replay()

        multisig_data = dict(
            alias=alias,
            local_member_aid=local_member_hab.pre,
            signing_threshold=simple_signing_threshold,
            rotation_threshold=simple_rotation_threshold,
            members=[(aid, thresholds['signing'], thresholds['rotation']) for aid, thresholds in threshold_data.items()]
        )

        # Store threshold data in state for use in Section 3 (group creation)
        await self._save_threshold_configuration(kel, multisig_data)

        # Hide continue button and reveal Section 2
        self._continue_btn.setEnabled(False)
        self.show_success("Multisig identifier created.  Waiting for peers to join.")
        logger.info(f"Threshold configuration saved: {threshold_data}")

    @staticmethod
    def _validate_threshold_format(threshold: str) -> bool:
        """Validate threshold string format (int or fraction)."""
        if threshold.isdigit():
            return True
        if '/' in threshold:
            parts = threshold.split('/')
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                return int(parts[1]) > 0 and int(parts[0]) <= int(parts[1])
        return False

    async def _save_threshold_configuration(self, kel: bytes, multisig_data: dict):
        """Store threshold configuration and create multisig identifier on server."""
        self._pending_threshold_config = multisig_data
        logger.debug(f"Stored pending threshold configuration: {multisig_data}")

        # Create multisig identifier on Castellan server
        result = await remoting.create_multisig_identifier(
            app=self.app,
            kel=kel,
            multisig_data=multisig_data
        )

        if not result.get('success'):
            error_msg = result.get('error', 'Unknown error')
            logger.error(f"Failed to create multisig identifier: {error_msg}")
            self.show_error(f"Failed to create multisig on server: {error_msg}")
            # Re-enable continue button on failure
            self._continue_btn.setEnabled(True)
            return

        logger.info(f"Successfully created multisig identifier on server: {result.get('data')}")
        self._reset_button.setText("Done")
        self._continue_btn.setEnabled(False)

    @staticmethod
    def _make_progress_frame(title: str) -> tuple["QFrame", "QVBoxLayout"]:
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame {{ border: 1px solid {colors.BORDER}; border-radius: 8px; "
            f"background: {colors.BACKGROUND_CONTENT}; padding: 16px; }}"
        )
        frame.setFixedWidth(510)
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(8, 8, 8, 8)
        fl.setSpacing(2)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(
            f"font-weight: bold; font-size: 15px; color: {colors.TEXT_MENU};"
        )
        fl.addWidget(title_lbl)

        participants_container = QWidget()
        participants_layout = QVBoxLayout(participants_container)
        participants_layout.setContentsMargins(0, 0, 0, 0)
        participants_layout.setSpacing(0)
        fl.addWidget(participants_container)

        return frame, participants_layout

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _scroll_to_bottom(self):
        QTimer.singleShot(
            100,
            lambda: self.scroll_area.verticalScrollBar().setValue(
                self.scroll_area.verticalScrollBar().maximum()
            ),
        )

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    def _get_db(self):
        return self.app.vault.plugin_state.get("castellan", {}).get("db")

    def _get_identity_state(self) -> MultisigIdentityState:
        db = self._get_db()
        if db is None:
            return MultisigIdentityState()
        return db.castellan_multisig_identity.get(keys=("self",)) or MultisigIdentityState()

    def _save_identity_state(self, state: MultisigIdentityState):
        db = self._get_db()
        if db is not None:
            db.castellan_multisig_identity.pin(keys=("self",), val=state)

    def _get_group_state(self, alias: str) -> MultisigInitState:
        db = self._get_db()
        if db is None:
            return MultisigInitState(group_alias=alias)
        return db.castellan_multisig_init.get(keys=(alias,)) or MultisigInitState(group_alias=alias)

    def _save_group_state(self, state: MultisigInitState):
        db = self._get_db()
        if db is not None:
            db.castellan_multisig_init.pin(keys=(state.group_alias,), val=state)

    def _save_threshold_config_to_group_state(self, group_alias: str):
        """Save the pending threshold configuration to the group state."""
        if hasattr(self, '_pending_threshold_config'):
            state = self._get_group_state(group_alias)
            state.threshold_config = self._pending_threshold_config
            self._save_group_state(state)
            logger.info(f"Saved threshold config to group state for {group_alias}")

    def _find_incomplete_group_alias(self) -> str | None:
        """Find the most recent in-progress (not yet complete) group-setup attempt."""
        db = self._get_db()
        if db is None:
            return None
        for (alias,), state in db.castellan_multisig_init.getItemIter():
            if not state.init_complete:
                return alias
        return None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def showEvent(self, event):
        """Qt lifecycle hook — fires whenever setCurrentWidget makes us visible."""
        super().showEvent(event)


    def on_show(self):
        """Called when the page becomes visible. Resumes any in-progress attempt."""
        self.clear_error()
        self.clear_success()
        self._load_accounts()

    def _on_reset_clicked(self):
        self._reset_button.setEnabled(False)
        self._reset_button.setText("Closing…")
        self.clear_error()
        self.clear_success()

        self.multisig_alias.setText("")
        self.signing_input.setText("")
        self.rotation_input.setText("")

        while self._accounts_layout.count():
            item = self._accounts_layout.takeAt(0)
            if item.widget():
                w = item.widget()
                w.setParent(None)

        self._account_rows.clear()

        settings = self.app.vault.plugin_state.get("castellan", {}).get("settings")
        # Current account row (special - no delete button)
        self._current_account_row = self._create_account_row(
            account_name=settings.username if settings else "",  # Will be set when current account is loaded
            account_aid=settings.issuer_aid if settings else "",
            is_current_account=True,
            show_delete=False
        )
        self._accounts_layout.addWidget(self._current_account_row)

        self._current_group_alias = None
        self._castellan_identifiers = []

        self._reset_button.setText("Cancel")
        self._reset_button.setEnabled(True)
        self._continue_btn.setEnabled(True)

        self.closed.emit()

    def _launch_create_registry_doer(self, group_alias: str):
        """Launch CreateRegistryDoer for the given group alias."""
        registry_name = f"{group_alias}-registry"
        doer = CreateRegistryDoer(
            app=self.app,
            hab_alias=group_alias,
            registry_name=registry_name,
            signal_bridge=self.app.vault.signals,
        )
        self.app.vault.extend([doer])

    # ------------------------------------------------------------------
    # Doer event listener
    # ------------------------------------------------------------------

    async def _upload_group_identifier(self, group_alias: str) -> None:
        """
        Best-effort upload of the group identifier to castellan, mirroring
        _on_upload_clicked's oobi/KEL construction. All participants resolve
        to the same (aid, alias) pair, so a re-upload by a later joiner is a
        harmless no-op server-side.
        """
        ghab = self.app.vault.hby.habByName(group_alias)
        if ghab is None:
            logger.warning(f"Could not find group hab '{group_alias}' to upload to castellan")
            return

        oobi = ""
        try:
            oobi_result = ghab.makeOwnEndRole()
            if oobi_result:
                oobi = oobi_result.decode() if isinstance(oobi_result, bytes) else str(oobi_result)
        except Exception:
            pass

        try:
            kel_bytes = b"".join(self.app.vault.hby.db.clonePreIter(pre=ghab.pre, fn=0))
        except Exception as e:
            logger.warning(f"Failed to serialize KEL for group identifier '{group_alias}': {e}")
            return

        if not kel_bytes:
            logger.warning(f"No KEL events found for group identifier '{group_alias}' — cannot upload")
            return

        result = await remoting.upload_identifier(
            self.app, aid=ghab.pre, alias=ghab.name, kel_bytes=kel_bytes, oobi=oobi
        )
        if not result.get("success") and not result.get("conflict"):
            logger.warning(
                f"Failed to upload group identifier '{group_alias}' to castellan: {result.get('error')}"
            )

    def _resolve_aid_alias(self, aid: str) -> str:
        hab = self.app.vault.hby.habs.get(aid)
        if hab:
            return hab.name
        contact = self.app.vault.org.get(aid)
        if contact:
            return contact.get("alias", "")
        return ""

    def _get_group_smids(self, group_alias: str) -> list[str]:
        if not group_alias:
            return []
        ghab = self.app.vault.hby.habByName(group_alias)
        if ghab is None:
            return []
        return list(self.app.vault.hby.db.signingMembers(pre=ghab.pre))

    def _build_signing_rows(
            self,
            participants_layout: "QVBoxLayout",
            participant_labels_dict: dict,
            smids: list[str],
            signed_aids: list[str],
    ) -> None:
        """Clear and rebuild participant signing rows into participants_layout."""
        while participants_layout.count():
            item = participants_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        participant_labels_dict.clear()

        for aid in smids:
            signed = aid in signed_aids
            alias = self._resolve_aid_alias(aid)
            text = f"{'✓ ' if signed else '○ '}{alias} — {aid}" if alias else f"{'✓ ' if signed else '○ '}{aid}"
            lbl = QLabel(text)
            lbl.setStyleSheet(
                f"font-size: 11px; color: {colors.SUCCESS if signed else colors.TEXT_SUBTLE}; border: none;"
            )
            participants_layout.addWidget(lbl)
            participant_labels_dict[aid] = lbl

    def _update_signing_row(
            self, participant_labels_dict: dict, aid: str, signed: bool
    ) -> None:
        lbl = participant_labels_dict.get(aid)
        if lbl is None:
            return
        alias = self._resolve_aid_alias(aid)
        prefix = "✓ " if signed else "○ "
        lbl.setText(f"{prefix}{alias} — {aid}" if alias else f"{prefix}{aid}")
        lbl.setStyleSheet(
            f"font-size: 11px; color: {colors.SUCCESS if signed else colors.TEXT_SUBTLE}; border: none;"
        )

    def _make_participant_label_row(self, aid: str) -> "QWidget":
        """Two-label row (name bold 15px / AID monospace 11px) for frozen s3 display."""
        alias = self._resolve_aid_alias(aid)
        widget = QWidget()
        vbox = QVBoxLayout(widget)
        vbox.setContentsMargins(8, 8, 0, 6)
        vbox.setSpacing(2)
        name_lbl = QLabel(alias if alias else aid[:24] + "…")
        name_lbl.setStyleSheet(
            f"font-size: 15px; font-weight: 600; color: {colors.TEXT_MENU};"
        )
        aid_lbl = QLabel(aid)
        aid_lbl.setStyleSheet(
            f"font-size: 11px; color: {colors.TEXT_SUBTLE}; font-family: {get_monospace_font_family()};"
        )
        vbox.addWidget(name_lbl)
        vbox.addWidget(aid_lbl)
        return widget
