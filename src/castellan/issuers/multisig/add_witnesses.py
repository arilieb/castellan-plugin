# castellan/issuers/multisig/configure.py
# -*- encoding: utf-8 -*-
"""
castellan.issuers.multisig.configure module

Page for preparing a multisig identifier as a Castellan Issuer.

"""
import qasync
from PySide6.QtCore import Signal, Qt, QTimer
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame
from keri import help
from locksmith.core import witnessing, rotating
from locksmith.ui import colors
from locksmith.ui.toolkit.widgets import LocksmithLineEdit
from locksmith.ui.toolkit.widgets.buttons import LocksmithButton, LocksmithInvertedButton
from locksmith.ui.toolkit.widgets.extensible import ExtensibleSelectorWidget
from locksmith.ui.toolkit.widgets.page import LocksmithFormPage
from locksmith.ui.vault.healthKERI.core import remoting as base_remoting
from locksmith.ui.vault.healthKERI.identifiers.update import SendKeystateUpdateDialog
from locksmith.ui.vault.identifiers.authenticate import WitnessAuthenticationDialog

from ...core import remoting

logger = help.ogler.getLogger(__name__)


class ConfigureIssuerMultisigIdentifier(LocksmithFormPage):
    """Full-page form for creating a new witness."""

    witness_created = Signal()  # Emits the created witness
    cancelled = Signal()
    _identifiers_loaded = Signal(dict)  # Internal signal for async data
    _capacity_loaded = Signal(dict)  # Internal signal for capacity data

    def __init__(self, app, parent = None):
        super().__init__(
            title="Configure Issuer Identifier",
            icon_path=":/assets/material-icons/group.svg",
            parent=parent
        )
        self._parent = parent
        self.app = app
        self.aid = None
        self.hab = None
        self.identifier = None
        self.vault_name = ""
        self._identifiers_data = None
        self._available_capacity = 0  # Track available witness capacity
        self._unused_witnesses = None
        self._current_witnesses = None

        self._setup_content()

    def _setup_content(self):
        """Set up the page content within the superclass layout."""
        # Use self.content_layout from LocksmithFormPage

        sub_header_label = QLabel("To begin issuing credentials with this identifier, you need to configure a few things. "
                                  "You will need to add witnesses, add a mailbox and upload credential schema.  Other members of your "
                                  "multisig identifier may be needed to approve these actions based on your signing threshold.")
        sub_header_label.setWordWrap(True)
        sub_header_label.setStyleSheet(f"font-size: 15px; color: {colors.TEXT_SUBTLE};")
        self.content_layout.addWidget(sub_header_label)

        self.content_layout.addSpacing(50)

        threshold_label = QLabel("Add Witnesses")
        threshold_label.setStyleSheet(f"font-weight: bold; font-size: 20px; color: {colors.TEXT_MENU};")
        self.content_layout.addWidget(threshold_label)

        self.content_layout.addSpacing(10)

        threshold_sub_label = QLabel("Select witnesses to add to this identifier.  You need to OOBI with witnesses before adding them here.")
        threshold_sub_label.setStyleSheet(f"font-size: 13px; color: {colors.TEXT_SUBTLE}; font-weight: 200;")
        self.content_layout.addWidget(threshold_sub_label)

        self.content_layout.addSpacing(10)

        self.add_witness_selector = ExtensibleSelectorWidget(
            dropdown_label="Select Witnesses",
            selector_dropdown_items=[],
            max_scrollable_height=225
        )
        self.add_witness_selector.setFixedWidth(450)
        self.add_witness_selector.setFixedHeight(100)

        # Connect to update recommended TOAD when witnesses change
        self.add_witness_selector.itemAdded.connect(self._on_witness_selection_changed)
        self.add_witness_selector.itemRemoved.connect(self._on_witness_selection_changed)

        self.content_layout.addWidget(self.add_witness_selector)

        self.content_layout.addSpacing(10)

        threshold_label = QLabel("Witness Signing Threshold")
        threshold_label.setStyleSheet(f"font-weight: bold; font-size: 20px; color: {colors.TEXT_MENU};")
        self.content_layout.addWidget(threshold_label)

        self.content_layout.addSpacing(10)

        threshold_sub_label = QLabel("The number of witness signatures required for valid events (must be less than or equal to number of witnesses).")
        threshold_sub_label.setStyleSheet(f"font-size: 13px; color: {colors.TEXT_SUBTLE}; font-weight: 200;")
        self.content_layout.addWidget(threshold_sub_label)
        self.content_layout.addSpacing(25)

        # Create threshold frame
        threshold_frame = QFrame()
        threshold_frame.setFixedWidth(465)
        threshold_frame.setFixedHeight(100)
        threshold_frame.setStyleSheet("""
            QFrame {
                border: 1px solid #E0E0E0;
                border-radius: 4px;
            }
        """)

        threshold_frame_layout = QHBoxLayout(threshold_frame)
        threshold_frame_layout.setContentsMargins(40, 20, 40, 20)
        threshold_frame_layout.setSpacing(18)

        # Threshold edit control
        self._threshold_edit = LocksmithLineEdit()
        self._threshold_edit.setFixedSize(40, 40)
        threshold_frame_layout.addWidget(self._threshold_edit)

        # Labels column
        labels_layout = QVBoxLayout()
        labels_layout.setSpacing(5)

        # Main label
        threshold_main_label = QLabel("Signing Threshold")
        threshold_main_label.setStyleSheet("font-weight: bold; font-size: 16px; color: #43474E; border: none;")
        labels_layout.addWidget(threshold_main_label)

        # Sub label
        threshold_sub_label = QLabel("We default to the suggested threshold for the number of witnesses you are adding")
        threshold_sub_label.setStyleSheet(f"font-size: 12px; color: {colors.TEXT_SUBTLE}; font-weight: 200; border: none;")
        threshold_sub_label.setWordWrap(True)
        labels_layout.addWidget(threshold_sub_label)

        threshold_frame_layout.addLayout(labels_layout)
        threshold_frame_layout.addStretch()

        self.content_layout.addWidget(threshold_frame)

        self.content_layout.addSpacing(40)

        # Create and Cancel buttons layout
        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()

        self.cancel_button = LocksmithInvertedButton("Cancel")
        self.cancel_button.setFixedWidth(100)
        self.cancel_button.clicked.connect(self._on_done_clicked)
        buttons_layout.addWidget(self.cancel_button)

        buttons_layout.addSpacing(10)

        self.add_witnesses_button = LocksmithButton("Add Witnesses")
        self.add_witnesses_button.setFixedWidth(175)
        self.add_witnesses_button.clicked.connect(self._on_add_witnesses_clicked)
        buttons_layout.addWidget(self.add_witnesses_button)

        buttons_layout.addStretch()
        self.content_layout.addLayout(buttons_layout)

        # OOBI panels section (hidden initially)
        self.oobi_section = QWidget()
        self.oobi_section.hide()
        self.oobi_section_layout = QVBoxLayout(self.oobi_section)
        self.oobi_section_layout.setContentsMargins(0, 0, 0, 0)
        self.oobi_section_layout.setSpacing(20)
        self.content_layout.addWidget(self.oobi_section)

        self.content_layout.addStretch()

        # Store references for created witnesses
        self.created_witnesses = []
        self.oobi_panels = []
        self.otp_panels = []
        self.introduce_button = None
        self.otp_section = None

    @staticmethod
    def _format_witness_display_name(witness: dict) -> str:
        """
        Format a witness for display in dropdowns using alias and full EID.

        Args:
            witness: Witness dict with 'alias' and 'id' keys

        Returns:
            Formatted string like "witnessme-wi-nyc-01 :: BB0SSuchr-x2llqi3DtEJt-pP55NBXs3OIMO9C6IVHxJ"
        """
        alias = witness.get('alias', 'Unknown')
        witness_id = witness.get('id', '')
        return f"{alias} - {witness_id}"

    def set_vault_name(self, vault_name: str):
        """Set the vault name for this page."""
        self.vault_name = vault_name

    def on_show(self, aid=None, identifier=None):
        """Called when the page becomes visible."""
        logger.info(f"WitnessCreatePage: on_show({aid})")
        self.aid = aid
        self.identifier = identifier

        self.hab = self.app.hby.habs[self.aid]
        self._unused_witnesses = witnessing.get_unused_witnesses_for_rotation(self.app, self.hab)
        self._current_witnesses = witnessing.get_current_witnesses_for_rotation(self.app, self.hab)

        witness_items = [
            (self._format_witness_display_name(witness), witness)
            for witness in self._unused_witnesses
        ]

        self.add_witness_selector._populate_dropdown(witness_items)

        self.clear_error()
        self.clear_success()
        # Load data sequentially to avoid connection race conditions
        self._load_page_data()

    def _on_witness_selection_changed(self, _text, _data):
        """Update recommended TOAD when witness selections change."""
        self._update_recommended_toad()

    def _get_resulting_witness_count(self):
        """Calculate the witness count after rotation."""
        current_count = len(self.hab.kever.wits)

        adds_count = 0
        if self.add_witness_selector:
            adds_count = len(self.add_witness_selector.get_selected_items())

        return current_count + adds_count

    def _update_recommended_toad(self):
        """Update the TOAD field with recommended value based on resulting witness count."""
        resulting_count = self._get_resulting_witness_count()
        recommended_toad = rotating.recommend_toad(resulting_count)
        self._threshold_edit.setText(str(recommended_toad))
        # Clear any previous error
        self.clear_error()


    @qasync.asyncSlot()
    async def _load_page_data(self):
        """Load all page data sequentially to avoid connection race conditions."""
        # Load identifiers first
        await self._load_identifiers()
        # Then load capacity
        await self._load_capacity()

    async def _load_identifiers(self):
        """Fetch and populate account identifiers for the dropdown."""
        logger.info("Loading account identifiers for witness creation")
        try:
            identifiers = await base_remoting.get_account_identifiers_for_dropdown(
                self.app,
                page_size=1000  # Get all identifiers
            )
            # Check if it's an error response
            if isinstance(identifiers, dict) and 'success' in identifiers and not identifiers['success']:
                error_msg = identifiers.get('error', 'Unknown error loading identifiers')
                logger.error(f"Failed to load identifiers: {error_msg}")
                self.show_error(f"Failed to load identifiers: {error_msg}")
                return

            self._identifiers_loaded.emit(identifiers)  # Emit signal with data
        except Exception as e:
            logger.exception(f"Failed to load identifiers: {e}")
            self.show_error(f"Failed to load identifiers: {e}")

    async def _load_capacity(self):
        """Fetch witness capacity information from the backend."""
        logger.info("Loading witness capacity for region configuration")
        try:
            result = await base_remoting.get_witness_capacity(self.app)
            if result.get('success'):
                self._capacity_loaded.emit(result)
            else:
                error_msg = result.get('error', 'Unknown error loading capacity')
                logger.error(f"Failed to load capacity: {error_msg}")
                self.show_error(f"Failed to load capacity: {error_msg}")
        except Exception as e:
            logger.exception(f"Failed to load capacity: {e}")
            self.show_error(f"Failed to load capacity: {e}")

    async def _check_identifier_sync(self, alias: str) -> tuple[bool, int, int]:
        """
        Check if an identifier's local keystate is ahead of remote.

        Args:
            alias: The identifier alias to check

        Returns:
            Tuple of (is_out_of_sync, local_sn, remote_sn)
        """
        try:
            # Get local hab
            hab = self.app.vault.hby.habByName(alias)
            if not hab:
                logger.warning(f"No local hab found for alias: {alias}")
                return (False, 0, 0)

            local_sn = hab.kever.sner.num

            # Fetch remote keystate
            response = await base_remoting.fetch_account_identifier(self.app, hab.pre)
            if not response.get('success'):
                logger.warning(f"Failed to fetch remote identifier for {alias}")
                return (False, local_sn, 0)

            remote_key_state = response.get('key_state', {})
            remote_sn_hex = remote_key_state.get('s', '0')

            try:
                remote_sn = int(remote_sn_hex, 16) if remote_sn_hex else 0
            except ValueError:
                remote_sn = 0

            is_out_of_sync = local_sn > remote_sn

            if is_out_of_sync:
                logger.info(f"Identifier {alias} is out of sync: local={local_sn}, remote={remote_sn}")

            return (is_out_of_sync, local_sn, remote_sn)

        except Exception as e:
            logger.exception(f"Error checking sync status for {alias}: {e}")
            return (False, 0, 0)

    async def _spawn_keystate_update_dialog(self, alias: str):
        """
        Spawn the SendKeystateUpdateDialog for an out-of-sync identifier.

        Args:
            alias: The identifier alias that needs updating
        """
        try:
            # Use the async factory method to create the dialog
            dialog = await SendKeystateUpdateDialog.create(
                icon_path=":/assets/material-icons/badge.svg",
                app=self.app,
                identifier_alias=alias,
                parent=self._parent
            )

            # Connect success signal to handler
            dialog.keystate_updated.connect(self._on_keystate_updated)

            # Open the dialog
            dialog.open()

        except Exception as e:
            logger.exception(f"Error spawning keystate update dialog: {e}")
            self.show_error(f"Failed to open keystate update dialog: {e}")

    def _on_keystate_updated(self, alias: str):
        """
        Handle successful keystate update.

        Shows success message and clears any previous errors.
        User must click Create button again to proceed with witness creation.

        Args:
            alias: The identifier alias that was updated
        """
        logger.info(f"Keystate update successful for {alias}")
        self.clear_error()
        self.show_success(f"Keystate update for {alias} was successful.")

    def _validate_form(self) -> bool:
        """
        Validate the form before adding witnesses.

        Returns:
            bool: True if valid, False otherwise.
        """
        self.clear_error()

        witnesses = self.add_witness_selector.get_selected_items()
        if len(witnesses) == 0:
            self.show_error("Please select at least one witness.")
            return False

        threshold_value = self._threshold_edit.text().strip()
        if not threshold_value or not threshold_value.isdigit():
            self.show_error("Threshold must be a positive integer.")
            return False

        threshold = int(threshold_value)
        resulting_witness_count = self._get_resulting_witness_count()

        if threshold < 1:
            self.show_error("Threshold must be at least 1.")
            return False

        if threshold > resulting_witness_count:
            self.show_error(f"Threshold cannot be greater than the total number of witnesses ({resulting_witness_count}).")
            return False

        return True

    @qasync.asyncSlot()
    async def _on_add_witnesses_clicked(self):
        """Handle Add Witnesses button click."""
        # Validate form
        multisig_id = self.identifier.get('id')
        if not self._validate_form():
            return

        # Disable button during creation
        self.add_witnesses_button.setEnabled(False)
        self.add_witnesses_button.setText("Adding...")
        self.cancel_button.setText("Close")
        self.cancel_button.setEnabled(False)

        try:
            # Get selected witnesses
            selected_witnesses = self.add_witness_selector.get_selected_items()

            # Format witness data for API
            added_witnesses = []
            for display_text, witness_data in selected_witnesses:
                added_witnesses.append({
                    'aid': witness_data.get('id', ''),
                    'alias': witness_data.get('alias', ''),
                    'oobi': witness_data.get('oobi', ''),
                })

            # Get threshold
            threshold = int(self._threshold_edit.text().strip())

            hab = self.app.vault.hby.habs.get(self.aid)
            if not hab:
                self.show_error(f"Identifier {self.aid} is not controlled locally")
                return

            member_index = hab.smids.index(hab.mhab.pre)
            tholder = hab.kever.tholder

            # If our signature is enough to create the registry, do so, otherwise create without parsing
            if tholder.satisfy([member_index]):
                self._awaiting_auth = True
                adds = [wit['aid'] for wit in added_witnesses]

                await remoting.rotate_multisig_identifier(self.app, hab,
                                                          isith=hab.kever.ntholder.sith, nsith=hab.kever.ntholder.sith,
                                                          toad=threshold, cuts=[], adds=adds)

                self.app.vault.signals.doer_event.connect(self._on_doer_event)
                auth_dialog = WitnessAuthenticationDialog(
                    app=self.app,
                    hab=hab,
                    witness_ids=adds,
                    auth_only=False,
                    parent=self,
                )
                auth_dialog.open()
            else:

                logger.info(f"Adding {len(added_witnesses)} witnesses to {self.aid} with threshold {threshold}")

                # Call API to add witnesses
                result = await remoting.update_multisig_witnesses(
                    app=self.app,
                    multisig_id=multisig_id,
                    adds=added_witnesses,
                    witness_threshold=threshold,
                    cuts=[],  # No cuts for now
                )

                if result.get('success'):
                    logger.info(f"Successfully added witnesses to {self.aid}")

                    # Clear errors on success
                    self.clear_error()
                    self.show_success(f"Successfully added {len(added_witnesses)} witness{'es' if len(added_witnesses) != 1 else ''} to identifier.")

                    # Reset form
                    self.add_witness_selector.clear_selections()
                    self._threshold_edit.clear()


                else:
                    error = result.get('error', 'Unknown error')
                    logger.error(f"Failed to add witnesses: {error}")
                    self.show_error(f"Failed to add witnesses: {error}")

                    self.add_witnesses_button.setEnabled(True)
                    self.add_witnesses_button.setText("Add Witnesses")


        except Exception as e:
            logger.exception(f"Error adding witnesses: {e}")
            self.show_error(f"Error adding witnesses: {e}")

            self.add_witnesses_button.setEnabled(True)
            self.add_witnesses_button.setText("Add Witnesses")
            self.cancel_button.setEnabled(True)
            self.cancel_button.setText("Cancel")

    @qasync.asyncSlot(str, str, dict)
    async def _on_doer_event(self, doer_name: str, event_type: str, data: dict):
        """
        Handle auth codes entered from WitnessAuthenticationDialog.

        Args:
            data: Dictionary containing 'codes' key with list of "witness_id:passcode" strings
        """
        if doer_name != "AuthenticateWitnessesDoer":
            return

        if data['pre'] != self.aid:
            return

        if event_type == "witness_authentication_failed":
            error = data['error']
            logger.error(f"Failed to add witnesses: {error}")
            self.show_error(f"Failed to add witnesses: {error}")

            self.add_witnesses_button.setEnabled(True)
            self.add_witnesses_button.setText("Add Witnesses")
            return

        # Assumes event_type is "witness_authentication_success"

        multisig_id = self.identifier.get('id')
        self.app.vault.signals.doer_event.disconnect(self._on_doer_event)

        if not self._awaiting_auth:
            return

        self._awaiting_auth = False

        selected_witnesses = self.add_witness_selector.get_selected_items()

        # Format witness data for API
        adds = []
        for display_text, witness_data in selected_witnesses:
            adds.append({
                'aid': witness_data.get('id', ''),
                'alias': witness_data.get('alias', ''),
                'oobi': witness_data.get('oobi', ''),
            })

        rot = self.hab.db.cloneEvtMsg(self.hab.pre, 0, self.hab.kever.serder.said)
        # Call API to add witnesses
        result = await remoting.complete_multisig_witnesses(
            app=self.app,
            multisig_id=multisig_id,
            rot=rot,
            data=adds,
        )

        if result.get('success'):
            logger.info(f"Successfully added witnesses to {self.aid}")

            # Clear errors on success
            self.clear_error()
            self.show_success(f"Successfully added {len(adds)} witness{'es' if len(adds) != 1 else ''} to identifier.")

            # Reset form
            self.add_witness_selector.clear_selections()
            self._threshold_edit.clear()


        else:
            error = result.get('error', 'Unknown error')
            logger.error(f"Failed to add witnesses: {error}")
            self.show_error(f"Failed to add witnesses: {error}")

            self.add_witnesses_button.setEnabled(True)
            self.add_witnesses_button.setText("Add Witnesses")

        self.cancel_button.setText("Done")
        self.cancel_button.setEnabled(True)


    def _display_oobi_panels(self, witnesses: list, controller_alias: str, controller_aid: str):
        """Display OOBI panels for the created witnesses."""
        from locksmith.ui.toolkit.widgets.panels import LocksmithQRPanel
        from locksmith.ui.vault.healthKERI.db.basing import WitnessState

        # Store WitnessState for each witness (matching original flet implementation)
        # WitnessState defaults to authenticated=False, reserved=True
        hk_db = self.app.vault.plugin_state.get("healthkeri", {}).get("db")
        for witness in witnesses:
            witness_state = WitnessState()
            if hk_db:
                hk_db.witStates.pin([witness['eid']], witness_state)
            logger.info(f"Stored WitnessState for witness EID: {witness['eid']}")

        # Clear existing panels
        while self.oobi_section_layout.count():
            item = self.oobi_section_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.oobi_panels.clear()

        # Header
        header_label = QLabel("Your witnesses have been created!")
        header_label.setStyleSheet(f"font-size: 24px; font-weight: bold; color: {colors.TEXT_MENU};")
        self.oobi_section_layout.addWidget(header_label)

        self.oobi_section_layout.addSpacing(10)

        description_label = QLabel(
            "Connect to your witnesses using the OOBI URLs and QR codes below. "
            "Click 'Toggle QR Codes' to show or hide the QR codes."
        )
        description_label.setWordWrap(True)
        description_label.setStyleSheet(f"font-size: 14px; color: {colors.TEXT_SUBTLE};")
        self.oobi_section_layout.addWidget(description_label)

        self.oobi_section_layout.addSpacing(20)

        # Toggle QR button - simple clickable label
        from PySide6.QtWidgets import QPushButton
        toggle_qr_button = QPushButton("( Toggle QR Codes )")
        toggle_qr_button.setFixedWidth(180)
        toggle_qr_button.setCursor(Qt.CursorShape.PointingHandCursor)
        toggle_qr_button.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {colors.BLUE_SELECTION};
                border: none;
                font-size: 14px;
                text-align: left;
                padding: 4px;
            }}
            QPushButton:hover {{
                background-color: {colors.BLUE_SELECTION_BG};
                border-radius: 4px;
            }}
        """)
        self.oobi_section_layout.addWidget(toggle_qr_button)

        self.oobi_section_layout.addSpacing(20)

        # Create panels in rows of 3
        PANELS_PER_ROW = 3
        for row_start in range(0, len(witnesses), PANELS_PER_ROW):
            row_witnesses = witnesses[row_start:row_start + PANELS_PER_ROW]
            panels_row = QHBoxLayout()
            panels_row.setSpacing(16)

            for idx, witness in enumerate(row_witnesses, start=row_start):
                panel = LocksmithQRPanel(
                    number=str(idx + 1),
                    witness_name=witness['name'],
                    witness_eid=witness['eid'],
                    controller_alias=controller_alias,
                    controller_aid=controller_aid,
                    url=witness['oobi'],
                    qr_visible=False  # Hidden initially for OOBI panels
                )
                panels_row.addWidget(panel)
                self.oobi_panels.append(panel)

            panels_row.addStretch()
            self.oobi_section_layout.addLayout(panels_row)

            # Add spacing between rows (but not after the last row)
            if row_start + PANELS_PER_ROW < len(witnesses):
                self.oobi_section_layout.addSpacing(16)

        # Add "Introduce All" and "Done" buttons (centered)
        self.oobi_section_layout.addSpacing(30)

        # Create horizontal layout for centered buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        done_button = LocksmithInvertedButton("Done")
        done_button.setFixedWidth(150)
        done_button.clicked.connect(self._on_done_clicked)
        button_layout.addWidget(done_button)

        button_layout.addSpacing(10)

        introduce_button = LocksmithButton("Introduce All")
        introduce_button.setFixedWidth(150)
        button_layout.addWidget(introduce_button)

        button_layout.addStretch()
        self.oobi_section_layout.addLayout(button_layout)

        # OTP panels section (hidden initially)
        self.otp_section = QWidget()
        self.otp_section.hide()
        self.otp_section_layout = QVBoxLayout(self.otp_section)
        self.otp_section_layout.setContentsMargins(0, 0, 0, 0)
        self.otp_section_layout.setSpacing(20)
        self.oobi_section_layout.addWidget(self.otp_section)

        # Store reference to introduce button
        self.introduce_button = introduce_button
        self.done_button = done_button

        # Show the section
        self.oobi_section.show()

        # Scroll to bottom after rendering
        self._scroll_to_bottom()

    def _scroll_to_bottom(self):
        """Scroll the scroll area to the bottom smoothly."""
        # Use a timer to ensure the layout has been updated before scrolling
        QTimer.singleShot(100, lambda: self.scroll_area.verticalScrollBar().setValue(
            self.scroll_area.verticalScrollBar().maximum()
        ))

    def _add_rotate_section(self):
        """Add the rotate button section with explanatory text."""
        self.otp_section_layout.addSpacing(30)

        # Rotate section label
        rotate_label = QLabel("Rotate to use new witnesses")
        rotate_label.setStyleSheet(f"font-size: 16px; font-weight: 500; color: {colors.TEXT_MENU};")
        self.otp_section_layout.addWidget(rotate_label)

        self.otp_section_layout.addSpacing(0)

        # Create bordered frame container
        rotate_frame = QFrame()
        rotate_frame.setStyleSheet(f"""
            QFrame {{
                border: 1px solid {colors.BORDER};
                border-radius: 4px;
                background-color: {colors.BACKGROUND_CONTENT};
            }}
        """)

        rotate_frame_layout = QHBoxLayout(rotate_frame)
        rotate_frame_layout.setContentsMargins(30, 30, 30, 30)
        rotate_frame_layout.setSpacing(18)

        # Rotate button
        rotate_button = LocksmithButton("Rotate")
        rotate_button.setFixedWidth(120)
        rotate_button.clicked.connect(self._on_rotate_clicked)
        rotate_frame_layout.addWidget(rotate_button, alignment=Qt.AlignmentFlag.AlignTop)

        # Explanatory text column
        text_column = QVBoxLayout()
        text_column.setSpacing(5)

        header_text = QLabel("Would you like to start using your new witnesses immediately?")
        header_text.setWordWrap(True)
        header_text.setStyleSheet(f"font-size: 16px; font-weight: 500; color: {colors.TEXT_MENU}; border: None")
        text_column.addWidget(header_text)

        witness_count = len(self.created_witnesses)
        explanation_text = QLabel(
            f"You have created {witness_count} witness{'es' if witness_count != 1 else ''} and added a 2FA one-time passcode for "
            f"them. If you would like to start using your witnesses immediately, click \"Rotate\" and "
            f"we will perform a key rotation of your identifier and add your witnesses."
        )
        explanation_text.setWordWrap(True)
        explanation_text.setStyleSheet(f"font-size: 14px; color: {colors.TEXT_SUBTLE}; border: None")
        text_column.addWidget(explanation_text)

        rotate_frame_layout.addLayout(text_column, stretch=1)

        self.otp_section_layout.addWidget(rotate_frame)

        # Add centered Done button
        self.otp_section_layout.addSpacing(30)

        done_button_layout = QHBoxLayout()
        done_button_layout.addStretch()

        done_button = LocksmithInvertedButton("Done")
        done_button.setFixedWidth(100)
        done_button.clicked.connect(self._on_done_clicked)
        done_button_layout.addWidget(done_button)

        done_button_layout.addStretch()
        self.otp_section_layout.addLayout(done_button_layout)

    def _on_done_clicked(self):
        """Handle Done button click - navigate back to witness list."""
        logger.info("Done button clicked - returning to Identifier list")
        # If witnesses were created, emit witness_created signal to trigger list refresh
        # Otherwise emit cancelled signal
        if self.created_witnesses:
            # Emit with the list of created witnesses
            self.witness_created.emit()
        else:
            self.cancelled.emit()

    def _on_rotate_clicked(self):
        """Handle Rotate button click - navigate to identifier rotation with pre-populated witnesses."""
        logger.info("Rotate button clicked - navigating to identifier rotation")

        # Get the selected identifier info

    def _disable_form_controls(self):
        """Disable region counter, hostname fields, and authentication radio controls after witness creation."""
        # Disable all region selector counters and hostname fields
        # Disable authentication radio panels
        self._threshold_edit.setEnabled(False)

    def hideEvent(self, event):
        """Stop polling when page is hidden."""
        super().hideEvent(event)
        self.reset()

    def reset(self):
        """
        Reset the form to a completely blank, fresh instance.

        Clears all form data, resets counters, re-enables controls, hides panels,
        and scrolls back to the top.
        """
        logger.info("Resetting witness create page to initial state")



        # Re-enable authentication radio panels
        self._threshold_edit.setEnabled(True)


        # Reset create and cancel buttons
        self.add_witnesses_button.setEnabled(True)
        self.add_witnesses_button.setText("Add Witnesses")
        self.add_witnesses_button.setFixedWidth(175)
        self.add_witnesses_button.show()

        self.cancel_button.setText("Cancel")
        self.cancel_button.show()

        # Hide and clear OOBI section
        if self.oobi_section:
            self.oobi_section.hide()
            # Clear all widgets from OOBI section layout
            while self.oobi_section_layout.count():
                item = self.oobi_section_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
                elif item.layout():
                    # Clear nested layouts
                    while item.layout().count():
                        nested_item = item.layout().takeAt(0)
                        if nested_item.widget():
                            nested_item.widget().deleteLater()

        # Clear OTP section if it exists
        try:
            if self.otp_section:
                self.otp_section.hide()
                while self.otp_section_layout.count():
                    item = self.otp_section_layout.takeAt(0)
                    if item.widget():
                        item.widget().deleteLater()
        except Exception as e:
            logger.exception(f"Error clearing OTP section: {e}")

        # Clear all stored data
        self.created_witnesses = []
        self.oobi_panels = []
        self.otp_panels = []
        self.introduce_button = None
        self.done_button = None

        # Scroll back to top
        QTimer.singleShot(100, lambda: self.scroll_area.verticalScrollBar().setValue(0))

        logger.info("Witness create page reset complete")
