# -*- encoding: utf-8 -*-
"""
castellan.users.list module

User accounts list page — shows user accounts from the Castellan server.
"""
from typing import Any, TYPE_CHECKING

import qasync
from PySide6.QtGui import QPalette, QColor
from PySide6.QtWidgets import QWidget, QVBoxLayout
from keri import help
from keri.help import helping
from locksmith.ui import colors
from locksmith.ui.toolkit.tables import PaginatedTableWidget

from ..core import remoting
from .view import ViewUserDialog

if TYPE_CHECKING:
    from locksmith.ui.vault.page import VaultPage

logger = help.ogler.getLogger(__name__)


class UsersListPage(QWidget):
    """Paginated list of user accounts from the Castellan server."""

    def __init__(self, app, parent: "VaultPage | None" = None):
        super().__init__(parent)
        self._parent = parent
        self.app = app
        self.vault_name = ""
        self._users_cache: dict[str, dict[str, Any]] = {}
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
            columns=["User Name", "Name", "Email", "Role", "Status", "Created Date"],
            column_widths={
                "User Name": 150,
                "Email": 185,
                "Role": 80,
                "Status": 100,
                "Created Date": 165,
                "Actions": 50
            },
            title="Users",
            icon_path=":/assets/material-icons/group.svg",
            show_add_button=True,
            add_button_text="Create User",
            row_actions=["View", "Edit", "Delete"],
            row_action_icons={
                "View": ":/assets/material-icons/view.svg",
                "Edit": ":/assets/material-icons/edit.svg",
                "Delete": ":/assets/material-icons/delete.svg",
            },
            row_actions_callback=self._get_row_actions,
            items_per_page=10,
            show_search=True,
            column_sort_mapping={
                "Name": "name",
                "Email": "email",
                "Role": "role",
                "Status": "status",
                "Created Date": "created_at",
            },
            transform_func=self._transform_user_to_row,
            parent=self,
        )

        self.table.row_action_triggered.connect(self._on_row_action_signal)
        self.table.row_clicked.connect(self._on_row_clicked)
        self.table.load_requested.connect(self._on_load_requested)
        self.table.load_error.connect(self._on_load_error)
        self.table.add_clicked.connect(self._on_add_user)

        layout.addWidget(self.table)

    def _get_row_actions(self, row_data: dict[str, Any]) -> tuple[list[str], dict[str, str]]:
        all_icons = {
            "View": ":/assets/material-icons/view.svg",
            "Edit": ":/assets/material-icons/edit.svg",
            "Delete": ":/assets/material-icons/delete.svg",
        }

        if self.my_account.get("role", "member") == "member":
            return ["View"], {"View": all_icons["View"]}

        actions = ["View", "Edit"]
        if row_data.get("Role") not in ("", "Owner") and row_data.get('_id') not in self.app.vault.hby.habs:
            actions.append("Delete")

        return actions, {a: all_icons[a] for a in actions}

    def _transform_user_to_row(self, user: dict[str, Any]) -> dict[str, Any]:
        """Transform user account data to table row format."""
        user_id = user.get('aid', '')
        name = user.get('username', '')
        first_name = user.get('first_name', '')
        last_name = user.get('last_name', '')
        email = user.get('email', '')
        role = user.get('role', 'Owner').capitalize()
        status = user.get('status', 'Active').capitalize()
        created_at_raw = user.get('created_at', '')

        # Format created date
        if created_at_raw:
            created_at_date = helping.fromIso8601(created_at_raw)
            created_at = created_at_date.strftime("%b %d, %Y %I:%M %p")
        else:
            created_at = "Unknown"

        # Color code status
        status_color = colors.SUCCESS_INDICATOR if status == "Active" else colors.DANGER

        row_data = {
            'User Name': name,
            'Name': f"{first_name} {last_name}",
            'Email': email,
            'Role': role,
            'Status': status,
            'Status_color': status_color,
            'Created Date': created_at,
            '_id': user_id,  # Internal tracking
        }

        # Cache full user data
        self._users_cache[user_id] = user
        return row_data

    @qasync.asyncSlot(dict)
    async def _on_load_requested(self, params: dict):
        """Load users from backend."""
        if not self.app:
            self.table.load_error.emit("No app instance available")
            return

        self.my_account = self.app.vault.plugin_state["castellan"]["account"]
        print(self.my_account)
        if self.my_account.get("role", "") == "member":
            self.table.set_add_button_visibitity(False)
        else:
            self.table.set_add_button_visibitity(True)

        self._users_cache.clear()

        try:
            response = await remoting.fetch_accounts(
                app=self.app,
                page=params["page"],
                page_size=params["page_size"],
                filter_term=params.get("filter_term"),
                order=params.get("order"),
            )
            self.table.set_page_data(response, data_key="accounts")
        except Exception as e:
            logger.exception(f"Error loading users: {e}")
            self.table.load_error.emit(str(e))

    @staticmethod
    def _on_load_error(error_msg: str):
        logger.error(f"Table load error: {error_msg}")

    def _refresh_table(self):
        self.table.refresh()

    def _on_row_clicked(self, row_data: Any):
        if isinstance(row_data, dict):
            self._on_row_action({str(k): v for k, v in row_data.items()}, "View")

    def _on_row_action_signal(self, row_data: object, action: str):
        if isinstance(row_data, dict):
            self._on_row_action({str(k): v for k, v in row_data.items()}, action)

    def _on_row_action(self, row_data: dict[str, Any], action: str):
        """Handle row action (View, Edit, or Delete)."""
        user_id = row_data.get('_id', '')
        if action == "View":
            self._view_user(user_id)
        elif action == "Edit":
            self._on_edit_user(user_id)
        elif action == "Delete":
            self._on_delete_user(row_data)

    def _view_user(self, user_id: str):
        """Open view dialog for user."""
        user = self._users_cache.get(user_id)
        if not user:
            logger.error(f"User {user_id} not in cache")
            return

        logger.info(f"Opening view dialog for user: {user_id}")
        dialog = ViewUserDialog(user=user, parent=self)
        dialog.show()

    def _on_add_user(self):
        """Handle Add user button click."""
        from .create import CreateUserDialog

        logger.info("Opening create user dialog")
        dialog = CreateUserDialog(
            app=self.app,
            on_refresh=self._refresh_table,
            parent=self._parent
        )
        dialog.open()

    def _on_edit_user(self, user_id: str):
        """Handle Edit user action."""
        from .edit import EditUserDialog

        user = self._users_cache.get(user_id)
        if not user:
            logger.error(f"User {user_id} not in cache")
            return

        logger.info(f"Opening edit dialog for user: {user_id}")
        dialog = EditUserDialog(
            app=self.app,
            user=user,
            on_refresh=self._refresh_table,
            parent=self._parent
        )
        dialog.open()

    def _on_delete_user(self, row_data: dict[str, Any]) -> None:
        """Handle Delete user action."""
        from .delete import DeleteUserDialog

        user_id = row_data.get("_id", "")
        user_name = row_data.get("Name", "")

        if not user_id:
            logger.error("Cannot delete: no user ID found")
            return

        if not user_name:
            user_name = user_id[:12]

        logger.info(f"Opening delete dialog for user: {user_name}")

        dialog = DeleteUserDialog(
            app=self.app,
            user_name=user_name,
            user_id=user_id,
            on_success=self._on_user_deleted,
            parent=self._parent
        )
        dialog.open()

    def _on_user_deleted(self, user_id: str):
        """Handle successful user deletion."""
        logger.info(f"User {user_id} deleted, reloading list")
        self.on_show()

    def set_vault_name(self, vault_name: str):
        self.vault_name = vault_name

    def on_show(self):
        """Called when page is shown - refresh data."""
        self._users_cache.clear()
        self.table.request_load()
