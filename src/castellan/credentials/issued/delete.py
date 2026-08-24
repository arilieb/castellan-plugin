# -*- encoding: utf-8 -*-
"""Dialog for deleting an issued credential from the Castellan server."""

from collections.abc import Callable
from typing import TYPE_CHECKING

import qasync
from keri import help
from locksmith.ui.toolkit.widgets.dialogs import LocksmithResourceDeletionDialog

from ...core import remoting

if TYPE_CHECKING:
    from locksmith.core.apping import LocksmithApplication
    from locksmith.ui.vault.page import VaultPage

logger = help.ogler.getLogger(__name__)


class DeleteIssuedCredentialDialog(LocksmithResourceDeletionDialog):
    """Dialog for confirming and deleting an issued credential from the Castellan server."""

    def __init__(
        self,
        app: "LocksmithApplication",
        credential_name: str,
        credential_said: str,
        on_success: Callable[[str], None] | None = None,
        parent: "VaultPage | None" = None,
    ):
        """Initialize the delete issued credential dialog.

        Args:
            app: The LocksmithApplication instance
            credential_name: Human-readable name of the credential (e.g., schema title or SAID prefix)
            credential_said: SAID of the credential to delete
            on_success: Callback to invoke on successful deletion
            parent: Parent VaultPage
        """
        self.app = app
        self.credential_name = credential_name
        self.credential_said = credential_said
        self.on_success = on_success

        super().__init__(
            resource_type="issued credential",
            resource_name=credential_name,
            title_icon=":/assets/material-icons/delete.svg",
            parent=parent,
        )

        # Connect the delete button to our delete method
        self.delete_button.clicked.disconnect()
        self.delete_button.clicked.connect(self._do_delete)

    @qasync.asyncSlot()
    async def _do_delete(self):
        """
        Perform the async delete operation.

        Removes the issued credential from the Castellan server.
        """
        # Disable buttons while processing
        self.delete_button.setEnabled(False)
        self.delete_button.setText("Deleting...")
        self.cancel_button.setEnabled(False)

        try:
            result = await remoting.delete_issued_credential(self.app, self.credential_said)

            if not result.get('success'):
                error_msg = result.get('error', 'Unknown error occurred')
                self.show_error(f"Deletion failed: {error_msg}")
                self.delete_button.setEnabled(True)
                self.delete_button.setText("Delete")
                self.cancel_button.setEnabled(True)
                return

            logger.info(f"Issued credential {self.credential_said} deleted from Castellan server")

            if self.on_success:
                self.on_success(self.credential_said)

            self.accept()

        except Exception as exc:
            logger.exception(f"DeleteIssuedCredentialDialog: deletion failed: {exc}")
            self.show_error(f"Deletion failed: {exc}")
            self.delete_button.setEnabled(True)
            self.delete_button.setText("Delete")
            self.cancel_button.setEnabled(True)
