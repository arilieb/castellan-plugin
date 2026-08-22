# -*- encoding: utf-8 -*-
"""
castellan.schema.delete module

Dialog for deleting a schema from the Castellan server.
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


class DeleteSchemaDialog(LocksmithResourceDeletionDialog):
    """Dialog for confirming and deleting a schema from the Castellan server."""

    def __init__(
        self,
        app: "LocksmithApplication",
        schema_title: str,
        schema_said: str,
        on_success: Callable[[str], None] | None = None,
        parent: "VaultPage | None" = None,
    ):
        """Initialize the delete schema dialog.

        Args:
            app: The LocksmithApplication instance
            schema_title: Human-readable title of the schema
            schema_said: SAID of the schema
            on_success: Callback to invoke on successful deletion
            parent: Parent VaultPage
        """
        self.app = app
        self.schema_title = schema_title
        self.schema_said = schema_said
        self.on_success = on_success

        super().__init__(
            resource_type="schema",
            resource_name=schema_title,
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

        Removes the schema from the Castellan server.
        """
        # Disable buttons while processing
        self.delete_button.setEnabled(False)
        self.delete_button.setText("Deleting...")
        self.cancel_button.setEnabled(False)

        try:
            result = await remoting.delete_schema(self.app, self.schema_said)

            if not result.get('success'):
                error_msg = result.get('error', 'Unknown error')
                logger.error(f"Delete failed: {error_msg}")
                self.show_error(f"Deletion failed: {error_msg}")
                self.delete_button.setEnabled(True)
                self.delete_button.setText("Delete")
                self.cancel_button.setEnabled(True)
                return

            logger.info(f"Schema {self.schema_said} deleted from Castellan server")

            if self.on_success:
                self.on_success(self.schema_said)

            self.accept()

        except Exception as exc:
            logger.exception(f"DeleteSchemaDialog: deletion failed: {exc}")
            self.show_error(f"Deletion failed: {exc}")
            self.delete_button.setEnabled(True)
            self.delete_button.setText("Delete")
            self.cancel_button.setEnabled(True)
