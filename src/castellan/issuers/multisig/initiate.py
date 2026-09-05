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

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

import qasync
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
)

from locksmith.ui import colors
from locksmith.ui.toolkit.widgets.buttons import (
    LocksmithButton, LocksmithInvertedButton,
)
from locksmith.ui.toolkit.widgets.dialogs import LocksmithResourceDeletionDialog
from locksmith.ui.toolkit.widgets.fields import (
    FloatingLabelComboBox, FloatingLabelLineEdit, LocksmithLineEdit,
)
from locksmith.ui.toolkit.widgets.page import LocksmithFormPage
from locksmith.ui.toolkit.widgets.extensible import ExtensibleSelectorWidget
from locksmith.ui.styles import get_monospace_font_family

from ...core import remoting
from ...db.basing import MultisigIdentityState, MultisigInitState
from .doers import GroupMultisigInceptDoer, CreateRegistryDoer
from .poller import UploadedIdentifierPoller

if TYPE_CHECKING:
    from locksmith.core.apping import LocksmithApplication
    from locksmith.ui.vault.page import VaultPage

from keri import help
from keri.vdr import credentialing as vdr_credentialing

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

    def __init__(
        self,
        app: "LocksmithApplication",
        on_complete: Callable[[str], None] | None = None,
        parent: "VaultPage | None" = None,
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
        self._reset_button = LocksmithInvertedButton("Reset")
        self._reset_button.setFixedWidth(100)
        self._reset_button.clicked.connect(self._on_reset_clicked)
        self._parent = parent
        self.app = app
        self.on_complete = on_complete
        self._poller: UploadedIdentifierPoller | None = None
        self._castellan_identifiers: list[dict] = []
        self._current_group_alias: str | None = None

        self._setup_content()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_content(self):
        layout = self.content_layout

        desc = QLabel(
            "Set up a Castellan multisig identifier. You will upload your identifier to the "
            "shared Castellan server, wait for peers to join, create a group multisig "
            "identifier with those peers, and create a self-backed credential registry."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"font-size: 15px; color: {colors.TEXT_SUBTLE};")
        layout.addWidget(desc)
        layout.addSpacing(40)

        # Section 1
        self._build_section1(layout)

        # Section 2 (hidden initially)
        self._section2 = QWidget()
        self._section2.hide()
        s2_layout = QVBoxLayout(self._section2)
        s2_layout.setContentsMargins(0, 0, 0, 0)
        s2_layout.setSpacing(0)
        self._build_section2(s2_layout)
        layout.addWidget(self._section2)

        # Section 3 (hidden initially)
        self._section3 = QWidget()
        self._section3.hide()
        s3_layout = QVBoxLayout(self._section3)
        s3_layout.setContentsMargins(0, 0, 0, 0)
        s3_layout.setSpacing(0)
        self._build_section3(s3_layout)
        layout.addWidget(self._section3)

        # Section 4 (hidden initially)
        self._section4 = QWidget()
        self._section4.hide()
        s4_layout = QVBoxLayout(self._section4)
        s4_layout.setContentsMargins(0, 0, 0, 0)
        s4_layout.setSpacing(0)
        self._build_section4(s4_layout)
        layout.addWidget(self._section4)

        # Footer — home for the Reset button whenever Create Group Identifier
        # isn't on screen to sit next to (still visible once past section 1).
        self._reset_footer = QWidget()
        self._reset_footer.hide()
        reset_footer_layout = QHBoxLayout(self._reset_footer)
        reset_footer_layout.setContentsMargins(0, 0, 0, 0)
        self._reset_footer_layout = reset_footer_layout
        reset_footer_layout.addStretch()
        reset_footer_layout.addWidget(self._reset_button)
        reset_footer_layout.addStretch()
        layout.addWidget(self._reset_footer)

        layout.addStretch()

    # -- Section 1: Choose and Upload Identifier -------------------------

    def _build_section1(self, layout: QVBoxLayout):
        self._s1_header_lbl = QLabel("Choose Your Identifier")
        self._s1_header_lbl.setStyleSheet(
            f"font-weight: bold; font-size: 20px; color: {colors.TEXT_MENU};"
        )
        layout.addWidget(self._s1_header_lbl)
        layout.addSpacing(6)
        self._s1_subtext_lbl = QLabel(
            "Select the single (non-group) identifier that will represent you "
            "in the Castellan network. This identifier will be uploaded to "
            "castellan so peers can discover you."
        )
        self._s1_subtext_lbl.setWordWrap(True)
        self._s1_subtext_lbl.setStyleSheet(
            f"font-size: 13px; color: {colors.TEXT_SUBTLE}; font-weight: 200;"
        )
        layout.addWidget(self._s1_subtext_lbl)
        layout.addSpacing(6)

        _s1_body = QWidget()
        _s1_body_layout = QVBoxLayout(_s1_body)
        _s1_body_layout.setContentsMargins(10, 0, 0, 0)
        _s1_body_layout.setSpacing(0)

        _s1_body_layout.addSpacing(20)

        self._s1_input = QWidget()
        s1_in = QHBoxLayout(self._s1_input)
        s1_in.setContentsMargins(0, 0, 0, 0)
        self._id_dropdown = FloatingLabelComboBox("Your Identifier")
        self._id_dropdown.setFixedWidth(380)
        self._id_dropdown.currentIndexChanged.connect(self._on_identifier_changed)
        s1_in.addWidget(self._id_dropdown)
        s1_in.addSpacing(12)
        self._upload_button = LocksmithButton("Upload to Castellan")
        self._upload_button.setFixedWidth(200)
        self._upload_button.clicked.connect(self._on_upload_clicked)
        s1_in.addWidget(self._upload_button)
        s1_in.addStretch()
        _s1_body_layout.addWidget(self._s1_input)

        self._id_aid_label = QLabel("")
        self._id_aid_label.setStyleSheet(
            f"font-size: 11px; color: {colors.TEXT_SUBTLE}; font-family: {get_monospace_font_family()};"
        )
        _s1_body_layout.addWidget(self._id_aid_label)

        self._s1_chosen = QWidget()
        s1_ch = QVBoxLayout(self._s1_chosen)
        s1_ch.setContentsMargins(0, 0, 0, 0)
        s1_ch.setSpacing(4)
        self._s1_chosen_name_lbl = QLabel("—")
        self._s1_chosen_name_lbl.setStyleSheet(
            f"font-size: 15px; font-weight: 600; color: {colors.TEXT_MENU};"
        )
        s1_ch.addWidget(self._s1_chosen_name_lbl)
        self._s1_chosen_aid_lbl = QLabel("—")
        self._s1_chosen_aid_lbl.setStyleSheet(
            f"font-size: 11px; color: {colors.TEXT_SUBTLE}; font-family: {get_monospace_font_family()};"
        )
        s1_ch.addWidget(self._s1_chosen_aid_lbl)
        self._s1_chosen.hide()
        _s1_body_layout.addWidget(self._s1_chosen)

        layout.addWidget(_s1_body)
        layout.addSpacing(40)

    # -- Section 2: Wait for Peers --------------------------------------

    def _build_section2(self, layout: QVBoxLayout):
        self._s2_header_lbl = QLabel("Waiting for Peers")
        self._s2_header_lbl.setStyleSheet(
            f"font-weight: bold; font-size: 20px; color: {colors.TEXT_MENU};"
        )
        layout.addWidget(self._s2_header_lbl)
        layout.addSpacing(6)
        self._s2_subtext_lbl = QLabel(
            "Your identifier has been uploaded. Waiting for at least one peer to "
            "join before group identifier creation can begin."
        )
        self._s2_subtext_lbl.setWordWrap(True)
        self._s2_subtext_lbl.setStyleSheet(
            f"font-size: 13px; color: {colors.TEXT_SUBTLE}; font-weight: 200;"
        )
        layout.addWidget(self._s2_subtext_lbl)
        layout.addSpacing(6)

        _s2_body = QWidget()
        _s2_body_layout = QVBoxLayout(_s2_body)
        _s2_body_layout.setContentsMargins(10, 0, 0, 0)
        _s2_body_layout.setSpacing(0)

        _s2_body_layout.addSpacing(12)

        self._peer_count_label = QLabel("0 peer(s) have joined castellan")
        self._peer_count_label.setStyleSheet(
            f"font-size: 14px; color: {colors.TEXT_SUBTLE};"
        )
        _s2_body_layout.addWidget(self._peer_count_label)

        layout.addWidget(_s2_body)
        layout.addSpacing(40)

    # -- Section 3: Create Group Identifier -----------------------------

    def _build_section3(self, layout: QVBoxLayout):
        self._s3_header_lbl = QLabel("Create Group Identifier or Wait to Join a Group")
        self._s3_header_lbl.setStyleSheet(
            f"font-weight: bold; font-size: 20px; color: {colors.TEXT_MENU};"
        )
        layout.addWidget(self._s3_header_lbl)
        layout.addSpacing(6)
        self._s3_subtext_lbl = QLabel(
            "Select peers to include in your group multisig identifier and create it, "
            "or wait here — if a peer invites you to join their group you will receive "
            "a notification to accept.",
        )
        self._s3_subtext_lbl.setWordWrap(True)
        self._s3_subtext_lbl.setStyleSheet(
            f"font-size: 13px; color: {colors.TEXT_SUBTLE}; font-weight: 200;"
        )
        layout.addWidget(self._s3_subtext_lbl)
        layout.addSpacing(6)

        _s3_body = QWidget()
        _s3_body_layout = QVBoxLayout(_s3_body)
        _s3_body_layout.setContentsMargins(10, 0, 0, 0)
        _s3_body_layout.setSpacing(0)

        _s3_body_layout.addSpacing(12)

        self._group_alias_field = FloatingLabelLineEdit("Group Identifier Alias")
        self._group_alias_field.setFixedWidth(500)
        _s3_body_layout.addWidget(self._group_alias_field)
        _s3_body_layout.addSpacing(16)

        participants_lbl = QLabel("Group Participants")
        participants_lbl.setStyleSheet("font-weight: 600; font-size: 14px;")
        _s3_body_layout.addWidget(participants_lbl)

        self._participants_container = QWidget()
        self._participants_container_layout = QVBoxLayout(self._participants_container)
        self._participants_container_layout.setContentsMargins(0, 0, 0, 0)
        self._participants_selector: ExtensibleSelectorWidget | None = None
        _s3_body_layout.addWidget(self._participants_container)
        _s3_body_layout.addSpacing(4)

        # Frozen participant list (replaces selector when section 3 is locked)
        self._s3_frozen_participants_widget = QWidget()
        self._s3_frozen_participants_widget.hide()
        self._s3_frozen_participants_layout = QVBoxLayout(self._s3_frozen_participants_widget)
        self._s3_frozen_participants_layout.setContentsMargins(0, 0, 0, 0)
        self._s3_frozen_participants_layout.setSpacing(0)
        _s3_body_layout.addWidget(self._s3_frozen_participants_widget)

        _s3_body_layout.addSpacing(8)

        self._s3_self_widget = QWidget()
        s3_self_vbox = QVBoxLayout(self._s3_self_widget)
        s3_self_vbox.setContentsMargins(8, 0, 0, 0)
        s3_self_vbox.setSpacing(4)
        self._s3_self_name_lbl = QLabel("—")
        self._s3_self_name_lbl.setStyleSheet(
            f"font-size: 15px; font-weight: 600; color: {colors.TEXT_MENU};"
        )
        s3_self_vbox.addWidget(self._s3_self_name_lbl)
        self._s3_self_aid_lbl = QLabel("—")
        self._s3_self_aid_lbl.setStyleSheet(
            f"font-size: 11px; color: {colors.TEXT_SUBTLE}; font-family: {get_monospace_font_family()};"
        )
        s3_self_vbox.addWidget(self._s3_self_aid_lbl)
        _s3_body_layout.addWidget(self._s3_self_widget)
        _s3_body_layout.addSpacing(16)

        thresholds_lbl = QLabel("Thresholds")
        thresholds_lbl.setStyleSheet("font-weight: 600; font-size: 14px;")
        _s3_body_layout.addWidget(thresholds_lbl)

        thresh_row = QHBoxLayout()
        self._signing_threshold = FloatingLabelLineEdit("Signing Threshold")
        self._signing_threshold.setText("1")
        self._signing_threshold.setFixedWidth(240)
        thresh_row.addWidget(self._signing_threshold)
        thresh_row.addSpacing(8)
        self._rotation_threshold = FloatingLabelLineEdit("Rotation Threshold")
        self._rotation_threshold.setText("1")
        self._rotation_threshold.setFixedWidth(240)
        thresh_row.addWidget(self._rotation_threshold)
        thresh_row.addStretch()
        _s3_body_layout.addLayout(thresh_row)
        _s3_body_layout.addSpacing(20)

        toad_row = QHBoxLayout()
        toad_lbl = QLabel("Threshold of Acceptable Duplicity: ")
        toad_lbl.setStyleSheet("font-size: 14px;")
        toad_row.addWidget(toad_lbl)
        self._toad_field = LocksmithLineEdit()
        self._toad_field.setText("0")
        self._toad_field.setFixedWidth(50)
        self._toad_field.setAlignment(Qt.AlignmentFlag.AlignCenter)
        toad_row.addWidget(self._toad_field)
        toad_row.addStretch()
        _s3_body_layout.addLayout(toad_row)
        _s3_body_layout.addSpacing(20)

        btn_row = QHBoxLayout()
        self._s3_btn_row = btn_row
        btn_row.setSpacing(12)
        btn_row.addStretch()
        self._create_group_button = LocksmithButton("Create Group Identifier")
        self._create_group_button.setFixedWidth(220)
        self._create_group_button.clicked.connect(self._on_create_group_clicked)
        btn_row.addWidget(self._create_group_button)
        btn_row.addStretch()
        _s3_body_layout.addLayout(btn_row)

        layout.addWidget(_s3_body)
        layout.addSpacing(40)

    # -- Section 4: Progress --------------------------------------------
    def _build_section4(self, layout: QVBoxLayout):
        self._s4_header_lbl = QLabel("Initializing…")
        self._s4_header_lbl.setStyleSheet(f"font-weight: bold; font-size: 20px; color: {colors.TEXT_MENU};")
        layout.addWidget(self._s4_header_lbl)
        layout.addSpacing(6)
        self._s4_subtext_lbl = QLabel("Coordinating signatures across participants.")
        self._s4_subtext_lbl.setWordWrap(True)
        self._s4_subtext_lbl.setStyleSheet(f"font-size: 13px; color: {colors.TEXT_SUBTLE}; font-weight: 200;")
        layout.addWidget(self._s4_subtext_lbl)
        layout.addSpacing(6)

        _s4_body = QWidget()
        _s4_body_layout = QVBoxLayout(_s4_body)
        _s4_body_layout.setContentsMargins(10, 0, 0, 0)
        _s4_body_layout.setSpacing(0)

        _s4_body_layout.addSpacing(12)

        self._round1_frame, self._round1_participants_layout = self._make_progress_frame(
            "Step 1 of 2 — Group Identifier"
        )
        _s4_body_layout.addWidget(self._round1_frame)
        _s4_body_layout.addSpacing(12)

        self._round2_frame, self._round2_participants_layout = self._make_progress_frame(
            "Step 2 of 2 — Registry"
        )
        _s4_body_layout.addWidget(self._round2_frame)

        layout.addWidget(_s4_body)
        layout.addSpacing(40)

    def _make_progress_frame(self, title: str) -> tuple["QFrame", "QVBoxLayout"]:
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
        if self.app.vault:
            self.on_show()

    def on_show(self):
        """Called when the page becomes visible. Resumes any in-progress attempt."""
        self.clear_error()
        self.clear_success()

        # Reset all progressive sections — required when switching vaults so
        # that sections revealed for a previous vault are hidden for the new one.
        self._section2.hide()
        self._section3.hide()
        self._section4.hide()

        self._s1_header_lbl.setText("Choose Your Identifier")
        self._s1_subtext_lbl.setText(
            "Select the single (non-group) identifier that will represent you "
            "in the Castellan network. This identifier will be uploaded to "
            "castellan so peers can discover you."
        )
        self._s1_input.show()
        self._id_aid_label.show()
        self._s1_chosen.hide()

        # Unlock section 3 by default — required so a group flow that fully
        # completed since the last on_show() doesn't leave stale frozen
        # fields behind. Re-locked below if an in-progress attempt is found.
        self._unlock_section3()

        if self._poller is not None:
            try:
                self._poller.signals.identifiers_changed.disconnect(self._on_identifiers_changed)
            except Exception:
                pass
            self._poller = None
        self._castellan_identifiers = []
        self._round1_participant_labels: dict[str, "QLabel"] = {}
        self._round2_participant_labels: dict[str, "QLabel"] = {}

        self._load_identifier_dropdown()

        identity = self._get_identity_state()

        if identity.identifier_uploaded:
            hab = self.app.vault.hby.habByName(identity.chosen_identifier_alias) if identity.chosen_identifier_alias else None
            if hab:
                self._apply_s1_uploaded(identity.chosen_identifier_alias, hab.pre)
            self._section2.show()
            self._start_poller()

            self._current_group_alias = self._find_incomplete_group_alias()

            if self._current_group_alias:
                state = self._get_group_state(self._current_group_alias)
                self._section3.show()
                self._populate_section3(state, identity)

                _show_s4 = state.init_step >= 4 or (state.init_step == 3 and state.section4_started)

                if _show_s4:
                    smids = self._get_group_smids(self._current_group_alias)
                    if smids:
                        if state.init_step == 3 and state.section4_started:
                            from keri.core import coring as _kc
                            _ghab = self.app.vault.hby.habByName(self._current_group_alias)
                            if _ghab is not None:
                                _pfx = _kc.Prefixer(qb64=_ghab.pre)
                                _seq = _kc.Seqner(sn=0)
                                if self.app.vault.counselor.complete(_pfx, _seq):
                                    state.init_step = 4
                                    if not state.group_signed_aids:
                                        state.group_signed_aids = list(smids)
                                    self._save_group_state(state)

                        self._lock_section3(state, smids, identity)
                        self._section4.show()

                        self._build_signing_rows(
                            self._round1_participants_layout,
                            self._round1_participant_labels,
                            smids,
                            state.group_signed_aids,
                        )
                        self._build_signing_rows(
                            self._round2_participants_layout,
                            self._round2_participant_labels,
                            smids,
                            state.registry_signed_aids,
                        )

                        if state.init_step >= 4 and not state.init_complete:
                            registry_name = f"{self._current_group_alias}-registry"
                            registry = self.app.vault.rgy.registryByName(registry_name)
                            if registry is not None:
                                _reg = vdr_credentialing.Registrar(
                                    hby=self.app.vault.hby,
                                    rgy=self.app.vault.rgy,
                                    counselor=self.app.vault.counselor,
                                )
                                if _reg.complete(pre=registry.regk, sn=0):
                                    self._on_init_complete(registry.regk)
                                elif state.is_proposer:
                                    self._launch_create_registry_doer(self._current_group_alias)
                            elif state.is_proposer:
                                self._launch_create_registry_doer(self._current_group_alias)

        # Reconnect doer event listener for the current vault.
        if self.app.vault and hasattr(self.app.vault, "signals"):
            try:
                self.app.vault.signals.doer_event.disconnect(self._on_doer_event)
            except Exception:
                pass
            self.app.vault.signals.doer_event.connect(self._on_doer_event)

        self._sync_reset_button_placement()

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def _place_reset_next_to_create(self):
        self._reset_footer_layout.removeWidget(self._reset_button)
        if self._s3_btn_row.indexOf(self._reset_button) == -1:
            create_idx = self._s3_btn_row.indexOf(self._create_group_button)
            self._s3_btn_row.insertWidget(create_idx, self._reset_button)
        self._reset_footer.hide()
        self._reset_button.show()

    def _place_reset_in_footer(self):
        self._s3_btn_row.removeWidget(self._reset_button)
        if self._reset_footer_layout.indexOf(self._reset_button) == -1:
            self._reset_footer_layout.addWidget(self._reset_button)
        self._reset_footer.show()
        self._reset_button.show()

    def _hide_reset_button(self):
        self._s3_btn_row.removeWidget(self._reset_button)
        self._reset_footer_layout.removeWidget(self._reset_button)
        self._reset_button.hide()
        self._reset_footer.hide()

    def _sync_reset_button_placement(self):
        """
        Reset only makes sense once section 1 is behind us. From then on it
        sits next to Create Group Identifier while that button is on screen,
        otherwise it falls back to the page footer (section 2 only, or
        section 3 locked into section 4's progress view).
        """
        identity = self._get_identity_state()
        if not identity.identifier_uploaded:
            self._hide_reset_button()
            return
        if self._section3.isVisible() and self._create_group_button.isVisible():
            self._place_reset_next_to_create()
        else:
            self._place_reset_in_footer()

    def _on_reset_clicked(self):
        resource_name = self._current_group_alias or "Multi-Signature"
        dialog = LocksmithResourceDeletionDialog(
            parent=self._parent or self,
            resource_type="setup",
            resource_name=resource_name,
            action_verb="Reset",
        )
        dialog.delete_button.clicked.disconnect(dialog.accept)
        dialog.delete_button.clicked.connect(lambda: self._confirm_reset(dialog))
        dialog.open()

    def _confirm_reset(self, dialog: LocksmithResourceDeletionDialog):
        dialog.accept()
        self._do_reset()

    @qasync.asyncSlot()
    async def _do_reset(self):
        """Clear all persisted progress for this page and redraw at section 1."""
        self._reset_button.setEnabled(False)
        self._reset_button.setText("Resetting…")
        self.clear_error()
        self.clear_success()

        if self._poller is not None:
            try:
                self.app.vault.remove([self._poller])
            except Exception:
                pass
            self._poller = None

        db = self._get_db()
        if db is not None:
            db.castellan_multisig_identity.trim()
            db.castellan_multisig_init.trim()

        self._current_group_alias = None
        self._castellan_identifiers = []

        self._reset_button.setText("Reset")
        self._reset_button.setEnabled(True)

        self.on_show()
        self.show_success("Multisig setup has been reset.")

    # ------------------------------------------------------------------
    # Section 1
    # ------------------------------------------------------------------

    def _load_identifier_dropdown(self):
        """Populate dropdown with local non-group habs."""
        if not self.app.vault:
            return
        from keri.app.habbing import GroupHab
        self._id_dropdown.clear()
        self._id_alias_map: dict[str, str] = {}
        for aid, hab in self.app.vault.hby.habs.items():
            if isinstance(hab, GroupHab):
                continue
            display = f"{hab.name} - {aid}"
            self._id_alias_map[display] = aid
            self._id_dropdown.addItem(display)
        self._id_dropdown.setCurrentIndex(-1)

    def _on_identifier_changed(self, index: int):
        if index < 0:
            self._id_aid_label.setText("")
            return
        display = self._id_dropdown.currentText()
        aid = self._id_alias_map.get(display)
        hab = self.app.vault.hby.habs.get(aid) if aid else None
        if hab:
            self._id_aid_label.setText(f"{hab.name} - {aid}")

    def _apply_s1_uploaded(self, alias: str, aid: str):
        """Swap section 1 from selection mode to confirmation mode."""
        self._s1_header_lbl.setText("Your Identifier Has Been Chosen!")
        self._s1_subtext_lbl.setText(
            "This identifier has been uploaded to castellan and will represent "
            "you in the shared network."
        )
        self._s1_chosen_name_lbl.setText(alias)
        self._s1_chosen_aid_lbl.setText(aid)
        self._s1_input.hide()
        self._id_aid_label.hide()
        self._s1_chosen.show()

    @qasync.asyncSlot()
    async def _on_upload_clicked(self):
        identity = self._get_identity_state()
        display = self._id_dropdown.currentText()
        if not display:
            self.show_error("Please select an identifier.")
            return

        aid = self._id_alias_map.get(display)
        hab = self.app.vault.hby.habs.get(aid) if aid else None
        if hab is None:
            self.show_error("Selected identifier not found.")
            return

        oobi = ""
        try:
            oobi_result = hab.makeOwnEndRole()
            if oobi_result:
                oobi = oobi_result.decode() if isinstance(oobi_result, bytes) else str(oobi_result)
        except Exception:
            pass

        try:
            kel_bytes = b"".join(self.app.vault.hby.db.clonePreIter(pre=hab.pre, fn=0))
        except Exception as e:
            self.show_error(f"Failed to serialize KEL for upload: {e}")
            return

        if not kel_bytes:
            self.show_error("No KEL events found for selected identifier — cannot upload.")
            return

        self._upload_button.setEnabled(False)
        self._upload_button.setText("Uploading…")
        self.clear_error()

        result = await remoting.upload_identifier(self.app, aid=hab.pre, alias=hab.name, kel_bytes=kel_bytes, oobi=oobi)

        self._upload_button.setEnabled(True)
        self._upload_button.setText("Upload to Castellan")

        if result.get("conflict"):
            self.show_error(
                f"The alias '{hab.name}' is already uploaded to castellan. "
                "Rename your local identifier if this is your first upload."
            )
            return

        if not result.get("success"):
            self.show_error(f"Upload failed: {result.get('error', 'unknown error')}")
            return

        self.clear_error()
        identity.chosen_identifier_alias = hab.name
        identity.chosen_identifier_aid = hab.pre
        identity.identifier_uploaded = True
        self._save_identity_state(identity)

        self._apply_s1_uploaded(hab.name, hab.pre)
        self._section2.show()
        self._scroll_to_bottom()
        self._start_poller()
        self._sync_reset_button_placement()

    # ------------------------------------------------------------------
    # Section 2
    # ------------------------------------------------------------------

    def _start_poller(self):
        if self._poller is not None:
            return
        self._poller = UploadedIdentifierPoller(self.app)
        self._poller.signals.identifiers_changed.connect(self._on_identifiers_changed)
        self.app.vault.extend([self._poller])
        self._poller._poll()

    def _on_identifiers_changed(self, identifiers: list[dict]):
        self._castellan_identifiers = identifiers
        identity = self._get_identity_state()
        chosen_hab = self.app.vault.hby.habByName(identity.chosen_identifier_alias) if identity.chosen_identifier_alias else None
        chosen_aid = chosen_hab.pre if chosen_hab else ""
        peers = [i for i in identifiers if i["aid"] != chosen_aid]

        count = len(peers)
        self._peer_count_label.setText(f"{count} peer(s) have joined castellan")

        if count >= 1:
            self._s2_header_lbl.setText("Castellan Peers are Available!")
            self._s2_subtext_lbl.setText(
                "Multiple Castellan peers are available to form a group identifier."
            )
            if not self._section3.isVisible():
                self._section3.show()
                self._populate_section3(
                    self._get_group_state(self._current_group_alias) if self._current_group_alias else None,
                    identity,
                )
                self._scroll_to_bottom()
            else:
                self._populate_section3(
                    self._get_group_state(self._current_group_alias) if self._current_group_alias else None,
                    identity,
                )
        else:
            if self._section3.isVisible():
                self._populate_section3(
                    self._get_group_state(self._current_group_alias) if self._current_group_alias else None,
                    identity,
                )

        self._sync_reset_button_placement()

    # ------------------------------------------------------------------
    # Section 3
    # ------------------------------------------------------------------

    def _populate_section3(self, state: MultisigInitState | None, identity: MultisigIdentityState):
        """Populate participant selector from current castellan identifiers."""
        hab = self.app.vault.hby.habByName(identity.chosen_identifier_alias) if identity.chosen_identifier_alias else None

        chosen_aid = hab.pre if hab else ""
        if hab:
            self._s3_self_name_lbl.setText(identity.chosen_identifier_alias or "—")
            self._s3_self_aid_lbl.setText(chosen_aid or "—")

        # Skip rebuilding selector if a group flow is already locked
        if state is not None and (state.section4_started or state.init_step >= 4):
            return

        items = [
            (i["alias"], {"aid": i["aid"], "alias": i["alias"], "oobi": i.get("oobi", "")})
            for i in self._castellan_identifiers
            if i["aid"] != chosen_aid
        ]

        if self._participants_selector is not None:
            self._participants_container_layout.removeWidget(self._participants_selector)
            self._participants_selector.deleteLater()
            self._participants_selector = None

        self._participants_selector = ExtensibleSelectorWidget(
            dropdown_label="Select Participant",
            selector_dropdown_items=items,
            parent=self,
            max_scrollable_height=200,
        )
        self._participants_selector.setFixedWidth(500)
        self._participants_container_layout.addWidget(self._participants_selector)

    def _on_create_group_clicked(self):
        identity = self._get_identity_state()
        alias = self._group_alias_field.text().strip()
        if not alias:
            self.show_error("Please enter a group identifier alias.")
            return

        mhab = self.app.vault.hby.habByName(identity.chosen_identifier_alias) if identity.chosen_identifier_alias else None
        if mhab is None:
            self.show_error("Your signing identifier was not found in the vault.")
            return

        if self._participants_selector is None:
            self.show_error("Participants selector not initialized.")
            return

        selected = self._participants_selector.get_selected_items()
        if not selected:
            self.show_error("Select at least one other participant.")
            return

        smids = [mhab.pre]
        for _, data in selected:
            aid = data.get("aid")
            if aid and aid not in smids:
                smids.append(aid)

        isith = self._signing_threshold.text().strip() or "1"
        nsith = self._rotation_threshold.text().strip() or "1"
        toad = int(self._toad_field.text().strip() or "0")

        self._current_group_alias = alias
        state = MultisigInitState(group_alias=alias, is_proposer=True)
        self._save_group_state(state)

        self._create_group_button.setEnabled(False)
        self._create_group_button.setText("Creating…")
        self.clear_error()

        doer = GroupMultisigInceptDoer(
            app=self.app,
            alias=alias,
            mhab=mhab,
            smids=smids,
            isith=isith,
            nsith=nsith,
            toad=toad,
            signal_bridge=self.app.vault.signals,
        )
        self.app.vault.extend([doer])

    # ------------------------------------------------------------------
    # Section 4
    # ------------------------------------------------------------------

    def _lock_section3(self, state: "MultisigInitState", smids: list[str], identity: MultisigIdentityState) -> None:
        """Freeze all section 3 inputs and display frozen participant list."""
        if state.is_proposer:
            self._s3_header_lbl.setText("Group Identifier Created")
            self._s3_subtext_lbl.setText(
                "The fields below reflect the parameters of the created group identifier."
            )
        else:
            self._s3_header_lbl.setText("Group Identifier Joined")
            self._s3_subtext_lbl.setText(
                "The fields below reflect the parameters of the group identifier you joined."
            )

        if not state.is_proposer:
            self._group_alias_field.setText(state.group_alias)
            self._signing_threshold.setText(state.group_isith or "1")
            self._rotation_threshold.setText(state.group_nsith or "1")
            self._toad_field.setText(state.group_toad or "0")
        else:
            self._group_alias_field.setText(state.group_alias)

        self._group_alias_field.setReadOnly(True)
        self._signing_threshold.setReadOnly(True)
        self._rotation_threshold.setReadOnly(True)
        self._toad_field.setReadOnly(True)
        self._create_group_button.hide()

        self._participants_container.hide()
        while self._s3_frozen_participants_layout.count():
            item = self._s3_frozen_participants_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        own_aid = identity.chosen_identifier_aid
        others = [aid for aid in smids if aid != own_aid]

        if len(others) > 4:
            from PySide6.QtWidgets import QScrollArea
            scroll = QScrollArea()
            scroll.setMaximumHeight(260)
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            container = QWidget()
            c_layout = QVBoxLayout(container)
            c_layout.setContentsMargins(0, 0, 0, 0)
            c_layout.setSpacing(0)
            for aid in others:
                c_layout.addWidget(self._make_participant_label_row(aid))
            scroll.setWidget(container)
            self._s3_frozen_participants_layout.addWidget(scroll)
        else:
            for aid in others:
                self._s3_frozen_participants_layout.addWidget(self._make_participant_label_row(aid))

        self._s3_frozen_participants_widget.show()

    def _unlock_section3(self) -> None:
        """
        Restore section 3 to its pristine editable state (inverse of
        _lock_section3). Called from on_show() whenever there is no
        in-progress group attempt, so a fully-completed (or never-started)
        flow doesn't leave stale frozen fields behind for the next attempt.
        """
        self._s3_header_lbl.setText("Create Group Identifier or Wait to Join a Group")
        self._s3_subtext_lbl.setText(
            "Select peers to include in your group multisig identifier and create it, "
            "or wait here — if a peer invites you to join their group you will receive "
            "a notification to accept.",
        )

        self._group_alias_field.clear()
        self._group_alias_field.setReadOnly(False)
        self._signing_threshold.setText("1")
        self._signing_threshold.setReadOnly(False)
        self._rotation_threshold.setText("1")
        self._rotation_threshold.setReadOnly(False)
        self._toad_field.setText("0")
        self._toad_field.setReadOnly(False)

        self._create_group_button.setText("Create Group Identifier")
        self._create_group_button.setEnabled(True)
        self._create_group_button.show()

        self._s3_frozen_participants_widget.hide()
        while self._s3_frozen_participants_layout.count():
            item = self._s3_frozen_participants_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._participants_container.show()

    def _reveal_section4_waiting(
            self, group_alias: str, smids: list[str], is_proposer: bool, data: dict
    ) -> None:
        """Show section 4 before group inception is complete. Lock section 3."""
        identity = self._get_identity_state()
        state = self._get_group_state(group_alias)
        state.is_proposer = is_proposer
        state.section4_started = True
        state.group_isith = data.get("isith", "1")
        state.group_nsith = data.get("nsith", "1")
        state.group_toad = data.get("toad", "0")

        if is_proposer:
            own_aid = identity.chosen_identifier_aid
            if own_aid and own_aid not in state.group_signed_aids:
                state.group_signed_aids.append(own_aid)

        self._current_group_alias = group_alias
        self._save_group_state(state)
        self._lock_section3(state, smids, identity)

        self._section4.show()
        self._scroll_to_bottom()

        self._build_signing_rows(
            self._round1_participants_layout,
            self._round1_participant_labels,
            smids,
            state.group_signed_aids,
        )
        self._build_signing_rows(
            self._round2_participants_layout,
            self._round2_participant_labels,
            smids,
            [],
        )

        self._sync_reset_button_placement()

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

    def _on_doer_event(self, doer_name: str, event_type: str, data: dict):
        # ---- GroupMultisigInceptDoer ----
        if doer_name == "CastellanGroupMultisigInceptDoer":
            if event_type == "group_inception_exn_sent":
                smids = data.get("smids", [])
                alias = data.get("alias", "")
                if smids and alias:
                    self._reveal_section4_waiting(alias, smids, is_proposer=True, data=data)

            elif event_type == "group_participant_signed":
                signer_aid = data.get("signer_aid", "")
                if signer_aid:
                    self._update_signing_row(self._round1_participant_labels, signer_aid, signed=True)

            elif event_type == "group_identifier_created":
                alias = data.get("alias", "") or self._current_group_alias
                if not alias:
                    return
                state = self._get_group_state(alias)
                state.init_step = 4
                identity = self._get_identity_state()
                smids = self._get_group_smids(alias)
                for aid in smids:
                    self._update_signing_row(self._round1_participant_labels, aid, signed=True)
                state.group_signed_aids = list(smids)
                own_aid = identity.chosen_identifier_aid
                if own_aid and own_aid not in state.registry_signed_aids:
                    state.registry_signed_aids.append(own_aid)
                self._save_group_state(state)
                self._update_signing_row(self._round2_participant_labels, own_aid, signed=True)
                self._launch_create_registry_doer(alias)

            elif event_type == "group_inception_failed":
                alias = data.get("alias", "") or self._current_group_alias
                state = self._get_group_state(alias) if alias else None
                if state is None or not state.section4_started:
                    self._create_group_button.setEnabled(True)
                    self._create_group_button.setText("Create Group Identifier")
                    self._create_group_button.show()
                    self._sync_reset_button_placement()
                self.show_error(f"Group creation failed: {data.get('error')}")

        # ---- MultisigJoinDoer ----
        elif doer_name == "CastellanMultisigJoinDoer":
            if event_type == "group_join_waiting":
                smids = data.get("smids", [])
                alias = data.get("alias", "")
                if smids and alias:
                    self._reveal_section4_waiting(alias, smids, is_proposer=False, data=data)

            elif event_type == "group_identifier_joined":
                alias = data.get("alias", "") or self._current_group_alias
                if not alias:
                    return
                state = self._get_group_state(alias)
                state.init_step = 4
                smids = self._get_group_smids(alias)
                for aid in smids:
                    self._update_signing_row(self._round1_participant_labels, aid, signed=True)
                state.group_signed_aids = list(smids)
                self._save_group_state(state)

            elif event_type == "group_join_failed":
                alias = data.get("alias", "") or self._current_group_alias
                state = self._get_group_state(alias) if alias else None
                if state is None or not state.section4_started:
                    self._create_group_button.setEnabled(True)
                    self._create_group_button.setText("Create Group Identifier")
                    self._create_group_button.show()
                    self._sync_reset_button_placement()
                self.show_error(f"Group join failed: {data.get('error')}")

        # ---- CreateRegistryDoer ----
        elif doer_name == "CastellanCreateRegistryDoer":
            alias = self._current_group_alias
            if event_type == "registry_participant_signed":
                signer_aid = data.get("signer_aid", "")
                if signer_aid:
                    self._update_signing_row(self._round2_participant_labels, signer_aid, signed=True)

            elif event_type == "registry_created":
                if alias:
                    smids = self._get_group_smids(alias)
                    for aid in smids:
                        self._update_signing_row(self._round2_participant_labels, aid, signed=True)
                    state = self._get_group_state(alias)
                    state.registry_signed_aids = list(smids)
                    self._save_group_state(state)
                self._on_init_complete(data.get("regk", ""))

            elif event_type == "registry_creation_failed":
                self.show_error(f"Registry creation failed: {data.get('error')}")

        # ---- RegistryAcceptDoer ----
        elif doer_name == "CastellanRegistryAcceptDoer":
            alias = self._current_group_alias
            if event_type == "registry_accept_waiting":
                own_aid = data.get("own_aid", "")
                if own_aid and alias:
                    state = self._get_group_state(alias)
                    if own_aid not in state.registry_signed_aids:
                        state.registry_signed_aids.append(own_aid)
                        self._save_group_state(state)
                    self._update_signing_row(self._round2_participant_labels, own_aid, signed=True)

            elif event_type == "registry_accepted":
                if alias:
                    smids = self._get_group_smids(alias)
                    for aid in smids:
                        self._update_signing_row(self._round2_participant_labels, aid, signed=True)
                    state = self._get_group_state(alias)
                    state.registry_signed_aids = list(smids)
                    self._save_group_state(state)
                self._on_init_complete(data.get("regk", ""))

            elif event_type == "registry_accept_failed":
                self.show_error(f"Registry acceptance failed: {data.get('error')}")

    def _on_init_complete(self, regk: str):
        """Mark initialization as complete."""
        self._on_init_complete_task(regk)

    @qasync.asyncSlot(str)
    async def _on_init_complete_task(self, regk: str):
        group_alias = self._current_group_alias
        if group_alias:
            state = self._get_group_state(group_alias)
            state.init_complete = True
            self._save_group_state(state)

            # Upload the newly-created group identifier to castellan before
            # handing off, so it's already visible on the Issuers list the
            # moment the page navigates there — otherwise the Issuers page's
            # own load can win the race and show the list without it.
            await self._upload_group_identifier(group_alias)

        self._s4_header_lbl.setText("Initialized!")
        self._s4_subtext_lbl.setText(
            "Signatures have been coordinated across participants. "
            "You are ready to issue credentials."
        )

        if self._poller is not None:
            try:
                self.app.vault.remove([self._poller])
            except Exception:
                pass
            self._poller = None

        if self.on_complete:
            self.on_complete(regk)

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
