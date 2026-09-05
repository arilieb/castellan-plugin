# -*- encoding: utf-8 -*-
"""
castellan.credentials.issued.list module

Issued credentials list page — shows issued credentials stored on the Castellan server.
"""
import asyncio
from typing import Any, TYPE_CHECKING

import qasync
from PySide6.QtGui import QPalette, QColor
from PySide6.QtWidgets import QWidget, QVBoxLayout, QMessageBox, QDialog
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


async def _exec_dialog_async(dialog: QDialog) -> int:
    """
    Await a dialog's completion without blocking the event loop.

    Unlike QDialog.exec(), which blocks via a nested native event loop and
    conflicts with asyncio's task re-entrancy guard when the dialog's own
    slots are qasync coroutines, this suspends via a real `await` so the
    calling task is fully off the stack while the dialog is open.
    """
    future = asyncio.get_event_loop().create_future()
    dialog.finished.connect(lambda result: not future.done() and future.set_result(result))
    dialog.open()
    return await future


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
            row_actions=["View", "Edit", "Revoke", "Update", "Delete"],
            row_action_icons={
                "View": ":/assets/material-icons/view.svg",
                "Edit": ":/assets/material-icons/edit.svg",
                "Revoke": ":/assets/material-icons/remove_moderator.svg",
                "Update": ":/assets/material-icons/cloud_sync.svg",
                "Delete": ":/assets/material-icons/delete.svg",
            },
            row_actions_callback=self._get_row_actions,
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
        local_status = self._local_credential_status(self.app, said, sad)

        is_out_of_sync = local_status is not None and local_status != remote_status
        status_text = f"{remote_status} ({local_status})" if local_status is not None else remote_status
        status_color = colors.DANGER if is_out_of_sync else colors.SUCCESS_INDICATOR

        row_data = {
            'Schema': schema_title,
            'Recipient': recipient_name,
            'Status (Local)': status_text,
            'Status (Local)_color': status_color,
            'Issued Date': created_at,
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

    def _get_row_actions(self, row_data: dict[str, Any]) -> tuple[list[str], dict[str, str]]:
        all_icons = {
            "View": ":/assets/material-icons/view.svg",
            "Edit": ":/assets/material-icons/edit.svg",
            "Revoke": ":/assets/material-icons/remove_moderator.svg",
            "Update": ":/assets/material-icons/cloud_sync.svg",
            "Delete": ":/assets/material-icons/delete.svg",
        }
        actions = ["View", "Edit"]
        if row_data.get('_local_status') == 'issued':
            actions.append("Revoke")
        if row_data.get('_out_of_sync'):
            actions.append("Update")
        actions.append("Delete")
        return actions, {a: all_icons[a] for a in actions}

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
        elif action == "Revoke":
            self._on_revoke_credential(row_data)
        elif action == "Update":
            self._push_status_update(row_data)
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

    @qasync.asyncSlot(dict)
    async def _push_status_update(self, row_data: dict[str, Any]):
        """Push the locally-known status to the Castellan server."""
        said = row_data.get('_said', '')
        local_status = row_data.get('_local_status')
        if not said or not local_status:
            return

        result = await remoting.update_issued_credential_status(self.app, said, local_status)
        if not result.get('success'):
            QMessageBox.critical(self, "Update Failed", result.get('error', 'Unknown error'))
            return

        self._refresh_table()

    def _on_revoke_credential(self, row_data: dict[str, Any]):
        """Handle Revoke credential action."""
        from .revoke import RevokeIssuedCredentialDialog

        said = row_data.get('_said', '')
        schema_title = row_data.get('Schema', '')

        if not said:
            logger.error("Cannot revoke: no credential SAID found")
            return

        dialog = RevokeIssuedCredentialDialog(
            app=self.app,
            schema_name=schema_title,
            said=said,
            on_success=self._on_credential_revoked,
            parent=self.parent(),
        )
        dialog.open()

    def _on_credential_revoked(self, credential_said: str):
        """Handle successful credential revocation."""
        logger.info(f"Credential {credential_said} revoked, reloading list")
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
        self._check_server_sync()

    @qasync.asyncSlot()
    async def _check_server_sync(self):
        """
        Check for local state the Castellan server doesn't know about yet.

        Revoked-credential mismatches are checked first, since revoking a
        credential locally anchors a new event into the issuer's KEL - meaning
        the accompanying key state check is already handled by the same dialog.
        The separate pure-keystate check only runs if no revocations were found.
        """
        try:
            found_revocations = await self._check_revoked_credentials()
            if found_revocations:
                return
            await self._check_issuer_keystate()
        except Exception as e:
            logger.exception(f"Error checking server sync state: {e}")

    async def _check_revoked_credentials(self) -> bool:
        """
        Scan all issued credentials for local revocations not yet reflected on
        the Castellan server, opening one ServerUpdateDialog per mismatch found.

        Returns:
            True if at least one mismatch was found (and a dialog opened).
        """
        if not self.app or not self.app.vault or not self.app.vault.hby:
            return False

        response = await remoting.fetch_issued_credentials(app=self.app, page=0, page_size=10000)
        if not response.get('success'):
            logger.debug(f"Could not fetch issued credentials for revocation check: {response.get('error')}")
            return False

        from .server_update import ServerUpdateDialog

        found = False
        for credential in response.get('credentials', []):
            said = credential.get('said', '')
            sad = credential.get('sad', '')
            remote_status = credential.get('status', '').capitalize()
            local_status = self._local_credential_status(self.app, said, sad)

            if local_status != "Revoked" or remote_status == "Revoked":
                continue

            issuer_pre = credential.get('issuer', '')
            hab = self.app.vault.hby.habs.get(issuer_pre)
            if not hab:
                logger.warning(f"Could not find local hab for issuer {issuer_pre}; skipping revocation sync for {said}")
                continue

            local_state = hab.kever.state()
            local_sn = int(local_state.s, 16)

            keystate_result = await remoting.fetch_identifier_keystate(app=self.app, identifier_prefix=issuer_pre)
            remote_data = keystate_result.get('data') if keystate_result.get('success') else None
            remote_sn = int(remote_data.get('key_state', {}).get('s', 0), 16) if remote_data else -1

            dialog = ServerUpdateDialog(
                app=self.app,
                issuer_name=hab.name,
                issuer_aid=hab.pre,
                local_sn=local_sn,
                remote_sn=remote_sn,
                revoked_credential={'said': said, 'schema_title': credential.get('schema_title')},
                parent=self.parent(),
            )
            result = await _exec_dialog_async(dialog)
            found = True
            if result == QDialog.DialogCode.Accepted:
                self._refresh_table()

        return found

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
                    continue

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
                    from .server_update import ServerUpdateDialog

                    dialog = ServerUpdateDialog(
                        app=self.app,
                        issuer_name=hab.name,
                        issuer_aid=hab.pre,
                        local_sn=local_sn,
                        remote_sn=remote_sn,
                        parent=self.parent(),
                    )
                    result = await _exec_dialog_async(dialog)
                    if result == QDialog.DialogCode.Accepted:
                        self._refresh_table()

        except Exception as e:
            logger.exception(f"Error checking issuer key state: {e}")
