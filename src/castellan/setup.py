# -*- encoding: utf-8 -*-
"""

keriguard_admin — KERIGuard plugin settings page.
"""
import re
from typing import Optional
from urllib import parse
from urllib.parse import urlparse

import qasync
import requests
from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve, QRect, Signal, QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QButtonGroup, QFrame, QPushButton, QVBoxLayout, )
from keri import help
from keri.app import connecting
from keri.app.habbing import GroupHab
from keri.kering import Schemes
from locksmith.core import habbing
from locksmith.core.apping import LocksmithApplication
from locksmith.core.essring import APIClient
from locksmith.core.signals import DoerSignalBridge
from locksmith.ui import colors
from locksmith.ui.navigation import Pages
from locksmith.ui.toolkit.widgets import CollapsibleSection
from locksmith.ui.toolkit.widgets.buttons import LocksmithButton, LocksmithInvertedButton, LocksmithCopyButton
from locksmith.ui.toolkit.widgets.fields import FloatingLabelComboBox, FloatingLabelLineEdit
from locksmith.ui.toolkit.widgets.page import LocksmithFormPage
from locksmith.ui.vault.page import VaultPage

from castellan.core import remoting
from castellan.db.basing import CastellanSettings

BORDER = "#d7d9dc"
TEXT_PRIMARY = "#1a1a1a"
TEXT_SECONDARY = "#54575a"
PANEL_BG = "#fafbfb"

logger = help.ogler.getLogger(__name__)

OOBI_RE = re.compile(r'\A/oobi/(?P<cid>[^/]+)(?:/(?P<role>[^/]+)(?:/(?P<eid>[^/]+))?)?\Z', re.IGNORECASE)

# --------------------------------------------------------------------------
# KERIGuard Admin Setup Page
# --------------------------------------------------------------------------

