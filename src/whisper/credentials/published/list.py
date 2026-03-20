# -*- encoding: utf-8 -*-
"""
locksmith.ui.vault.healthKERI.credentials.published.list module

Published credentials list page for healthKERI with server-side pagination.
"""
from typing import Any, TYPE_CHECKING

import qasync
from PySide6.QtWidgets import QWidget, QVBoxLayout
from keri import help
from keri.help import helping

from ...core import remoting
from locksmith.ui import colors
from locksmith.ui.toolkit.tables import PaginatedTableWidget
from ...credentials.published.publish import PublishCredentialDialog

if TYPE_CHECKING:
    from locksmith.ui.vault.page import VaultPage

logger = help.ogler.getLogger(__name__)


class PublishedCredentialsListPage(QWidget):
    """Published credentials list page for healthKERI.

    Shows credentials published to healthKERI.net with:
    - Server-side pagination (loads one page at a time)
    - Schema, Recipient, Status, and Issued Date columns
    """

    def __init__(self, app, parent: "VaultPage | None" = None):
        """
        Initialize the PublishedCredentialsListPage.

        Args:
            app: Application instance
            parent: Parent widget (optional)
        """
        super().__init__(parent)
        self._parent = parent
        self.app = app
        self.vault_name = ""

        # Cache for current page's credentials (for row action lookups)
        self._credentials_cache: dict[str, dict[str, Any]] = {}

        self._setup_ui()

    def _setup_ui(self):
        """Set up the page UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        columns = ["Schema", "Recipient", "Status", "Issued Date"]
        row_actions = ["View", "Send", "Revoke", "Export"]
        row_action_icons = {
            "View": ":/assets/material-icons/view.svg",
            "Send": ":/assets/material-icons/send.svg",
            "Revoke": ":/assets/material-icons/delete.svg",
            "Export": ":/assets/material-icons/export.svg"
        }

        # Set background using palette
        from PySide6.QtGui import QPalette, QColor
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(colors.BACKGROUND_CONTENT))
        self.setPalette(palette)
        self.setAutoFillBackground(True)

        # Create the table with async API loading configuration
        self.table = PaginatedTableWidget(
            columns=columns,
            column_widths={"Schema": 220, "Status": 110, "Issued Date": 165, "Actions": 50},
            title="Published Credentials",
            icon_path=":/assets/material-icons/out-badge.svg",
            show_add_button=True,
            add_button_text="Publish Credential",
            row_actions=row_actions,
            row_action_icons=row_action_icons,
            items_per_page=10,
            show_search=True,
            # Async loading configuration
            column_sort_mapping={
                "Schema": "schema",
                "Recipient": "recipient",
                "Status": "status",
                "Issued Date": "issued_date",
            },
            transform_func=self._transform_credential_to_row,
            parent=self
        )

        # Connect table signals
        self.table.add_clicked.connect(self._on_publish_credential)
        self.table.row_action_triggered.connect(self._on_row_action_signal)
        self.table.row_clicked.connect(self._on_row_clicked)

        # Connect async loading signals
        self.table.load_requested.connect(self._on_load_requested)
        self.table.load_error.connect(self._on_load_error)

        layout.addWidget(self.table)

    def _transform_credential_to_row(self, credential: dict[str, Any]) -> dict[str, Any]:
        """
        Transform an API credential response to a table row.

        Args:
            credential: Credential data from API

        Returns:
            Row data dict for table
        """
        said = credential.get('said', '')
        schema = credential.get('schema', {})
        sad = credential.get('sad', {})
        attribs = sad.get('a', {})
        recipient = sad.get('i', '')
        dt = helping.fromIso8601(attribs['dt'])

        row_data = {
            'Schema': schema.get('title', ''),
            'Recipient': recipient,
            'Status': credential.get('status', '').capitalize(),
            'Issued Date': dt.strftime("%b %d, %Y %I:%M %p"),
            # Store SAID for row action lookups
            '_said': said,
        }

        # Cache the full credential for row actions
        self._credentials_cache[said] = credential

        return row_data

    @qasync.asyncSlot(dict)
    async def _on_load_requested(self, params: dict):
        """
        Handle load_requested signal from table.

        Fetches data from API and updates table.

        Args:
            params: {"page": int, "page_size": int, "filter_term": str|None, "order": list|None}
        """
        if not self.app:
            logger.error("No app instance available")
            self.table.load_error.emit("No app instance available")
            return

        # Clear cache before loading new page
        self._credentials_cache.clear()

        logger.debug(f"Loading published credentials: {params}")

        try:
            response = await remoting.fetch_published_credentials(
                app=self.app,
                page=params["page"],
                page_size=params["page_size"],
                filter_term=params.get("filter_term"),
                order=params.get("order")
            )

            # Pass response to table (handles success/error internally)
            self.table.set_page_data(response, data_key="credentials")

        except Exception as e:
            logger.exception(f"Error loading published credentials: {e}")
            self.table.load_error.emit(str(e))

    @staticmethod
    def _on_load_error(error_msg: str):
        """Handle load error from table."""
        logger.error(f"Table load error: {error_msg}")
        # Could show a toast/notification here if desired

    def _on_publish_credential(self):
        """Handle publish credential button click."""
        if not self.app:
            logger.warning("No app instance available for publish dialog")
            return

        dialog = PublishCredentialDialog(
            app=self.app,
            existing_credentials=list(self._credentials_cache.keys()),
            on_refresh=self._refresh_table,
            parent=self
        )
        dialog.show()

    def _refresh_table(self):
        """Refresh the table data."""
        self.table.refresh()

    def _on_row_clicked(self, row_data: Any):
        """Handle row click from table."""
        if isinstance(row_data, dict):
            data = {str(k): v for k, v in row_data.items()}
            self._on_row_action(data, "View")

    def _on_row_action_signal(self, row_data: object, action: str):
        """Handle row_action_triggered signal."""
        if isinstance(row_data, dict):
            data = {str(k): v for k, v in row_data.items()}
            self._on_row_action(data, action)

    def _on_row_action(self, row_data: dict[str, Any], action: str):
        """Handle row action from skewer menu."""
        said = row_data.get('_said', '')
        schema = row_data.get('Schema', '')
        recipient = row_data.get('Recipient', '')

        if action == "View":
            self._view_credential(said)
        elif action == "Send":
            self._send_credential(said)
        elif action == "Revoke":
            self._revoke_credential(said)
        elif action == "Export":
            self._export_credential(said)

    def _view_credential(self, said: str):
        """Open the view credential dialog."""
        credential = self._credentials_cache.get(said)
        if not credential:
            logger.error(f"Credential {said} not in cache")
            return

        if not self.app:
            logger.error("No app instance available")
            return

        logger.info(f"View credential: {said}")
        # TODO: Implement ViewPublishedCredentialDialog

    def _send_credential(self, said: str):
        """Send the credential."""
        logger.info(f"Send credential: {said}")
        # TODO: Implement send credential functionality

    def _revoke_credential(self, said: str):
        """Revoke the credential."""
        logger.info(f"Revoke credential: {said}")
        # TODO: Implement revoke credential functionality

    def _export_credential(self, said: str):
        """Export the credential."""
        logger.info(f"Export credential: {said}")
        # TODO: Implement export credential functionality

    def set_vault_name(self, vault_name: str):
        """
        Set the vault name for this page.

        Called by VaultPage during vault initialization.
        Does NOT load data - wait for on_show() when page becomes visible.

        Args:
            vault_name: Name of the open vault
        """
        self.vault_name = vault_name
        logger.debug(f"PublishedCredentialsListPage: set_vault_name({vault_name})")

    def on_show(self):
        """
        Called when the page becomes visible (user navigates to it).

        Triggers async data load via the table's load_requested signal.
        """
        # Clear cache from previous session
        self._credentials_cache.clear()

        # Request initial load (table will show loading state and emit load_requested)
        self.table.request_load()
