# -*- encoding: utf-8 -*-
"""
Castellan.plugin module

CastellanPlugin — the reference Locksmith plugin implementation.
Registers castellan page(s), menus, and lifecycle hooks.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QWidget
from keri import help

from locksmith.core.essring import APIClient
from locksmith.plugins.base import (
    PluginBase,
    AccountProviderPlugin,
)
from locksmith.ui.vault.menu import MenuButton
from locksmith.ui.toolkit.widgets.buttons import BackButton

from .db.basing import CastellanBaser

if TYPE_CHECKING:
    from locksmith.core.apping import LocksmithApplication
    from locksmith.core.vaulting import Vault

logger = help.ogler.getLogger(__name__)


class CastellanPlugin(
    PluginBase,
    AccountProviderPlugin,
):
    """Reference Locksmith plugin for castellan platform integration."""

    @property
    def plugin_id(self) -> str:
        return "castellan"

    def initialize(self, app: "LocksmithApplication", parent) -> None:
        self._app = app
        self.parent = parent
        self._db: CastellanBaser | None = None
        self._pages: dict[str, QWidget] = {}
        self._build_pages(app)
        self._build_menu()

    def _build_pages(self, app: "LocksmithApplication") -> None:
        """Instantiate all castellan page widgets."""
        from .schema.list import SchemaListPage
        from .credentials.issued.list import IssuedCredentialsListPage
        from .credentials.received.list import ReceivedCredentialsListPage
        from .setup import CastellanAdminSetupPage

        castellan_setup = CastellanAdminSetupPage(app, self.parent)

        self._pages = {
            "castellan_schema": SchemaListPage(app, None),
            "castellan_issued_credentials": IssuedCredentialsListPage(app, None),
            "castellan_received_credentials": ReceivedCredentialsListPage(app, None),
            "castellan_setup": castellan_setup,
            "castellan_placeholder": CastellanPlaceholderPage("castellan", None),
        }

        castellan_setup.setup_complete_clicked.connect(self._on_setup_complete_event)

    def _show_issued_credentials(self):
        vault_page = self._get_vault_page()
        if vault_page:
            vault_page.nav_menu.push_plugin_menu("castellan")
            vault_page._show_page("castellan_issued_credentials")
            create_page = self._pages.get("castellan_issued_credentialss")
            if create_page and hasattr(create_page, "on_show"):
                create_page.on_show()


    def _navigate(self, page_key: str) -> None:
        vault_page = self._get_vault_page()
        if vault_page:
            vault_page._show_page(page_key)

    def _get_vault_page(self):
        if hasattr(self._app, '_vault_page'):
            return self._app._vault_page
        return None

    # -------------------------------------------------------------------------
    # Menu
    # -------------------------------------------------------------------------

    def _build_menu(self) -> None:
        self._account_button = MenuButton(
            QIcon(":/assets/custom/logos/castellan-lightmode.png"),
            "KERIGuard Issuer"
        )
        self._account_button.is_account_btn = True
        self._castellan_submenu_items = self._create_submenu_items()

    def _create_submenu_items(self) -> list[QWidget]:
        items = []

        back_button = BackButton(dark_mode=False)
        items.append(back_button)

        from locksmith.ui.vault.menu import MenuSpacer
        items.append(MenuSpacer(10))

        nav_buttons_config = [
            (":/assets/material-icons/badge_outgoing.svg", "Issued Credentials", "castellan_issued_credentials"),
            (":/assets/material-icons/badge_incoming.svg", "Received Credentials", "castellan_received_credentials"),
            (":/assets/material-icons/schema.svg", "Schema", "castellan_schema"),
        ]

        self._nav_buttons_by_page = {}
        for icon_path, label, page_key in nav_buttons_config:
            btn = MenuButton(QIcon(icon_path), label)
            btn.clicked.connect(self._make_nav_handler(page_key, btn))
            items.append(btn)
            self._nav_buttons_by_page[page_key] = btn

        return items

    def _refresh_credential_pages(self):
        for key in ("castellan_issued_credentials", "castellan_received_credentials"):
            page = self._pages.get(key)
            if page and hasattr(page, "_refresh_table"):
                page._refresh_table()

    def _make_nav_handler(self, page_key: str, button: MenuButton):
        def handler():
            for item in self._castellan_submenu_items:
                if isinstance(item, MenuButton):
                    item.set_active(False)
            button.set_active(True)
            self._navigate(page_key)
            page = self._pages.get(page_key)
            if page and hasattr(page, "on_show"):
                page.on_show()
        return handler

    # -------------------------------------------------------------------------
    # PluginBase lifecycle
    # -------------------------------------------------------------------------

    def on_vault_opened(self, vault: "Vault") -> None:
        self._db = CastellanBaser(name=vault.hby.name, reopen=True)

        _, settings = next(self._db.castellan_settings.getItemIter(), (None, None))  # type: ignore
        vault.plugin_state["castellan"] = {
            "settings": settings,
            "essr": None,
            "db": self._db,
        }

        if settings:
            self.reset_essr(vault)

    def on_vault_closed(self, vault: "Vault") -> None:
        vault.plugin_state.pop("castellan", None)
        if self._db:
            self._db.close()
            self._db = None

    def on_plugin_reset(self, vault: "Vault") -> None:
        if self._db:
            self._db.close(clear=True)
            self._db = None
        vault.plugin_state.pop("castellan", None)
        self.on_vault_opened(vault)

    @property
    def supports_reset(self) -> bool:
        return True

    def _on_setup_complete_event(self) -> None:
        """Handle vault-level doer events relevant to the castellan plugin."""
        self.reset_essr(self._app.vault)
        self._show_issued_credentials()

    def get_menu_entry(self) -> MenuButton:
        return self._account_button

    def get_menu_section(self) -> list[QWidget]:
        return self._castellan_submenu_items

    def get_pages(self) -> dict[str, QWidget]:
        return self._pages

    # -------------------------------------------------------------------------
    # AccountProviderPlugin
    # -------------------------------------------------------------------------

    def is_setup_complete(self, vault: "Vault") -> bool:
        state = vault.plugin_state.get("castellan", {})
        return state.get("settings") is not None

    def get_setup_page(self, vault: "Vault") -> tuple[str, bool]:
        cdb = self._app.vault.plugin_state.get("castellan", {}).get("db")
        settings = cdb.castellan_settings.get(keys=("settings",)) if cdb else None
        if settings is None or settings.issuer_aid is None:
            page = self._pages.get("castellan_setup")
            if page and hasattr(page, "on_show"):
                page.on_show()
            return "castellan_setup", False
        else:
            return "castellan_schema", True

    # -------------------------------------------------------------------------
    # ESSR management
    # -------------------------------------------------------------------------

    @staticmethod
    def reset_essr(vault: "Vault") -> None:
        """Reset ESSR client with current account hab."""
        state = vault.plugin_state["castellan"]
        settings = state.get("settings")
        if settings is None:
            logger.warning("Cannot reset ESSR: no settings configured")
            return
        hab = vault.hby.habs.get(settings.issuer_aid)
        if hab is None:
            logger.warning(f"Cannot reset ESSR: hab not found for aid {settings.issuer_aid}")
            return

        logger.info(f"Resetting ESSR for registrar {settings.registrar_url} to {settings.registrar_aid}")

        state["essr"] = APIClient(
            url=settings.registrar_url,
            root=settings.registrar_aid,
            hby=vault.hby,
            hab=hab
        )


class CastellanPlaceholderPage(QWidget):
    """Placeholder page for castellan sub-pages (to be implemented later)."""

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
