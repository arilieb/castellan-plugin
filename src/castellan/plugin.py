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
from keri.app import grouping as keri_grouping
from keri.peer import exchanging as keri_exchanging

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

    def get_description(self) -> str:
        return (
            "Castellan integration for enterprise credential management. Propogate issued credentials, received "
            "credentials, and TEL events through a server or service provider."
        )

    def initialize(self, app: "LocksmithApplication", parent) -> None:
        self._app = app
        self.parent = parent
        self._db: CastellanBaser | None = None
        self._pages: dict[str, QWidget] = {}
        self._identifier_poller = None
        self._message_poller = None
        self._open_group_dialog_gid: str | None = None
        self._open_registry_dialog_gid: str | None = None
        self._build_pages(app)
        self._build_menu()

    def _build_pages(self, app: "LocksmithApplication") -> None:
        """Instantiate all castellan page widgets."""
        from .schema.list import SchemaListPage
        from .credentials.issued.list import IssuedCredentialsListPage
        from .credentials.received.list import ReceivedCredentialsListPage
        from .issuers.list import IdentifiersListPage
        # from .issuers.multisig.initiate import InitiateMultisigPage
        from .setup import CastellanAdminSetupPage

        castellan_setup = CastellanAdminSetupPage(app, self.parent)

        self._pages = {
            "castellan_schema": SchemaListPage(app, None),
            "castellan_issued_credentials": IssuedCredentialsListPage(app, None),
            "castellan_received_credentials": ReceivedCredentialsListPage(app, None),
            "castellan_issuers": IdentifiersListPage(
                app, on_navigate_to_multisig_init=self._navigate_to_multisig_init, parent=None
            ),
            # "castellan_multisig_init": InitiateMultisigPage(
            #     app, on_complete=self._on_multisig_init_complete, parent=None
            # ),
            "castellan_setup": castellan_setup,
            "castellan_placeholder": CastellanPlaceholderPage("castellan", None),
        }

        castellan_setup.setup_complete_clicked.connect(self._on_setup_complete_event)

    def _on_multisig_init_complete(self, regk: str) -> None:
        """Called when InitiateMultisigPage finishes group+registry setup."""
        logger.info(f"Castellan multisig init complete, registry {regk}")
        self._navigate("castellan_issuers")
        page = self._pages.get("castellan_issuers")
        if page and hasattr(page, "on_show"):
            page.on_show()

    def _navigate_to_multisig_init(self) -> None:
        """
        Callback threaded down: plugin._build_pages -> IdentifiersListPage
        -> UploadIdentifierDialog's "Create a Castellan Multisig" link.
        Navigates to InitiateMultisigPage without a submenu button (intentionally
        NOT in nav_buttons_config — reachable only from this link, at this stage
        of development). "castellan_setup"/"castellan_placeholder" are existing
        precedent for a registered page with no nav_buttons_config entry.
        """
        self._navigate("castellan_multisig_init")
        page = self._pages.get("castellan_multisig_init")
        if page and hasattr(page, "on_show"):
            page.on_show()

    def _show_issued_credentials(self):
        vault_page = self._get_vault_page()
        if vault_page:
            vault_page.nav_menu.push_plugin_menu("castellan")
            vault_page._show_page("castellan_issued_credentials")
            create_page = self._pages.get("castellan_issued_credentials")
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
            (":/assets/material-icons/group.svg", "Issuers", "castellan_issuers"),
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
            # self._start_multisig_listening(vault)

    def on_vault_closed(self, vault: "Vault") -> None:
        # self._stop_multisig_listening(vault)
        vault.plugin_state.pop("castellan", None)
        if self._db:
            self._db.close()
            self._db = None

    # -------------------------------------------------------------------------
    # Multisig background listening (peer discovery poll + EXN relay poll)
    # -------------------------------------------------------------------------

    def _start_multisig_listening(self, vault: "Vault") -> None:
        """
        Wire an Exchanger + message poller so incoming multisig group/registry
        proposals can surface a dialog at any time, regardless of which page
        the user is on — matches whisper's original background-listening UX.
        """
        from .issuers.multisig.poller import UploadedIdentifierPoller
        from .issuers.multisig.doers import (
            CastellanMessagePoller,
            CounselingCompletionDoer,
            RegistryAcceptCompletionDoer,
        )

        castellan_exc = keri_exchanging.Exchanger(hby=vault.hby, handlers=[])
        keri_grouping.loadHandlers(exc=castellan_exc, mux=vault.mux)
        vault.plugin_state["castellan"]["exc"] = castellan_exc

        if hasattr(vault, "signals") and vault.signals:
            if hasattr(vault.signals, "new_notification"):
                vault.signals.new_notification.connect(self._on_new_notification)

        self._identifier_poller = UploadedIdentifierPoller(self._app)
        self._message_poller = CastellanMessagePoller(self._app, exc=castellan_exc)
        vault.extend([self._identifier_poller, self._message_poller])
        self._identifier_poller.signals.initial_load_complete.connect(
            self._message_poller.mark_kel_load_ready
        )

        # Resume any in-progress group-setup attempts left open across restart.
        from keri.app.habbing import GroupHab as _GroupHab
        from keri.core import coring as _kc

        for (alias,), state in self._db.castellan_multisig_init.getItemIter():
            if state.init_complete:
                continue

            if state.init_step == 3 and state.section4_started:
                for (pre,), (seqner, _saider) in vault.hby.db.gpse.getItemIter():
                    _hab = vault.hby.habByPre(pre)
                    if _hab is not None and isinstance(_hab, _GroupHab) and _hab.name == alias:
                        vault.extend([CounselingCompletionDoer(
                            app=self._app,
                            prefixer=_kc.Prefixer(qb64=pre),
                            seqner=seqner,
                            ghab=_hab,
                            is_proposer=state.is_proposer,
                        )])
                        logger.info(
                            f"Castellan: resuming group counseling for '{alias}' "
                            f"({'proposer' if state.is_proposer else 'joiner'})"
                        )
                        break

            elif state.init_step >= 4 and not state.is_proposer:
                registry_name = f"{alias}-registry"
                registry = vault.rgy.registryByName(registry_name)
                if registry is not None:
                    from keri.vdr import credentialing as _vdr
                    _reg_check = _vdr.Registrar(hby=vault.hby, rgy=vault.rgy, counselor=vault.counselor)
                    if not _reg_check.complete(pre=registry.regk, sn=0):
                        vault.extend([RegistryAcceptCompletionDoer(
                            app=self._app,
                            registry=registry,
                            signal_bridge=vault.signals,
                        )])
                        logger.info(f"Castellan: resuming registry acceptance for '{alias}' (joiner)")

    def _stop_multisig_listening(self, vault: "Vault") -> None:
        if hasattr(vault, "signals") and vault.signals and hasattr(vault.signals, "new_notification"):
            try:
                vault.signals.new_notification.disconnect(self._on_new_notification)
            except (RuntimeError, TypeError):
                pass
        doers = [d for d in (self._identifier_poller, self._message_poller) if d is not None]
        if doers:
            try:
                vault.remove(doers)
            except Exception:
                pass
        self._identifier_poller = None
        self._message_poller = None
        self._open_group_dialog_gid = None
        self._open_registry_dialog_gid = None

    def _on_new_notification(self, notification: dict) -> None:
        """Intercept vault notifications and open the appropriate multisig dialog."""
        try:
            route = notification.get("r", "")
            said = notification.get("d", "")
            if not said:
                return
            vault_page = self._get_vault_page()
            if vault_page is None:
                return

            if "/multisig/icp" in route:
                # Distinguish a new invitation (group hab doesn't exist yet) from a
                # co-signer response to our own proposal (group hab already exists).
                _is_response = False
                _exn = self._app.vault.hby.db.exns.get(keys=(said,))
                _gid = ""

                if _exn is not None:
                    _icp_sad = _exn.ked.get("e", {}).get("icp", {})
                    _gid = _icp_sad.get("i", "") if isinstance(_icp_sad, dict) else ""
                    if _gid and self._app.vault.hby.habs.get(_gid) is not None:
                        _is_response = True
                        _sender = _exn.ked.get("i", "")
                        if _sender:
                            self._app.vault.plugin_state.setdefault("castellan", {}).setdefault(
                                "group_join_tracker", set()
                            ).add(_sender)
                            _db = self._app.vault.plugin_state.get("castellan", {}).get("db")
                            _ghab = self._app.vault.hby.habs.get(_gid)
                            if _db is not None and _ghab is not None:
                                _ws = _db.castellan_multisig_init.get(keys=(_ghab.name,))
                                if _ws is not None and _sender not in _ws.group_signed_aids:
                                    _ws.group_signed_aids.append(_sender)
                                    _db.castellan_multisig_init.pin(keys=(_ghab.name,), val=_ws)
                            if self._app.vault.signals:
                                self._app.vault.signals.emit_doer_event(
                                    "CastellanGroupMultisigInceptDoer", "group_participant_signed",
                                    {"signer_aid": _sender}
                                )
                if not _is_response:
                    if not _gid or self._open_group_dialog_gid == _gid:
                        return
                    multisig_alias = notification.get("multisig_alias", "")
                    from .issuers.multisig.accept_group import AcceptGroupProposalDialog
                    dialog = AcceptGroupProposalDialog(
                        app=self._app, parent=vault_page, proposal_said=said,
                        multisig_alias=multisig_alias,
                    )
                    self._open_group_dialog_gid = _gid

                    def _clear_group_dialog():
                        self._open_group_dialog_gid = None

                    dialog.finished.connect(_clear_group_dialog)
                    dialog.open()
            elif "/multisig/vcp" in route:
                _is_response = False
                _exn = self._app.vault.hby.db.exns.get(keys=(said,))
                _gid = ""

                if _exn is not None:
                    _gid = _exn.ked.get("a", {}).get("gid", "")
                    if _gid:
                        _ghab = self._app.vault.hby.habs.get(_gid)
                        if _ghab is not None:
                            _reg_name = f"{_ghab.name}-registry"
                            if self._app.vault.rgy.registryByName(_reg_name) is not None:
                                _is_response = True
                                _sender = _exn.ked.get("i", "")
                                if _sender:
                                    self._app.vault.plugin_state.setdefault("castellan", {}).setdefault(
                                        "registry_sign_tracker", set()
                                    ).add(_sender)
                                    _db = self._app.vault.plugin_state.get("castellan", {}).get("db")
                                    if _db is not None:
                                        _ws = _db.castellan_multisig_init.get(keys=(_ghab.name,))
                                        if _ws is not None and _sender not in _ws.registry_signed_aids:
                                            _ws.registry_signed_aids.append(_sender)
                                            _db.castellan_multisig_init.pin(keys=(_ghab.name,), val=_ws)
                                    if self._app.vault.signals:
                                        self._app.vault.signals.emit_doer_event(
                                            "CastellanCreateRegistryDoer", "registry_participant_signed",
                                            {"signer_aid": _sender}
                                        )
                if not _is_response:
                    if not _gid or self._open_registry_dialog_gid == _gid:
                        return
                    from .issuers.multisig.accept_registry import AcceptRegistryProposalDialog
                    dialog = AcceptRegistryProposalDialog(
                        app=self._app, parent=vault_page, proposal_said=said,
                    )
                    self._open_registry_dialog_gid = _gid

                    def _clear_registry_dialog():
                        self._open_registry_dialog_gid = None

                    dialog.finished.connect(_clear_registry_dialog)
                    dialog.open()
        except Exception:
            logger.exception("Error handling new notification in CastellanPlugin")

    def on_plugin_reset(self, vault: "Vault") -> None:
        # self._stop_multisig_listening(vault)
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
        if self._identifier_poller is None:
            # self._start_multisig_listening(self._app.vault)
            pass
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
