# -*- encoding: utf-8 -*-
"""
castellan.credentials.issued.revoke module

Dialog for confirming and revoking an issued credential, and automatically
syncing the revocation (and any resulting key state change) to the Castellan
server once the local TEL revocation completes.
"""
import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING

from keri import help
from locksmith.core.credentialing import RevokeCredentialDoer
from locksmith.ui.toolkit.widgets.dialogs import LocksmithResourceDeletionDialog
from locksmith.ui.vault.identifiers.authenticate import WitnessAuthenticationDialog
from PySide6.QtWidgets import QLabel

from ...core import remoting

if TYPE_CHECKING:
    from locksmith.core.apping import LocksmithApplication
    from locksmith.ui.vault.page import VaultPage

logger = help.ogler.getLogger(__name__)


class RevokeIssuedCredentialDialog(LocksmithResourceDeletionDialog):
    """Dialog for confirming and revoking an issued credential.

    Once the local TEL revocation completes, the revocation status (and any
    resulting key state advancement) is automatically pushed to the
    Castellan server - the user is not routed through a separate
    confirmation dialog for that step.
    """

    def __init__(
        self,
        app: "LocksmithApplication",
        schema_name: str,
        said: str,
        on_success: Callable[[str], None] | None = None,
        parent: "VaultPage | None" = None,
    ):
        """Initialize the RevokeIssuedCredentialDialog.

        Args:
            app: The LocksmithApplication instance
            schema_name: Name/title of the credential schema (for confirmation)
            said: SAID of the credential to revoke
            on_success: Callback to invoke once the revocation has been synced
                to (or the sync has failed against) the Castellan server
            parent: Parent widget (VaultPage container)
        """
        self.app = app
        self.schema_name = schema_name
        self.said = said
        self.on_success = on_success
        self._awaiting_auth = False  # Guard: only handle auth_codes_entered when we initiated auth
        self.issuer_pre: str | None = None
        self.issuer_name: str | None = None

        super().__init__(
            parent=parent,
            resource_type="issued credential",
            resource_name=schema_name if schema_name else said,
            title_icon=":/assets/material-icons/remove_moderator.svg",
            action_verb="Revoke",
        )

        note = QLabel(
            "Revoking this credential will automatically update its status "
            "on the Castellan server."
        )
        note.setWordWrap(True)
        note.setStyleSheet("font-size: 12px; color: #6b7280;")
        self.content_layout.addWidget(note)

        # Override the revoke button click to handle credential revocation
        self.delete_button.clicked.disconnect(self.accept)
        self.delete_button.clicked.connect(self._on_revoke)

        # Connect to vault signal bridge for doer events
        if hasattr(self.app.vault, 'signals'):
            self.app.vault.signals.doer_event.connect(self._on_doer_event)
            self.app.vault.signals.auth_codes_entered.connect(self._on_auth_codes_entered)

        logger.info(f"RevokeIssuedCredentialDialog initialized for '{schema_name}' ({said})")

    def _on_revoke(self):
        """Handle the revoke button click, launching witness auth first if needed."""
        self.clear_error()
        self.delete_button.setEnabled(False)
        self.delete_button.setText("Revoking...")

        try:
            creder = self.app.vault.rgy.reger.creds.get(keys=(self.said,))
            if not creder:
                raise Exception(f"Credential {self.said} not found")

            registry = self.app.vault.rgy.regs[creder.regi]
            hab = registry.hab
            self.issuer_pre = hab.pre
            self.issuer_name = hab.name

            if hab.kever.wits:
                self._awaiting_auth = True
                auth_dialog = WitnessAuthenticationDialog(
                    app=self.app,
                    hab=hab,
                    witness_ids=hab.kever.wits,
                    auth_only=True,
                    signals=self.app.vault.signals,
                    parent=self.parent(),
                )
                auth_dialog.open()
            else:
                self._complete_revocation(codes=None)

        except Exception as e:
            error_msg = f"Failed to revoke credential: {str(e)}"
            logger.exception(error_msg)
            self._reset_revoke_button()
            self.show_error(error_msg)

    def _on_auth_codes_entered(self, data: dict):
        """
        Handle auth codes entered from WitnessAuthenticationDialog.

        Args:
            data: Dictionary containing 'codes' key with list of "witness_id:passcode" strings
        """
        if not self._awaiting_auth:
            return
        self._awaiting_auth = False

        codes = data.get('codes', [])
        logger.info(f"Received {len(codes)} auth codes from WitnessAuthenticationDialog")

        self._complete_revocation(codes=codes)

    def _complete_revocation(self, codes=None):
        """Start the RevokeCredentialDoer to perform the actual revocation."""
        logger.info(f"Revoking issued credential '{self.schema_name}' ({self.said})")

        try:
            doer = RevokeCredentialDoer(
                app=self.app,
                credential_said=self.said,
                codes=codes,
                signal_bridge=self.app.vault.signals if hasattr(self.app.vault, 'signals') else None
            )
            self.app.vault.extend([doer])

            logger.info(f"RevokeCredentialDoer started for credential {self.said}")

        except Exception as e:
            logger.exception(f"Error creating RevokeCredentialDoer: {e}")
            self._reset_revoke_button()
            self.show_error(f"Failed to start credential revocation: {str(e)}")

    def _on_doer_event(self, doer_name: str, event_type: str, data: dict):
        """
        Handle doer events from the signal bridge.

        Args:
            doer_name: Name of the doer that emitted the event
            event_type: Type of event
            data: Event data dictionary
        """
        if doer_name != "RevokeCredentialDoer" or data.get('credential_said') != self.said:
            return

        logger.debug(f"RevokeIssuedCredentialDialog received doer_event: {doer_name} - {event_type}")

        if event_type == "credential_revoked":
            logger.info(f"Credential revoked successfully: {self.said}")
            self.delete_button.setText("Syncing with server...")
            asyncio.ensure_future(self._sync_to_castellan())

        elif event_type == "credential_revocation_failed":
            error_msg = data.get('error', 'Unknown error')
            logger.error(f"Credential revocation failed: {error_msg}")
            self._reset_revoke_button()
            self.show_error(f"Failed to revoke credential: {error_msg}")

    async def _sync_to_castellan(self):
        """
        Push the revoked status (and any key state change) to the Castellan server.

        `on_success` is fired exactly once, after this sync attempt finishes
        (successfully or not) - not as soon as the local revocation lands -
        so that a caller refreshing a list row sees the post-sync state
        instead of having to refresh again manually.
        """
        try:
            result = await remoting.update_issued_credential_status(
                app=self.app,
                credential_said=self.said,
                status="revoked",
            )
            if not result.get('success'):
                self._set_revoke_button_final("Revoked locally")
                self.show_error(
                    f"Credential revoked locally, but failed to update the Castellan "
                    f"server: {result.get('error', 'Unknown error')}. It will be "
                    f"flagged as out of sync until retried."
                )
                return

            hab = self.app.vault.hby.habs.get(self.issuer_pre) if self.issuer_pre else None
            if hab:
                local_sn = int(hab.kever.state().s, 16)
                keystate_result = await remoting.fetch_identifier_keystate(
                    app=self.app,
                    identifier_prefix=self.issuer_pre,
                )
                remote_data = keystate_result.get('data') if keystate_result.get('success') else None
                remote_sn = int(remote_data.get('key_state', {}).get('s', 0), 16) if remote_data else -1

                if remote_sn < local_sn:
                    result = await remoting.upload_account_identifier(
                        app=self.app,
                        aid=self.issuer_pre,
                        alias=self.issuer_name,
                    )
                    if not result.get('success'):
                        self._set_revoke_button_final("Revoked locally")
                        self.show_error(
                            f"Credential status synced, but failed to update key "
                            f"state: {result.get('error', 'Unknown error')}"
                        )
                        return

            self._set_revoke_button_final("Revoked")
            self.show_success(f"'{self.schema_name}' revoked and synced to the Castellan server!")

        except Exception as e:
            logger.exception(f"Error syncing revocation to Castellan server: {e}")
            self._set_revoke_button_final("Revoked locally")
            self.show_error(f"Credential revoked locally, but server sync failed: {e}")

        finally:
            if self.on_success:
                self.on_success(self.said)

    def _reset_revoke_button(self):
        """Re-enable the revoke button and restore its label (revocation was not performed)."""
        self.delete_button.setEnabled(True)
        self.delete_button.setText("Revoke")

    def _set_revoke_button_final(self, text: str):
        """Set the revoke button's final label once local revocation has completed.

        The button stays disabled, since the credential has already been revoked
        and re-triggering RevokeCredentialDoer against it would fail.
        """
        self.delete_button.setEnabled(False)
        self.delete_button.setText(text)
