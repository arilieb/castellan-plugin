# -*- encoding: utf-8 -*-
"""
castellan.credentials.issued.list module

Issued credentials list page — shows issued credentials stored on the Castellan server.
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

from .upload import UploadIssuedCredentialsDialog
from .view import ViewIssuedCredentialDialog
from ...core import remoting

if TYPE_CHECKING:
    from locksmith.ui.vault.page import VaultPage

logger = help.ogler.getLogger(__name__)


class IssuedCredentialsListPage(QWidget):
    """Paginated list of issued credentials stored on the Castellan server."""

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
            columns=["Schema", "Recipient", "Status (Local)", "Issued Date"],
            column_widths={"Schema": 220, "Status (Local)": 125, "Issued Date": 165, "Actions": 50},
            title="Issued Credentials",
            icon_path=":/assets/material-icons/out-badge.svg",
            show_add_button=True,
            add_button_text="Upload Credential",
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
                "Recipient": "recipient",
                "Status (Local)": "status",
                "Issued Date": "created_at",
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

        said = credential.get('said', '')
        sad = credential.get('sad', '')
        schema_title = credential.get('schema_title')

        created_at = helping.fromIso8601(credential.get('created_at', '')).strftime("%b %d, %Y %I:%M %p")

        recp = credential.get('recipient', '')
        recipient_name = f'Unknown ({recp})'
        if (recipient_hab := self.app.vault.hby.habByPre(recp)) is not None:
            recipient_name = f'{recipient_hab.name} ({recp})'
        elif (remote_id := org.get(recp)) is not None:
            recipient_name = f'{remote_id['alias']} ({recp})'

        remote_status = credential.get('status', '').capitalize()

        regk = sad.get('ri')
        status = self.app.rgy.tevers[regk].vcState(said)

        if status.et in [coring.Ilks.rev, coring.Ilks.brv]:
            if remote_status == "Issued":
                status_text = "Issued (Revoked)"
                status_color = colors.DANGER
            else:
                status_text = "Revoked (Revoked)"
                status_color = colors.TEXT_PRIMARY
        else:
            if remote_status == "Issued":
                status_text = "Issued (Issued)"
                status_color = colors.TEXT_PRIMARY
            else:
                status_text = "Revoked (Issued)"
                status_color = colors.DANGER

        row_data = {
            'Schema': schema_title,
            'Recipient': recipient_name,
            'Status (Local)': status_text,
            'Status (Local)_color': status_color,
            'Issued Date': created_at,
            '_said': said,
        }

        self._credentials_cache[said] = credential
        return row_data

    @qasync.asyncSlot(dict)
    async def _on_load_requested(self, params: dict):
        if not self.app:
            self.table.load_error.emit("No app instance available")
            return

        self._credentials_cache.clear()

        try:
            response = await remoting.fetch_issued_credentials(
                app=self.app,
                page=params["page"],
                page_size=params["page_size"],
                filter_term=params.get("filter_term"),
                order=params.get("order"),
            )
            self.table.set_page_data(response, data_key="credentials")
        except Exception as e:
            logger.exception(f"Error loading issued credentials: {e}")
            self.table.load_error.emit(str(e))

    @staticmethod
    def _on_load_error(error_msg: str):
        logger.error(f"Table load error: {error_msg}")

    def _on_upload_credentials(self):
        if not self.app:
            return
        dialog = UploadIssuedCredentialsDialog(
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
            self._on_delete_credential(row_data)

    def _view_credential(self, said: str):
        credential = self._credentials_cache.get(said)
        if not credential:
            logger.error(f"Credential {said} not in cache")
            return
        dialog = ViewIssuedCredentialDialog(app=self.app, credential=credential, parent=self)
        dialog.show()

    def _edit_credential(self, said: str):
        """Open edit dialog for a credential's dynamic fields."""
        from .edit import EditIssuedCredentialDialog

        credential = self._credentials_cache.get(said)
        if not credential:
            logger.error(f"Credential {said} not in cache")
            return

        dialog = EditIssuedCredentialDialog(
            app=self.app,
            credential=credential,
            on_success=self._on_credential_edited,
            parent=self,
        )
        dialog.show()

    def _on_credential_edited(self):
        """Callback after successful credential edit."""
        self._refresh_table()

    def _on_delete_credential(self, row_data: dict[str, Any]):
        """Handle Delete credential action."""
        from .delete import DeleteIssuedCredentialDialog

        credential_said = row_data.get('_said', '')
        schema_title = row_data.get('Schema', '')

        if not credential_said:
            logger.error("Cannot delete: no credential SAID found")
            return

        # Use schema title as credential name, fallback to SAID prefix if missing
        credential_name = schema_title if schema_title else credential_said[:12]

        logger.info(f"Opening delete dialog for credential: {credential_name}")

        dialog = DeleteIssuedCredentialDialog(
            app=self.app,
            credential_name=credential_name,
            credential_said=credential_said,
            on_success=self._on_credential_deleted,
            parent=self._parent
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
        self._check_issuer_keystate()

    @qasync.asyncSlot()
    async def _check_issuer_keystate(self):
        """Check if any issuer identifiers have outdated key state on the Castellan server."""
        if not self.app or not self.app.vault or not self.app.vault.hby:
            return

        try:
            issuers = []

            for (said,), schemer in self.app.vault.hby.db.schema.getItemIter():
                # Determine issuer name
                registry = self.app.vault.rgy.registryByName(said)
                if registry:
                    try:
                        # Get the issuer prefix from the registry
                        issuer_pre = registry.hab.pre
                        # Get the hab for this issuer
                        hab = self.app.vault.hby.habs.get(issuer_pre)
                        if hab:
                            issuers.append((hab.pre, hab))
                    except Exception as e:
                        logger.warning(f"Error getting issuer for schema {said}: {e}")
                        continue

            for (hab_pre, hab) in issuers:
                # Get local key state
                local_state = hab.kever.state()
                local_sn = int(local_state.s, 16)  # Sequence number

                # Fetch remote key state from Castellan server
                result = await remoting.fetch_identifier_keystate(
                    app=self.app,
                    identifier_prefix=hab_pre,
                )

                if not result.get('success'):
                    # If identifier not found on server, that's okay - skip it
                    logger.debug(f"Could not fetch key state for {hab.name}: {result.get('error', 'Unknown error')}")
                    return

                remote_data = result.get('data', {})
                if remote_data is None:
                    remote_sn = -1
                else:
                    remote_sn = int(remote_data.get('key_state', {}).get('s', 0), 16)

                # Check if remote is behind local
                if remote_sn < local_sn:
                    logger.warning(
                        f"Key state mismatch for '{hab.name}': "
                        f"local_sn={local_sn}, remote_sn={remote_sn}"
                    )

                    # Show dialog to prompt user
                    from .keystate_update import KeyStateUpdateDialog

                    dialog = KeyStateUpdateDialog(
                        app=self.app,
                        issuer_name=hab.name,
                        issuer_aid=hab.pre,
                        local_sn=local_sn,
                        remote_sn=remote_sn,
                        parent=self._parent,
                    )
                    dialog.open()

        except Exception as e:
            logger.exception(f"Error checking issuer key state: {e}")
