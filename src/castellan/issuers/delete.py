# -*- encoding: utf-8 -*-
"""
castellan.issuers.delete module

Dialog for deleting a peer-discovery identifier from the Castellan server.
"""
from collections.abc import Callable
from typing import TYPE_CHECKING

import qasync
from keri import help
from locksmith.ui.toolkit.widgets.dialogs import LocksmithResourceDeletionDialog

from ..core import remoting

if TYPE_CHECKING:
    from locksmith.core.apping import LocksmithApplication
    from locksmith.ui.vault.page import VaultPage

logger = help.ogler.getLogger(__name__)


class DeleteIdentifierDialog(LocksmithResourceDeletionDialog):
    """Dialog for confirming and deleting an identifier from the Castellan server."""

    def __init__(
        self,
        app: "LocksmithApplication",
        alias: str,
        aid: str,
        on_success: Callable[[str], None] | None = None,
        parent: "VaultPage | None" = None,
    ):
        self.app = app
        self.alias = alias
        self.aid = aid
        self.on_success = on_success

        super().__init__(
            resource_type="issuer",
            resource_name=alias,
            title_icon=":/assets/material-icons/delete.svg",
            parent=parent,
        )

        self.delete_button.clicked.disconnect()
        self.delete_button.clicked.connect(self._do_delete)

    @qasync.asyncSlot()
    async def _do_delete(self):
        self.delete_button.setEnabled(False)
        self.delete_button.setText("Deleting...")
        self.cancel_button.setEnabled(False)

        try:
            result = await remoting.delete_identifier(self.app, self.aid)

            if not result.get('success'):
                error_msg = result.get('error', 'Unknown error occurred')
                self.show_error(f"Deletion failed: {error_msg}")
                self.delete_button.setEnabled(True)
                self.delete_button.setText("Delete")
                self.cancel_button.setEnabled(True)
                return

            logger.info(f"Identifier {self.aid} deleted from Castellan server")

            if self.on_success:
                self.on_success(self.aid)

            self.accept()

        except Exception as exc:
            logger.exception(f"DeleteIdentifierDialog: deletion failed: {exc}")
            self.show_error(f"Deletion failed: {exc}")
            self.delete_button.setEnabled(True)
            self.delete_button.setText("Delete")
            self.cancel_button.setEnabled(True)
