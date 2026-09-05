# -*- encoding: utf-8 -*-
"""
castellan.issuers.list module

Identifiers list page — shows peer-discovery identifiers uploaded to the
Castellan server (self + peers).
"""
from typing import Any, Callable, TYPE_CHECKING

import qasync
from PySide6.QtGui import QPalette, QColor
from PySide6.QtWidgets import QWidget, QVBoxLayout, QDialog
from keri import help
from keri.help import helping
from locksmith.ui import colors
from locksmith.ui.toolkit.tables import PaginatedTableWidget

from .upload import UploadIdentifierDialog
from .view import ViewIdentifierDialog
from ..credentials.issued.list import _exec_dialog_async
from ..credentials.issued.server_update import ServerUpdateDialog
from ..core import remoting

if TYPE_CHECKING:
    from locksmith.ui.vault.page import VaultPage

logger = help.ogler.getLogger(__name__)


class IdentifiersListPage(QWidget):
    """Paginated list of peer-discovery identifiers uploaded to the Castellan server."""

    def __init__(
        self,
        app,
        on_navigate_to_multisig_init: Callable[[], None] | None = None,
        parent: "VaultPage | None" = None,
    ):
        super().__init__(parent)
        self._parent = parent
        self.app = app
        self.on_navigate_to_multisig_init = on_navigate_to_multisig_init
        self.vault_name = ""
        self._identifiers_cache: dict[str, dict[str, Any]] = {}
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(colors.BACKGROUND_CONTENT))
        self.setPalette(palette)
        self.setAutoFillBackground(True)

        self.table = PaginatedTableWidget(
            columns=["Alias", "AID", "Seq No", "Uploaded"],
            column_widths={"Alias": 170, "Uploaded": 165, "Actions": 50, "Seq No": 100},
            title="Issuers",
            icon_path=":/assets/material-icons/group.svg",
            show_add_button=True,
            add_button_text="Add Issuer",
            row_actions=["View", "Update", "Delete"],
            row_action_icons={
                "View": ":/assets/material-icons/view.svg",
                "Update": ":/assets/material-icons/cloud_sync.svg",
                "Delete": ":/assets/material-icons/delete.svg",
            },
            row_actions_callback=self._get_row_actions,
            items_per_page=10,
            show_search=True,
            column_sort_mapping={"Alias": "alias", "AID": "aid", "Uploaded": "created_at"},
            transform_func=self._transform_identifier_to_row,
            parent=self,
        )
        self.table.add_clicked.connect(self._on_add_identifier)
        self.table.row_action_triggered.connect(self._on_row_action_signal)
        self.table.row_clicked.connect(self._on_row_clicked)
        self.table.load_requested.connect(self._on_load_requested)
        self.table.load_error.connect(self._on_load_error)

        layout.addWidget(self.table)

    def _transform_identifier_to_row(self, identifier: dict[str, Any]) -> dict[str, Any]:
        aid = identifier.get('aid', '')
        alias = identifier.get('alias', '')
        created_at = helping.fromIso8601(identifier.get('created_at', '')).strftime("%b %d, %Y %I:%M %p")

        hab = self.app.vault.hby.habs.get(aid)
        is_local = hab is not None

        seq_display = "—"
        is_out_of_sync = False
        local_sn = remote_sn = None
        if is_local:
            local_sn = int(hab.kever.state().s, 16)
            key_state = identifier.get('key_state')
            if key_state:
                remote_sn = int(key_state.get('s', '0'), 16)
                seq_display = f"{remote_sn}({local_sn})"
                is_out_of_sync = local_sn > remote_sn

        row_data = {
            'Alias': alias,
            'AID': aid,
            'Seq No': seq_display,
            'Uploaded': created_at,
            '_aid': aid,
            '_is_local': is_local,
            '_out_of_sync': is_out_of_sync,
        }

        if is_out_of_sync:
            row_data['Seq No_color'] = colors.DANGER
            row_data['Seq No_tooltip'] = (
                f"Local sequence number ({local_sn}) is ahead of the Castellan "
                f"server's ({remote_sn}). Use 'Update' to sync."
            )
        elif is_local and remote_sn is not None:
            row_data['Seq No_color'] = colors.SUCCESS_INDICATOR

        self._identifiers_cache[aid] = identifier
        return row_data

    def _get_row_actions(self, row_data: dict[str, Any]) -> tuple[list[str], dict[str, str]]:
        all_icons = {
            "View": ":/assets/material-icons/view.svg",
            "Update": ":/assets/material-icons/cloud_sync.svg",
            "Delete": ":/assets/material-icons/delete.svg",
        }
        actions = ["View"]
        if row_data.get('_is_local'):
            if row_data.get('_out_of_sync'):
                actions.append("Update")
            actions.append("Delete")
        return actions, {a: all_icons[a] for a in actions}

    @qasync.asyncSlot(dict)
    async def _on_load_requested(self, params: dict):
        if not self.app:
            self.table.load_error.emit("No app instance available")
            return

        self._identifiers_cache.clear()

        try:
            response = await remoting.fetch_identifiers(
                app=self.app,
                page=params["page"],
                page_size=params["page_size"],
                filter_term=params.get("filter_term"),
                order=params.get("order"),
                include_key_state=True,
            )
            self.table.set_page_data(response, data_key="identifiers")
        except Exception as e:
            logger.exception(f"Error loading identifiers: {e}")
            self.table.load_error.emit(str(e))

    @staticmethod
    def _on_load_error(error_msg: str):
        logger.error(f"Table load error: {error_msg}")

    def _on_add_identifier(self):
        if not self.app:
            return
        dialog = UploadIdentifierDialog(
            app=self.app,
            existing_identifiers=list(self._identifiers_cache.keys()),
            on_refresh=self._refresh_table,
            on_navigate_to_multisig_init=self.on_navigate_to_multisig_init,
            parent=self,
        )
        dialog.show()

    def _refresh_table(self):
        self.table.refresh()

    def _on_row_clicked(self, row_data: Any):
        if isinstance(row_data, dict):
            self._on_row_action({str(k): v for k, v in row_data.items()}, "View")

    def _on_row_action_signal(self, row_data: object, action: str):
        if isinstance(row_data, dict):
            self._on_row_action({str(k): v for k, v in row_data.items()}, action)

    def _on_row_action(self, row_data: dict[str, Any], action: str):
        if action == "View":
            self._view_identifier(row_data.get('_aid', ''))
        elif action == "Update":
            self._on_update_identifier(row_data)
        elif action == "Delete":
            self._on_delete_identifier(row_data)

    def _view_identifier(self, aid: str):
        identifier = self._identifiers_cache.get(aid)
        if not identifier:
            logger.error(f"Identifier {aid} not in cache")
            return
        dialog = ViewIdentifierDialog(app=self.app, identifier=identifier, parent=self)
        dialog.show()

    @qasync.asyncSlot(dict)
    async def _on_update_identifier(self, row_data: dict[str, Any]):
        aid = row_data.get('_aid', '')
        hab = self.app.vault.hby.habs.get(aid)
        identifier = self._identifiers_cache.get(aid)
        key_state = identifier.get('key_state') if identifier else None
        if not hab or not key_state:
            return
        dialog = ServerUpdateDialog(
            app=self.app,
            issuer_name=hab.name,
            issuer_aid=hab.pre,
            local_sn=int(hab.kever.state().s, 16),
            remote_sn=int(key_state.get('s', '0'), 16),
            revoked_credential=None,
            parent=self.parent(),
        )
        result = await _exec_dialog_async(dialog)
        if result == QDialog.DialogCode.Accepted:
            self._refresh_table()

    def _on_delete_identifier(self, row_data: dict[str, Any]):
        from .delete import DeleteIdentifierDialog

        aid = row_data.get('_aid', '')
        alias = row_data.get('Alias', '')
        if not aid:
            logger.error("Cannot delete: no AID found")
            return

        dialog = DeleteIdentifierDialog(
            app=self.app,
            alias=alias or aid[:12],
            aid=aid,
            on_success=self._on_identifier_deleted,
            parent=self,
        )
        dialog.open()

    def _on_identifier_deleted(self, aid: str):
        logger.info(f"Identifier {aid} deleted, reloading list")
        self._refresh_table()

    def set_vault_name(self, vault_name: str):
        self.vault_name = vault_name

    def on_show(self):
        self.table.request_load()
