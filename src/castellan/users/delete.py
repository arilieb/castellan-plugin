# -*- encoding: utf-8 -*-
"""
castellan.users.delete module

Dialog for deleting a user account from the Castellan server.
"""
from typing import TYPE_CHECKING, Callable

import qasync
from keri import help
from locksmith.ui.toolkit.widgets.dialogs import LocksmithResourceDeletionDialog

from ..core import remoting

if TYPE_CHECKING:
    from locksmith.core.apping import LocksmithApplication
    from locksmith.ui.vault.page import VaultPage

logger = help.ogler.getLogger(__name__)


class DeleteUserDialog(LocksmithResourceDeletionDialog):
    """Dialog for confirming and executing user account deletion."""

    def __init__(
        self,
        app: "LocksmithApplication",
        user_name: str,
        user_id: str,
        on_success: Callable[[str], None] | None = None,
        parent: "VaultPage | None" = None,
    ):
        self.app = app
        self.user_id = user_id
        self.on_success = on_success

        super().__init__(
            resource_type="user",
            resource_name=user_name,
            title_icon=":/assets/material-icons/delete.svg",
            parent=parent,
        )

        # Reconnect delete button to our async handler
        self.delete_button.clicked.disconnect()
        self.delete_button.clicked.connect(self._do_delete)

    @qasync.asyncSlot()
    async def _do_delete(self):
        """Execute the delete operation."""
        self.delete_button.setEnabled(False)
        self.delete_button.setText("Deleting...")
        self.cancel_button.setEnabled(False)

        try:
            result = await remoting.delete_account(self.app, self.user_id)

            if not result.get('success'):
                error_msg = result.get('error', 'Unknown error')
                self.show_error(f"Failed to delete user: {error_msg}")
                return

            # Success
            if self.on_success:
                self.on_success(self.user_id)

            self.accept()

        except Exception as exc:
            logger.exception(f"Error deleting user: {exc}")
            self.show_error(f"Error: {str(exc)}")

        finally:
            self.delete_button.setEnabled(True)
            self.delete_button.setText("Delete")
            self.cancel_button.setEnabled(True)
