# -*- encoding: utf-8 -*-
"""
castellan.schema.list module

Schema list page — shows schemas stored on the Castellan server.
"""
from typing import Any, TYPE_CHECKING

import qasync
from PySide6.QtGui import QPalette, QColor
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel
from keri import help
from locksmith.ui import colors
from locksmith.ui.toolkit.tables import PaginatedTableWidget
from locksmith.ui.toolkit.widgets import LocksmithDialog, LocksmithButton, LocksmithInvertedButton

from ..core import remoting
from .upload import UploadSchemaDialog
from .view import ViewSchemaDialog

if TYPE_CHECKING:
    from locksmith.ui.vault.page import VaultPage

logger = help.ogler.getLogger(__name__)


class SchemaListPage(QWidget):
    """Paginated list of schemas stored on the Castellan server."""

    def __init__(self, app, parent: "VaultPage | None" = None):
        super().__init__(parent)
        self._parent = parent
        self.app = app
        self.vault_name = ""
        self._schema_cache: dict[str, dict[str, Any]] = {}
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
            columns=["Title", "Version", "Created Date"],
            column_widths={"Version": 200, "Created Date": 185, "Actions": 50},
            title="Schemas",
            icon_path=":/assets/material-icons/schema.svg",
            show_add_button=True,
            add_button_text="Upload Schema(s)",
            row_actions=["View", "Delete"],
            row_action_icons={
                "View": ":/assets/material-icons/view.svg",
                "Delete": ":/assets/material-icons/delete.svg",
            },
            items_per_page=10,
            show_search=True,
            column_sort_mapping={
                "Title": "title",
                "Version": "version",
                "Created Date": "created_at",
            },
            transform_func=self._transform_schema_to_row,
            parent=self,
        )

        self.table.add_clicked.connect(self._on_upload_schemas)
        self.table.row_action_triggered.connect(self._on_row_action_signal)
        self.table.row_clicked.connect(self._on_row_clicked)
        self.table.load_requested.connect(self._on_load_requested)
        self.table.load_error.connect(self._on_load_error)

        layout.addWidget(self.table)

    def _transform_schema_to_row(self, schema: dict[str, Any]) -> dict[str, Any]:
        said = schema.get('said', '')
        title = schema.get('title', '')
        version = schema.get('version', '')
        created_at = schema.get('created_at', '')

        row_data = {
            'Title': title,
            'Version': version,
            'Created Date': created_at,
            '_said': said,
        }

        self._schema_cache[said] = schema
        return row_data

    @qasync.asyncSlot(dict)
    async def _on_load_requested(self, params: dict):
        if not self.app:
            self.table.load_error.emit("No app instance available")
            return

        self._schema_cache.clear()

        try:
            response = await remoting.fetch_schemas(
                app=self.app,
                page=params["page"],
                page_size=params["page_size"],
                filter_term=params.get("filter_term"),
                order=params.get("order"),
            )
            self.table.set_page_data(response, data_key="schemas")
        except Exception as e:
            logger.exception(f"Error loading schemas: {e}")
            self.table.load_error.emit(str(e))

    @staticmethod
    def _on_load_error(error_msg: str):
        logger.error(f"Table load error: {error_msg}")

    def _on_upload_schemas(self):
        if not self.app:
            return
        dialog = UploadSchemaDialog(
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
            self._view_schema(said)
        elif action == "Delete":
            self._confirm_delete_schema(said)

    def _view_schema(self, said: str):
        schema = self._schema_cache.get(said)
        if not schema:
            logger.error(f"Schema {said} not in cache")
            return
        dialog = ViewSchemaDialog(schema=schema, parent=self)
        dialog.show()

    def _confirm_delete_schema(self, said: str):
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 10, 0, 0)
        label = QLabel("Remove this schema from the Castellan server?")
        label.setStyleSheet("font-size: 13px;")
        label.setWordWrap(True)
        layout.addWidget(label)

        button_row = QHBoxLayout()
        button_row.addStretch()
        no_btn = LocksmithInvertedButton("No")
        yes_btn = LocksmithButton("Yes")
        button_row.addWidget(no_btn)
        button_row.addWidget(yes_btn)

        dialog = LocksmithDialog(
            parent=self,
            title="Remove Schema",
            title_icon=":/assets/material-icons/delete.svg",
            content=content,
            buttons=button_row,
        )
        no_btn.clicked.connect(dialog.close)
        yes_btn.clicked.connect(lambda: self._delete_schema(said, dialog))
        dialog.show()

    def _delete_schema(self, said: str, dialog: LocksmithDialog):
        dialog.close()
        self._do_delete_schema(said)

    @qasync.asyncSlot()
    async def _do_delete_schema(self, said: str):
        try:
            result = await remoting.delete_schema(self.app, said)
            if result.get('success'):
                self._refresh_table()
            else:
                logger.error(f"Delete failed: {result.get('error')}")
        except Exception as e:
            logger.exception(f"Error deleting schema: {e}")

    def set_vault_name(self, vault_name: str):
        self.vault_name = vault_name

    def on_show(self):
        self._schema_cache.clear()
        self.table.request_load()
