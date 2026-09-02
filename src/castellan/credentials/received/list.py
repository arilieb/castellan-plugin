# -*- encoding: utf-8 -*-
"""
castellan.credentials.received.list module

Received credentials list page — shows received credentials stored on the Castellan server.
"""
from typing import Any, TYPE_CHECKING

import qasync
from PySide6.QtGui import QPalette, QColor
from PySide6.QtWidgets import QWidget, QVBoxLayout
from keri import help
from keri.app import connecting
from keri.core import coring
from keri.help import helping
from locksmith.ui import colors
from locksmith.ui.toolkit.tables import PaginatedTableWidget

from .delete import DeleteReceivedCredentialDialog
from .edit import EditReceivedCredentialDialog
from .upload import UploadReceivedCredentialsDialog
from .view import ViewReceivedCredentialDialog
from ...core import remoting

if TYPE_CHECKING:
    from locksmith.ui.vault.page import VaultPage

logger = help.ogler.getLogger(__name__)


class ReceivedCredentialsListPage(QWidget):
    """Paginated list of received credentials stored on the Castellan server."""

    def __init__(self, app, parent: "VaultPage | None" = None):
        super().__init__(parent)
        self._parent = parent
        self.app = app
        self.vault_name = ""
        self._credentials_cache: dict[str, dict[str, Any]] = {}
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
            columns=["Schema", "Issuer", "Status (Local)", "Received Date"],
            column_widths={"Schema": 220, "Status (Local)": 125, "Received Date": 165, "Actions": 50},
            title="Received Credentials",
            icon_path=":/assets/material-icons/in-badge.svg",
            show_add_button=True,
            add_button_text="Upload Credential(s)",
            row_actions=["View", "Edit", "Delete"],
            row_action_icons={
                "View": ":/assets/material-icons/view.svg",
                "Edit": ":/assets/material-icons/edit.svg",
                "Delete": ":/assets/material-icons/delete.svg",
            },
            items_per_page=10,
            show_search=True,
            column_sort_mapping={
                "Schema": "schema",
                "Issuer": "issuer",
                "Status": "status",
                "Received Date": "created_at",
            },
            transform_func=self._transform_credential_to_row,
            parent=self,
        )

        self.table.add_clicked.connect(self._on_upload_credentials)
        self.table.row_action_triggered.connect(self._on_row_action_signal)
        self.table.row_clicked.connect(self._on_row_clicked)
        self.table.load_requested.connect(self._on_load_requested)
        self.table.load_error.connect(self._on_load_error)

        layout.addWidget(self.table)

    def _transform_credential_to_row(self, credential: dict[str, Any]) -> dict[str, Any]:
        org = connecting.Organizer(hby=self.app.vault.hby)

        sad = credential.get('sad', '')
        said = credential.get('said', '')
        schema_title = credential.get('schema_title')
        created_at = helping.fromIso8601(credential.get('created_at', '')).strftime("%b %d, %Y %I:%M %p")

        issr = credential.get('issuer', '')
        issuer_name = f'Unknown ({issr})'
        if (issuer_hab := self.app.vault.hby.habByPre(issr)) is not None:
            issuer_name = f'{issuer_hab.name} ({issr})'
        elif (remote_id := org.get(issr)) is not None:
            issuer_name = f'{remote_id['alias']} ({issr})'

        remote_status = credential.get('status', '').capitalize()
        local_status = self._local_credential_status(self.app, said, sad)

        is_out_of_sync = local_status is not None and local_status != remote_status
        status_text = f"{remote_status} ({local_status})" if local_status is not None else remote_status
        status_color = colors.DANGER if is_out_of_sync else colors.SUCCESS_INDICATOR

        row_data = {
            'Schema': schema_title,
            'Issuer': issuer_name,
            'Status (Local)': status_text,
            'Status (Local)_color': status_color,
            'Received Date': created_at,
            '_said': said,
            '_out_of_sync': is_out_of_sync,
            '_local_status': local_status.lower() if local_status is not None else None,
        }

        if is_out_of_sync:
            tooltip = (
                f"Castellan server reports this credential as '{remote_status}', "
                f"but it is '{local_status}' locally. Use 'Update' to sync the server."
            )
            for col in ("Schema", "Recipient", "Status (Local)", "Issued Date"):
                row_data[f"{col}_tooltip"] = tooltip

        self._credentials_cache[said] = credential
        return row_data

    @staticmethod
    def _local_credential_status(app, said: str, sad) -> str | None:
        """Determine local TEL status ('Issued'/'Revoked') for a credential, or None if unknown locally."""
        try:
            regk = sad.get('ri')
            vc_state = app.rgy.tevers[regk].vcState(said)
            return "Revoked" if vc_state.et in [coring.Ilks.rev, coring.Ilks.brv] else "Issued"
        except Exception as e:
            logger.debug(f"Could not determine local TEL state for {said}: {e}")
            return None

    @qasync.asyncSlot(dict)
    async def _on_load_requested(self, params: dict):
        if not self.app:
            self.table.load_error.emit("No app instance available")
            return

        self._credentials_cache.clear()

        try:
            response = await remoting.fetch_received_credentials(
                app=self.app,
                page=params["page"],
                page_size=params["page_size"],
                filter_term=params.get("filter_term"),
                order=params.get("order"),
            )
            self.table.set_page_data(response, data_key="credentials")
        except Exception as e:
            logger.exception(f"Error loading received credentials: {e}")
            self.table.load_error.emit(str(e))

    @staticmethod
    def _on_load_error(error_msg: str):
        logger.error(f"Table load error: {error_msg}")

    def _on_upload_credentials(self):
        if not self.app:
            return
        dialog = UploadReceivedCredentialsDialog(
            app=self.app,
            on_refresh=self._refresh_table,
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
        said = row_data.get('_said', '')
        if action == "View":
            self._view_credential(said)
        elif action == "Edit":
            self._edit_credential(said)
        elif action == "Delete":
            self._confirm_delete_credential(said)

    def _view_credential(self, said: str):
        credential = self._credentials_cache.get(said)
        if not credential:
            logger.error(f"Credential {said} not in cache")
            return
        dialog = ViewReceivedCredentialDialog(app=self.app, credential=credential, parent=self)
        dialog.show()

    def _edit_credential(self, said: str):
        """Handle Edit credential action."""
        credential = self._credentials_cache.get(said)
        if not credential:
            logger.error(f"Credential {said} not in cache")
            return
        dialog = EditReceivedCredentialDialog(
            app=self.app,
            credential=credential,
            on_success=self._refresh_table,
            parent=self
        )
        dialog.show()

    def _confirm_delete_credential(self, said: str):
        """Handle Delete credential action."""
        credential = self._credentials_cache.get(said)
        if not credential:
            logger.error(f"Credential {said} not in cache")
            return

        schema = credential.get('schema', {})
        schema_title = schema.get('title', '')
        credential_name = schema_title if schema_title else said[:12]

        dialog = DeleteReceivedCredentialDialog(
            app=self.app,
            credential_name=credential_name,
            credential_said=said,
            on_success=self._on_credential_deleted,
            parent=self
        )
        dialog.open()

    def _on_credential_deleted(self, credential_said: str):
        """Handle successful credential deletion."""
        logger.info(f"Credential {credential_said} deleted, reloading list")
        self._refresh_table()

    def set_vault_name(self, vault_name: str):
        self.vault_name = vault_name

    def on_show(self):
        self._credentials_cache.clear()
        self.table.request_load()
