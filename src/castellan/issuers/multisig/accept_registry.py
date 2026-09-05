# -*- encoding: utf-8 -*-
"""
castellan.issuers.multisig.accept_registry module

AcceptRegistryProposalDialog — participant-side dialog for accepting a
/multisig/vcp registry inception proposal delivered via castellan messages.

Displayed when the plugin intercepts a /multisig/vcp notification.
Launches RegistryAcceptDoer to co-sign the group ixn and send the response
back via castellan + mailbox. The registry is self-backed — there is no
external backer to display.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QHBoxLayout,
    QScrollArea, QFrame,
)
from keri.peer import exchanging
from keri.core.serdering import SerderKERI

from locksmith.ui import colors
from locksmith.ui.toolkit.widgets import (
    LocksmithDialog, LocksmithButton, LocksmithInvertedButton,
)

from .doers import RegistryAcceptDoer

if TYPE_CHECKING:
    from locksmith.core.apping import LocksmithApplication
    from locksmith.ui.vault.page import VaultPage

logger = logging.getLogger(__name__)


class AcceptRegistryProposalDialog(LocksmithDialog):
    """
    Dialog for accepting a Castellan self-backed registry inception proposal
    (/multisig/vcp).

    Displays registry name, group identifier and participants. On accept,
    launches RegistryAcceptDoer.
    """

    def __init__(self, app: "LocksmithApplication", parent: "VaultPage",
                 proposal_said: str):
        self.app = app
        self.parent_widget = parent
        self.proposal_said = proposal_said

        try:
            self._load_proposal()
        except Exception as e:
            logger.exception(f"Failed to load registry proposal: {e}")
            self.proposal_error = str(e)
            self._build_error_ui()
            return

        self._build_ui()
        super().__init__(
            parent=self.parent_widget,
            title="Accept Registry Creation",
            title_icon=":/assets/material-icons/passport.svg",
            content=self.scroll_area,
            buttons=self.button_row,
            show_overlay=False,
        )
        self.setFixedSize(550, 620)
        self.cancel_button.clicked.connect(self.close)
        self.accept_button.clicked.connect(self._on_accept)
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
        if "/multisig/vcp" not in route:
            raise ValueError(f"Not a /multisig/vcp proposal (route: {route})")

        payload = self.exn.ked.get("a", {})
        self.gid = payload.get("gid", "")
        self.usage = payload.get("usage", "")

        embeds = self.exn.ked.get("e", {})
        vcp_sad = embeds.get("vcp")
        if vcp_sad is None:
            raise ValueError("No vcp event in proposal embeds")
        vcp_serder = SerderKERI(sad=vcp_sad)

        self.registry_name = self.usage.replace("Registry: ", "") if self.usage.startswith("Registry: ") else self.gid[:16]

        ghab = self.app.vault.hby.habs.get(self.gid)
        if ghab is None:
            raise ValueError(f"Group hab not found for gid {self.gid[:16]}...")
        self.ghab = ghab

        self.local_mhab = getattr(ghab, "mhab", None)
        if self.local_mhab is None:
            raise ValueError("Could not determine local signing identifier for this group")

        self.smids = list(self.app.vault.hby.db.signingMembers(pre=self.gid))

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

        self._add_section_label(layout, "Registry Proposal")
        self._add_info_row(layout, "Registry:", self.registry_name)
        self._add_info_row(layout, "Group Identifier:", f"{self.gid[:32]}...")

        layout.addSpacing(10)
        self._add_section_label(layout, "Group Participants")
        for i, smid in enumerate(self.smids):
            alias = self._resolve_alias(smid)
            is_local = smid == self.local_mhab.pre
            display = f"{alias}{' (You)' if is_local else ''}" if alias else f"{smid[:20]}..."
            self._add_info_row(layout, f"Member {i + 1}:", display)

        layout.addSpacing(10)
        self._add_section_label(layout, "Your Signing Identifier")
        self._add_info_row(layout, "Identifier:", self.local_mhab.name)
        self._add_info_row(layout, "AID:", f"{self.local_mhab.pre[:24]}...")

        layout.addStretch()

        self.scroll_area.setWidget(content)

        self.button_row = QHBoxLayout()
        self.cancel_button = LocksmithInvertedButton("Decline")
        self.button_row.addWidget(self.cancel_button)
        self.button_row.addSpacing(10)
        self.accept_button = LocksmithButton("Accept & Sign")
        self.button_row.addWidget(self.accept_button)

    def _build_error_ui(self):
        content = QWidget()
        content.setStyleSheet(f"background-color: {colors.BACKGROUND_CONTENT};")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(20, 20, 20, 20)
        err = QLabel(f"Error loading registry proposal:\n\n{self.proposal_error}")
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

    def _on_accept(self):
        self.accept_button.setEnabled(False)
        self.cancel_button.setEnabled(False)
        self.accept_button.setText("Signing...")

        try:
            doer = RegistryAcceptDoer(
                app=self.app,
                proposal_said=self.proposal_said,
                mhab=self.local_mhab,
                signal_bridge=self.app.vault.signals,
            )
            self.app.vault.extend([doer])
        except Exception as e:
            logger.exception(f"Failed to start RegistryAcceptDoer: {e}")
            self.accept_button.setEnabled(True)
            self.cancel_button.setEnabled(True)
            self.accept_button.setText("Accept & Sign")

    def _on_doer_event(self, doer_name: str, event_type: str, data: dict):
        if doer_name != "CastellanRegistryAcceptDoer":
            return
        if event_type == "registry_accept_waiting":
            self.close()
        elif event_type == "registry_accept_failed":
            self.accept_button.setEnabled(True)
            self.cancel_button.setEnabled(True)
            self.accept_button.setText("Accept & Sign")
