# -*- encoding: utf-8 -*-
"""
castellan.issuers.multisig.accept_group module

AcceptGroupProposalDialog — participant-side dialog for accepting a
/multisig/icp group inception proposal delivered via castellan messages.

Mirrors locksmith's AcceptMultisigProposalDialog layout but launches
MultisigJoinDoer (which sends responses via castellan + mailbox) instead of
the standard MultisigJoinDoer (KERI Poster/mailbox transport only).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QHBoxLayout,
    QScrollArea, QFrame,
)
from keri.help import helping
from keri.peer import exchanging
from keri.core.serdering import SerderKERI

from locksmith.ui import colors
from locksmith.ui.toolkit.widgets import (
    LocksmithDialog, LocksmithButton, LocksmithInvertedButton,
    FloatingLabelLineEdit,
)
from locksmith.ui.toolkit.widgets.fields import FloatingLabelComboBox

from .doers import MultisigJoinDoer

if TYPE_CHECKING:
    from locksmith.core.apping import LocksmithApplication
    from locksmith.ui.vault.page import VaultPage

logger = logging.getLogger(__name__)


class AcceptGroupProposalDialog(LocksmithDialog):
    """
    Dialog for accepting a Castellan multisig group inception proposal.

    Displayed when the CastellanMessagePoller delivers a /multisig/icp EXN
    and the plugin intercepts the resulting notification.
    """

    def __init__(self, app: "LocksmithApplication", parent: "VaultPage",
                 proposal_said: str, multisig_alias: str = ""):
        self.app = app
        self.parent_widget = parent
        self.proposal_said = proposal_said
        self.multisig_alias = multisig_alias

        try:
            self._load_proposal()
        except Exception as e:
            logger.exception(f"Failed to load group proposal: {e}")
            self.proposal_error = str(e)
            self._build_error_ui()
            return

        self._build_ui()

        super().__init__(
            parent=self.parent_widget,
            title="Join Multisig Group",
            title_icon=":/assets/material-icons/group_add.svg",
            content=self.scroll_area,
            buttons=self.button_row,
            show_overlay=False,
        )
        self.setFixedSize(550, 780)
        self.cancel_button.clicked.connect(self.close)
        self.join_button.clicked.connect(self._on_join)
        if hasattr(self.app, "vault") and self.app.vault and hasattr(self.app.vault, "signals"):
            self.app.vault.signals.doer_event.connect(self._on_doer_event)

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load_proposal(self):
        self.exn, self.pathed = exchanging.cloneMessage(
            self.app.vault.hby, self.proposal_said
        )
        if self.exn is None:
            raise ValueError(f"Proposal not found: {self.proposal_said}")

        route = self.exn.ked.get("r", "")
        if "/multisig/icp" not in route:
            raise ValueError(f"Not a /multisig/icp proposal (route: {route})")

        self.initiator = self.exn.ked["i"]
        self.timestamp = self.exn.ked.get("dt", "")

        payload = self.exn.ked.get("a", {})
        self.gid = payload.get("gid", "")
        self.smids = payload.get("smids", [])
        self.rmids = payload.get("rmids", self.smids)

        embeds = self.exn.ked.get("e", {})
        icp_sad = embeds.get("icp")
        if icp_sad is None:
            raise ValueError("No icp event in proposal embeds")
        icp_serder = SerderKERI(sad=icp_sad)
        self.isith = icp_serder.ked.get("kt", "1")
        self.nsith = icp_serder.ked.get("nt", self.isith)

        self.local_smids = [
            {"alias": hab.name, "pre": hab.pre}
            for _, hab in self.app.vault.hby.habs.items()
            if hab.pre in self.smids
        ]
        if not self.local_smids:
            raise ValueError("None of your local identifiers are in this proposal")

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        content.setStyleSheet(f"background-color: {colors.BACKGROUND_CONTENT};")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        self._add_section_label(layout, "Proposal Information")
        self._add_info_row(layout, "From:", self._resolve_alias(self.initiator) or f"{self.initiator[:24]}...")
        if self.timestamp:
            try:
                ts = helping.fromIso8601(self.timestamp).strftime("%b %d, %Y %I:%M %p")
            except Exception:
                ts = self.timestamp
            self._add_info_row(layout, "Received:", ts)
        self._add_info_row(layout, "Group ID:", f"{self.gid[:32]}...")

        layout.addSpacing(10)
        self._add_section_label(layout, "Participants")
        for i, smid in enumerate(self.smids):
            alias = self._resolve_alias(smid)
            is_local = any(l["pre"] == smid for l in self.local_smids)
            display = f"{alias}{' (You)' if is_local else ''}" if alias else f"{smid[:20]}..."
            self._add_info_row(layout, f"Member {i + 1}:", display)

        layout.addSpacing(10)
        self._add_section_label(layout, "Configuration")
        self._add_info_row(layout, "Signing Threshold:", str(self.isith))
        self._add_info_row(layout, "Rotation Threshold:", str(self.nsith))
        self._add_info_row(layout, "Total Participants:", str(len(self.smids)))

        layout.addSpacing(20)
        self._add_section_label(layout, "Select Your Identifier")

        alias_note = QLabel("Choose a local name for this group identifier.")
        if self.multisig_alias:
            alias_note.setText("Alias is set by the proposer:")

        alias_note.setStyleSheet(f"color: {colors.TEXT_SUBTLE}; font-size: 13px;")
        alias_note.setWordWrap(True)
        alias_note.setFixedWidth(420)
        layout.addWidget(alias_note)

        self.group_alias_field = FloatingLabelLineEdit("Group Identifier Alias")
        self.group_alias_field.setText(self.multisig_alias or "")
        if self.multisig_alias:
            self.group_alias_field.setEnabled(False)
        self.group_alias_field.setFixedWidth(420)
        layout.addWidget(self.group_alias_field)

        self.local_id_dropdown = FloatingLabelComboBox("Local Identifier")
        self.local_id_dropdown.setFixedWidth(420)
        for item in self.local_smids:
            self.local_id_dropdown.addItem(f"{item['alias']}", item)
        layout.addWidget(self.local_id_dropdown)

        layout.addStretch()
        self.scroll_area.setWidget(content)

        self.button_row = QHBoxLayout()
        self.cancel_button = LocksmithInvertedButton("Close")
        self.button_row.addWidget(self.cancel_button)
        self.button_row.addSpacing(10)
        self.join_button = LocksmithButton("Join")
        self.button_row.addWidget(self.join_button)

    def _build_error_ui(self):
        content = QWidget()
        content.setStyleSheet(f"background-color: {colors.BACKGROUND_CONTENT};")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(20, 20, 20, 20)
        err = QLabel(f"Error loading proposal:\n\n{self.proposal_error}")
        err.setStyleSheet(f"color: {colors.DANGER};")
        err.setWordWrap(True)
        layout.addWidget(err)
        layout.addStretch()
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setWidget(content)
        self.button_row = QHBoxLayout()
        close_btn = LocksmithInvertedButton("Close")
        close_btn.clicked.connect(self.close)
        self.button_row.addWidget(close_btn)
        super().__init__(
            parent=self.parent_widget,
            title="Error",
            content=self.scroll_area,
            buttons=self.button_row,
            show_overlay=False,
        )
        self.setFixedSize(400, 250)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _add_section_label(self, layout, text: str):
        lbl = QLabel(text)
        lbl.setStyleSheet("font-weight: 600; font-size: 16px;")
        layout.addWidget(lbl)

    def _add_info_row(self, layout, label_text: str, value_text: str):
        row = QHBoxLayout()
        lbl = QLabel(label_text)
        lbl.setStyleSheet("font-weight: 500;")
        lbl.setFixedWidth(140)
        row.addWidget(lbl)
        val = QLabel(value_text)
        val.setStyleSheet(f"color: {colors.TEXT_MENU};")
        val.setWordWrap(True)
        row.addWidget(val, stretch=1)
        layout.addLayout(row)

    def _resolve_alias(self, pre: str) -> str | None:
        for prefix, hab in self.app.vault.hby.habs.items():
            if prefix == pre:
                return hab.name
        contact = self.app.vault.org.get(pre)
        if contact:
            return contact.get("alias")
        return None

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _on_join(self):
        mhab_data = self.local_id_dropdown.currentData()
        if not mhab_data:
            return
        if self.multisig_alias:
            alias = self.multisig_alias
        else:
            alias = self.group_alias_field.text().strip()
        if not alias:
            return
        mhab = self.app.vault.hby.habByName(mhab_data["alias"])
        if mhab is None:
            return

        self.join_button.setEnabled(False)
        self.cancel_button.setEnabled(False)
        self.join_button.setText("Joining...")

        try:
            doer = MultisigJoinDoer(
                app=self.app,
                alias=alias,
                proposal_said=self.proposal_said,
                mhab=mhab,
                signal_bridge=self.app.vault.signals,
            )
            self.app.vault.extend([doer])
        except Exception as e:
            logger.exception(f"Failed to start MultisigJoinDoer: {e}")
            self.join_button.setEnabled(True)
            self.cancel_button.setEnabled(True)
            self.join_button.setText("Join")

    def _on_doer_event(self, doer_name: str, event_type: str, data: dict):
        if doer_name != "CastellanMultisigJoinDoer":
            return
        if event_type == "group_join_waiting":
            self.close()
        elif event_type == "group_join_failed":
            self.join_button.setEnabled(True)
            self.cancel_button.setEnabled(True)
            self.join_button.setText("Join")
