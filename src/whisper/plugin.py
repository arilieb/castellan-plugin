# -*- encoding: utf-8 -*-
"""
whisper.plugin module

WhisperPlugin — the reference Locksmith plugin implementation.
Registers Whisper page(s), menus, and lifecycle hooks.
"""
from __future__ import annotations

from typing import Any, TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton
from keri import help

from locksmith.core.essring import APIClient
from locksmith.plugins.base import (
    PluginBase,
    AccountProviderPlugin,
)
from locksmith.ui.vault.menu import MenuButton
from locksmith.ui.toolkit.widgets.buttons import BackButton

from .db.basing import WhisperBaser

if TYPE_CHECKING:
    from locksmith.core.apping import LocksmithApplication
    from locksmith.core.vaulting import Vault
    from locksmith.ui.vault.page import VaultPage

logger = help.ogler.getLogger(__name__)


class WhisperPlugin(
    PluginBase,
    AccountProviderPlugin,
):
    """Reference Locksmith plugin for whisper platform integration."""

    @property
    def plugin_id(self) -> str:
        return "whisper"

    def initialize(self, app: "LocksmithApplication") -> None:
        self._app = app
        self._db: WhisperBaser | None = None
        self._pages: dict[str, QWidget] = {}
        self._build_pages(app)
        self._build_menu()

    def _build_pages(self, app: "LocksmithApplication") -> None:
        """Instantiate all Whisper page widgets and wire cross-page signals."""
        from .credentials.published.list import PublishedCredentialsListPage

        # Create pages — some take (app, parent), others take (parent,)
        # We pass parent=None; VaultPage.register_page() will reparent as needed
        self._pages = {
            "whisper_published_credentials": PublishedCredentialsListPage(app, None),
            "whisper_placeholder": WhisperPlaceholderPage("Whisper", None),
        }

        # Wire cross-page signals (formerly in VaultPage._connect_navigation)
        self._wire_internal_signals()

    def _wire_internal_signals(self) -> None:
        """Wire internal cross-page navigation signals."""
        # May become necessary later
        pass

    def _navigate(self, page_key: str) -> None:
        """Navigate to a page by key using VaultPage._show_page."""
        vault_page = self._get_vault_page()
        if vault_page:
            vault_page._show_page(page_key)

    def _get_vault_page(self):
        """Get the VaultPage instance from the app."""
        if hasattr(self._app, '_vault_page'):
            return self._app._vault_page
        return None

    def _on_account_created(self, account) -> None:
        """Handle account creation — navigate to team start."""
        # May become necessary later
        pass

    def _on_team_created(self, team) -> None:
        """Handle team creation — push plugin menu and navigate to profile."""
        # May become necessary later
        pass

    # -------------------------------------------------------------------------
    # Menu
    # -------------------------------------------------------------------------

    def _build_menu(self) -> None:
        """Build the menu entry button and submenu items."""
        # Entry button for main vault sidebar
        self._account_button = MenuButton(
            QIcon(":/assets/material-icons/forest.svg"),
            "Whisper Credentials"
        )
        self._account_button.is_account_btn = True

        # Submenu items
        self._whisper_submenu_items = self._create_submenu_items()

    def _create_submenu_items(self) -> list[QWidget]:
        """Create the submenu widgets shown when Whisper menu is pushed."""
        items = []

        # Back button
        back_button = BackButton(dark_mode=False)
        items.append(back_button)

        # Logo
        logo = self._create_whisper_logo()
        items.append(logo)

        # Spacer
        from locksmith.ui.vault.menu import MenuSpacer
        items.append(MenuSpacer(15))

        # Navigation buttons
        nav_buttons_config = [
            (":/assets/material-icons/out-badge.svg", "Published Credentials", "whisper_published_credentials"),
        ]

        self._nav_buttons_by_page = {}
        for icon_path, label, page_key in nav_buttons_config:
            btn = MenuButton(QIcon(icon_path), label)
            btn.clicked.connect(self._make_nav_handler(page_key, btn))
            items.append(btn)
            self._nav_buttons_by_page[page_key] = btn

        return items

    def _make_nav_handler(self, page_key: str, button: MenuButton):
        """Create a navigation handler for a submenu button."""
        def handler():
            # Deactivate all nav buttons in the submenu
            for item in self._whisper_submenu_items:
                if isinstance(item, MenuButton):
                    item.set_active(False)
            button.set_active(True)
            # Navigate to the page
            self._navigate(page_key)
            # Trigger on_show if available
            page = self._pages.get(page_key)
            if page and hasattr(page, "on_show"):
                page.on_show()
        return handler

    def _create_whisper_logo(self) -> QWidget:
        """Create Whisper logo for the account menu."""
        container = QWidget()
        container.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(container)
        layout.setContentsMargins(10, 8, 10, 8)

        logo_label = QLabel()
        logo_pixmap = QPixmap(":/assets/custom/logos/healthkeri-main-logo.png")
        if not logo_pixmap.isNull():
            logo_label.setPixmap(logo_pixmap.scaledToWidth(150, Qt.TransformationMode.SmoothTransformation))
        else:
            logo_label.setText("Whisper")
            logo_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #333;")
        logo_label.setStyleSheet("background-color: transparent; border: none;")

        layout.addWidget(logo_label)
        layout.addStretch()

        def on_logo_clicked(event):
            # Navigate to published credentials (default Whisper view)
            for item in self._whisper_submenu_items:
                if isinstance(item, MenuButton):
                    item.set_active(False)
            self._navigate("whisper_published_credentials")
            page = self._pages.get("whisper_published_credentials")
            if page and hasattr(page, "on_show"):
                page.on_show()

        container.mousePressEvent = on_logo_clicked
        return container

    # -------------------------------------------------------------------------
    # PluginBase lifecycle
    # -------------------------------------------------------------------------

    def on_vault_opened(self, vault: "Vault") -> None:
        self._db = WhisperBaser(name=vault.hby.name, reopen=True)

        _, account = next(self._db.whisperAccounts.getItemIter(), (None, None))
        _, team = next(self._db.whisperTeams.getItemIter(), (None, None))

        # Build ESSR client if account exists
        essr = None
        if account is not None:
            hab = vault.hby.habs.get(account.aid)
            if hab is not None:
                essr = APIClient(
                    url=self._app.protectedUrl,
                    root=self._app.root,
                    hby=vault.hby,
                    hab=hab
                )

        vault.plugin_state["whisper"] = {
            "account": account,
            "team": team,
            "essr": essr,
            "db": self._db,
        }

    def on_vault_closed(self, vault: "Vault") -> None:
        vault.plugin_state.pop("whisper", None)
        if self._db:
            self._db.close()
            self._db = None

    def get_menu_entry(self) -> MenuButton:
        return self._account_button

    def get_menu_section(self) -> list[QWidget]:
        return self._whisper_submenu_items

    def get_pages(self) -> dict[str, QWidget]:
        return self._pages

    # -------------------------------------------------------------------------
    # AccountProviderPlugin
    # -------------------------------------------------------------------------

    def is_setup_complete(self, vault: "Vault") -> bool:
        state = vault.plugin_state.get("whisper", {})
        return state.get("account") is not None and state.get("team") is not None

    def get_setup_page(self, vault: "Vault") -> tuple[str, bool]:
        state = vault.plugin_state.get("whisper", {})
        # This should just navigate to a placeholder for now
        if state.get("account") is None:
            return ("whisper_placeholder", False)
        else:
            return ("whisper_published_credentials", True)

    # -------------------------------------------------------------------------
    # ESSR management
    # -------------------------------------------------------------------------

    def resetEssr(self, vault: "Vault") -> None:
        """Reset ESSR client with current account hab."""
        state = vault.plugin_state.get("whisper", {})
        account = state.get("account")
        if account is None:
            logger.warning("Cannot reset ESSR: no hkAccount configured")
            return
        hab = vault.hby.habs.get(account.aid)
        if hab is None:
            logger.warning(f"Cannot reset ESSR: hab not found for aid {account.aid}")
            return
        state["essr"] = APIClient(
            url=self._app.protectedUrl,
            root=self._app.root,
            hby=vault.hby,
            hab=hab
        )

class WhisperPlaceholderPage(QWidget):
    """Placeholder page for Whisper sub-pages (to be implemented later)."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.vault_name = None

        from PySide6.QtWidgets import QVBoxLayout, QLabel
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)

        title_label = QLabel(title)
        title_label.setStyleSheet("font-size: 24px; font-weight: bold; color: #333;")
        layout.addWidget(title_label)

        placeholder_label = QLabel("This plugin currently requires a healthKERI account.")
        placeholder_label.setStyleSheet("font-size: 14px; color: #666;")
        layout.addWidget(placeholder_label)

        layout.addStretch()

    def set_vault_name(self, vault_name: str):
        self.vault_name = vault_name