class CastellanAdminSetupPage(LocksmithFormPage):

    setup_complete_clicked = Signal()

    SUBTITLES = {
        "opensource": "Open source — connect a public or self-hosted repository.",
        "healthKERI": "Service provider — connect to a vendor-managed integration.",
    }

    def __init__(self, app: "LocksmithApplication", parent: Optional["VaultPage"] = None):
        super().__init__(
            title="KERIGuard Issuer Setup",
            icon_path=":/assets/material-icons/swords.svg",
            parent=parent,
        )
        self.app = app
        self._parent = parent
        self.signals = DoerSignalBridge()
        self._build_content()
        logger.info("KERIGuard setup initialized")

    def _build_content(self):
        self._build_mode_section()
        self._build_registrar_url_section()
        self._build_service_provider_section()
        self._build_issuer_section()
        self.content_layout.addSpacing(40)
        self._build_notification()
        self._build_button_row()
        self.content_layout.addStretch()

    def _build_mode_section(self):
        header = QLabel("Publish Mode")
        header.setStyleSheet("font-weight: 600; font-size: 16px;")
        self.content_layout.addWidget(header)
        self.content_layout.addSpacing(8)

        hint = QLabel(
            "Select the publish mode for your KERIGuard Issuer "
            "whether you want to use the open source registrar or a service provider"
        )
        hint.setStyleSheet(f"color: {colors.TEXT_SUBTLE}; font-size: 13px;")
        hint.setWordWrap(True)
        self.content_layout.addWidget(hint)
        self.content_layout.addSpacing(20)

        self.toggle = SegmentedToggle([
            ("registrar", "Open Source", ":/assets/material-icons/open-source.svg", ":/assets/material-icons/dark-open-source.svg"),
            ("serviceprovider", "Service Provider", ":/assets/material-icons/trip.svg", ":/assets/material-icons/dark-trip.svg"),
        ])
        self.toggle.setFixedWidth(525)
        self.toggle.valueChanged.connect(self._on_toggle_changed)
        self.content_layout.addWidget(self.toggle)

    def _build_service_provider_section(self):

        self._service_provider_section = CollapsibleSection(
            button=self.toggle,
            on_expand_changed=None
        )

        layout = QVBoxLayout()
        layout.addSpacing(24)
        layout.setContentsMargins(25, 0, 0, 0)

        header = QLabel("Service Provider")
        header.setStyleSheet("font-weight: 600; font-size: 16px;")
        layout.addWidget(header)
        layout.addSpacing(8)

        hint = QLabel(
            "Select the Service Provider to use as your watcher network and credential publisher."
        )
        hint.setStyleSheet(f"color: {colors.TEXT_SUBTLE}; font-size: 13px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addSpacing(10)

        self._service_provider_dropdown = FloatingLabelComboBox("Service Provider")
        self._service_provider_dropdown.addItem("healthKERI")

        self._service_provider_dropdown.setFixedWidth(420)
        layout.addWidget(self._service_provider_dropdown)

        self._service_provider_section.set_content_layout(layout)
        self.content_layout.addWidget(self._service_provider_section)

    def _build_registrar_url_section(self):

        self._registrar_url_section = CollapsibleSection(
            button=self.toggle,
            on_expand_changed=None
        )
        self._registrar_url_section.toggle()

        layout = QVBoxLayout()
        layout.addSpacing(24)
        layout.setContentsMargins(25, 0, 0, 0)

        header = QLabel("Castellan Server URL")
        header.setStyleSheet("font-weight: 600; font-size: 16px;")
        layout.addWidget(header)
        layout.addSpacing(8)

        hint = QLabel(
            "Enter the URL and OOBI of the Castellan service. After issuing a credential, "
            "the plugin publishes credentials here."
        )
        hint.setStyleSheet(f"color: {colors.TEXT_SUBTLE}; font-size: 13px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addSpacing(10)

        self._castellan_oobi_field = FloatingLabelLineEdit("Castellan Server OOBI")
        self._castellan_oobi_field.setText("")
        self._castellan_oobi_field.setFixedWidth(420)
        layout.addWidget(self._castellan_oobi_field)

        self._registrar_url_section.set_content_layout(layout)
        self.content_layout.addWidget(self._registrar_url_section)

    def _build_issuer_section(self):

        layout = QVBoxLayout()
        layout.addSpacing(24)
        layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.addLayout(layout)

        header = QLabel("Castellan Account Identifier")
        header.setStyleSheet("font-weight: 600; font-size: 16px;")
        layout.addWidget(header)
        layout.addSpacing(8)

        hint = QLabel(
            "Select the Identifier to use to authenticate with Castellan."
        )
        hint.setStyleSheet(f"color: {colors.TEXT_SUBTLE}; font-size: 13px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addSpacing(10)

        self._issuer_dropdown = FloatingLabelComboBox("Select Castellan identifier")
        self._issuer_dropdown.setFixedWidth(450)
        self._issuer_dropdown.currentIndexChanged.connect(self._on_issuer_changed)
        layout.addWidget(self._issuer_dropdown)
        layout.addSpacing(10)

        # Create OOBI display controls (initially hidden)
        self.oobi_display_container = QWidget()
        oobi_layout = QHBoxLayout(self.oobi_display_container)
        oobi_layout.setContentsMargins(0, 0, 0, 0)

        self._oobi_label = QLabel()
        self._oobi_label.setStyleSheet("font-size: 11px;")
        self._oobi_label.setWordWrap(True)
        oobi_layout.addWidget(self._oobi_label)

        self._oobi_copy_button = LocksmithCopyButton()
        oobi_layout.addWidget(self._oobi_copy_button)

        layout.addWidget(self.oobi_display_container)
        layout.addSpacing(10)

        # Initially hide the OOBI display
        self.oobi_display_container.setVisible(False)


    def _build_notification(self):
        hint = QLabel(
            "Click Complete Setup to save your settings and "
            "create a credential registry for issuing your credentials."
        )
        hint.setStyleSheet(f"color: {colors.TEXT_SUBTLE}; font-size: 15px;")
        hint.setWordWrap(True)

        self.content_layout.addSpacing(10)
        self.content_layout.addWidget(hint)
        self.content_layout.addSpacing(40)

    def _build_button_row(self):
        # --- Button row ---
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self._cancel_btn = LocksmithInvertedButton("Cancel")
        self._cancel_btn.setFixedWidth(140)
        self._cancel_btn.clicked.connect(self._cancel)

        btn_row.addWidget(self._cancel_btn)
        btn_row.addSpacing(12)

        self._complete_btn = LocksmithButton("Complete Setup")
        self._complete_btn.setFixedWidth(180)
        self._complete_btn.clicked.connect(self._save_settings)

        btn_row.addWidget(self._complete_btn)
        btn_row.addStretch()

        self.content_layout.addLayout(btn_row)

    def _cancel(self) -> None:
        self._parent.navigate_to(Pages.VAULT)

    def _validate_form(self) -> tuple[bool, list[str]]:
        """Validate the form fields before saving settings.

        Returns:
            tuple[bool, list[str]]: (is_valid, error_messages)
        """
        errors = []

        # Validate publish mode specific requirements
        mode = self.toggle.value()
        if mode == "serviceprovider":
            if self._service_provider_dropdown.currentIndex() == -1:
                errors.append("Please select a Service Provider.")
        elif mode == "opensource":
            registrar_oobi = self._castellan_oobi_field.text().strip()
            if not registrar_oobi:
                errors.append("Please enter a Castellan OOBI.")
            else:
                # Validate URL format
                try:
                    result = urlparse(registrar_oobi)
                    if not all([result.scheme, result.netloc]):
                        errors.append("Castellan OOBI must be a valid URL (e.g., https://example.com/oobi).")
                except Exception:
                    errors.append("Castellan OOBI must be a valid URL.")

        # Validate issuer selection (index 0 is the empty item)
        if self._issuer_dropdown.currentIndex() <= 0:
            errors.append("Please select an Issuer.")

        return len(errors) == 0, errors

    def _reset_complete_button(self) -> None:
        self._complete_btn.setEnabled(True)
        self._complete_btn.setText("Complete Setup")

    def _save_settings(self) -> None:
        # Validate the form first
        is_valid, errors = self._validate_form()
        if not is_valid:
            self.show_error("\n".join(errors))
            logger.warning(f"Form validation failed: {errors}")
            return

        self.clear_error()

        if not self.app or not self.app.vault:
            return
        cdb = self.app.vault.plugin_state.get("castellan", {}).get("db")
        if cdb is None:
            return

        self._complete_btn.setEnabled(False)
        self._complete_btn.setText("Completing Setup...")

        self._complete_setup(cdb)

    @qasync.asyncSlot()
    async def _complete_setup(self, cdb) -> None:
        """
        Resolve the registrar OOBI, verify the Castellan server is actually
        reachable over ESSR, and only then persist settings and proceed.

        If the ESSR /health roundtrip cannot succeed even once, the setup is aborted,
        no settings are persisted, and an error is shown so the user can retry.
        """
        try:
            hby = self.app.vault.hby

            settings = CastellanSettings()
            issuer_alias = self._issuer_dropdown.currentData()
            logger.info(f"setting issuer alias as {issuer_alias}")
            hab = hby.habByName(issuer_alias)
            settings.issuer_aid = hab.pre

            registrar_oobi = self._castellan_oobi_field.text().strip()
            if registrar_oobi:
                purl = parse.urlparse(registrar_oobi)

                match = OOBI_RE.match(purl.path)
                if not match:
                    raise ValueError("Invalid OOBI format")

                settings.registrar_aid = match.group("cid")

                response = requests.get(registrar_oobi)
                hab.psr.parse(ims=response.content)

                hab.kvy.processEscrows()

                org = connecting.Organizer(hby=hby)
                org.update(pre=settings.registrar_aid, data=dict(alias="castellan-registrar", oobi=registrar_oobi))

                urls = hab.fetchUrls(eid=settings.registrar_aid, scheme="tcp")
                settings.registrar_url = urls.get(Schemes.tcp, None)

                if not settings.registrar_url:
                    raise ValueError(f"Castellan URL not registered with Castellan AID {settings.registrar_aid}).")

            publish_mode = self.toggle.value()
            if publish_mode is not None:
                settings.publish_mode = publish_mode

            essr = APIClient(
                url=settings.registrar_url,
                root=settings.registrar_aid,
                hby=hby,
                hab=hab,
            )

            health_result = await remoting.essr_health_guard(essr, max_attempts=1)
            if not health_result.get('success'):
                raise ConnectionError(
                    "Could not reach the Castellan server via ESSR after 1 attempt(s). "
                    f"({health_result.get('error', 'Unknown error')}). "
                    "Please verify that you have created an account on the server for the Castellan account identifier, then try again."
                )

            cdb.castellan_settings.pin(keys=("settings",), val=settings)
            self.app.vault.plugin_state["castellan"]["settings"] = settings
            self.app.vault.plugin_state["castellan"]["essr"] = essr
            self.settings = settings

            logger.info("Castellan admin setup complete")
            self.setup_complete_clicked.emit()

        except Exception as e:
            logger.exception(f"Castellan setup failed: {e}")
            self._reset_complete_button()
            self.show_error(str(e))

    def on_show(self) -> None:
        logger.info("Castellan setup shown")
        # This page is created once and reused for the app's lifetime (see
        # CastellanPlugin._build_pages), so a stale "Completing Setup..."
        # disabled state from a prior successful/interrupted attempt can
        # otherwise persist across a plugin reset that brings the user back
        # here. Always restore the button to its base state on show.
        self._reset_complete_button()
        self._load_dropdowns()

    def _on_toggle_changed(self, value: str):
        self._service_provider_section.toggle()
        self._registrar_url_section.toggle()

    def _on_issuer_changed(self, index: int) -> None:
        """
        Handle issuer dropdown selection change.

        Args:
            index: The index of the newly selected item in the dropdown
        """
        if index <= 0:
            # Empty item selected - hide OOBI display
            logger.debug("Empty issuer item selected")
            self.oobi_display_container.setVisible(False)
            return

        # Get the issuer alias from userData
        issuer_alias = self._issuer_dropdown.currentData()
        if not issuer_alias:
            logger.warning("No issuer alias found in dropdown userData")
            self.oobi_display_container.setVisible(False)
            return

        hab = self.app.vault.hby.habByName(issuer_alias)
        if hab is None:
            logger.warning(f"Selected issuer '{issuer_alias}' not found in Habby")
            self.oobi_display_container.setVisible(False)
            return

        oobi_result = habbing.generate_oobi(self.app, hab)

        if not oobi_result['success'] or not oobi_result['oobi']:
            logger.warning(f"Failed to generate OOBi for issuer '{issuer_alias}'")
            self.oobi_display_container.setVisible(False)
            return

        oobi_url = oobi_result['oobi']

        # Update the label text and copy button content
        self._oobi_label.setText(oobi_url)
        self._oobi_copy_button.set_copy_content(oobi_url)

        # Show the OOBI display
        self.oobi_display_container.setVisible(True)

        logger.debug(f"Issuer changed to: {issuer_alias}")

    def selected_mode(self) -> str:
        return self.toggle.value()

    def _load_dropdowns(self):
        if not self.app or not self.app.vault:
            return

        hby = self.app.vault.hby

        self._issuer_dropdown.clear()

        # Add empty item to force user selection
        self._issuer_dropdown.addItem("", userData=None)

        # hby.habs is keyed by AID prefix; hab.name is the human alias
        issuer_count = 0
        for aid, hab in hby.habs.items():
            if isinstance(hab, GroupHab) or not hab.kever.wits:
                continue
            display = f"{hab.name} — {aid}"
            # Store hab.name as userData for easy retrieval
            self._issuer_dropdown.addItem(display, userData=hab.name)
            issuer_count += 1

        # Set to empty item by default (index 0)
        self._issuer_dropdown.setCurrentIndex(0)

        # If only one issuer available, auto-select it
        if issuer_count == 1:
            self._issuer_dropdown.setCurrentIndex(1)



# --------------------------------------------------------------------------
# Segmented toggle control
# --------------------------------------------------------------------------

class SegmentedToggle(QWidget):
    """Two-option segmented control with an animated sliding highlight."""

    valueChanged = Signal(str)

    def __init__(self, options: list[tuple[str, str, str, str]], parent=None):
        """options: exactly two (value, label) tuples."""
        super().__init__(parent)

        assert len(options) == 2, "SegmentedToggle only supports two options"
        self._options = options
        self._current_index = 0
        self.setFixedHeight(40)

        self._track = QFrame(self)
        self._track.setObjectName("track")
        self._track.setStyleSheet(f"""
            #track {{
                background: #eceef0;
                border: 1px solid {BORDER};
                border-radius: 20px;
            }}
        """)

        self._highlight = QFrame(self._track)
        self._highlight.setStyleSheet(f"""
            background: {colors.PRIMARY};
            border-radius: 17px;
        """)

        self._buttons: list[tuple[QPushButton, str, str]] = []
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

        for i, (_value, label, icon_path, dark_icon_path) in enumerate(options):
            btn = QPushButton(label, self._track)
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)  # type: ignore
            btn.setFlat(True)
            icon = QIcon(icon_path)
            btn.setIcon(icon)
            btn.setIconSize(QSize(20, 20))
            self._group.addButton(btn, i)
            self._buttons.append((btn, icon_path, dark_icon_path))

        self._buttons[0][0].setChecked(True)
        self._highlight.lower()  # keep highlight behind button text
        self._group.idClicked.connect(self._on_clicked)

        self._anim = QPropertyAnimation(self._highlight, b"geometry")
        self._anim.setDuration(220)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)  # type: ignore

        self._update_text_colors()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._track.setGeometry(0, 0, self.width(), self.height())
        seg_w = self.width() // 2
        for i, (btn, _, _) in enumerate(self._buttons):
            btn.setGeometry(i * seg_w, 0, seg_w, self.height())
        self._highlight.setGeometry(
            self._current_index * seg_w + 3, 3, seg_w - 6, self.height() - 6
        )

    def _on_clicked(self, index: int):
        self._animate_to(index)
        value, _label, _icon_path, _dark = self._options[index]
        self.valueChanged.emit(value)

    def _animate_to(self, index: int):
        seg_w = self.width() // 2
        end_rect = QRect(index * seg_w + 3, 3, seg_w - 6, self.height() - 6)
        self._anim.stop()
        self._anim.setStartValue(self._highlight.geometry())
        self._anim.setEndValue(end_rect)
        self._anim.start()
        self._current_index = index
        self._update_text_colors()

    def _update_text_colors(self):
        for i, (btn, icon_path, dark_icon_path) in enumerate(self._buttons):
            color = "#ffffff" if i == self._current_index else TEXT_SECONDARY
            btn.setStyleSheet(f"""
                QPushButton {{
                    border: none;
                    font-size: 13px;
                    font-weight: 600;
                    color: {color};
                }}
            """)
            icon = QIcon(icon_path if i == self._current_index else dark_icon_path)
            btn.setIcon(icon)
            btn.setIconSize(QSize(20, 20))


    def value(self) -> str:
        return self._options[self._current_index][0]


# --------------------------------------------------------------------------
# Content panels (the part that "morphs")
# --------------------------------------------------------------------------

def _field_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {TEXT_SECONDARY};")
    return label


