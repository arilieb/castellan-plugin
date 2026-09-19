# -*- encoding: utf-8 -*-
"""
castellan.users.edit module

Dialog for editing a user account on the Castellan server.
"""
from typing import TYPE_CHECKING, Callable

import qasync
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel
from keri import help

from locksmith.ui.toolkit.widgets import LocksmithDialog, LocksmithButton, LocksmithInvertedButton
from locksmith.ui.toolkit.widgets.fields import FloatingLabelLineEdit, FloatingLabelComboBox

from ..core import remoting

if TYPE_CHECKING:
    from locksmith.core.apping import LocksmithApplication
    from locksmith.ui.vault.page import VaultPage

logger = help.ogler.getLogger(__name__)


class EditUserDialog(LocksmithDialog):
    """Dialog for editing an existing user account."""

    def __init__(
        self,
        app: "LocksmithApplication",
        user: dict,
        on_refresh: Callable[[], None] | None = None,
        parent: "VaultPage | None" = None,
    ):
        self.app = app
        self.user = user
        self.on_refresh = on_refresh
        self._is_saving = False

        content_widget = QWidget()
        self._content_layout = QVBoxLayout(content_widget)
        self._content_layout.setContentsMargins(0, 10, 0, 0)
        self._content_layout.setSpacing(12)

        instruction = QLabel("Edit user account information.")
        instruction.setStyleSheet("font-size: 13px; color: #636466;")
        instruction.setWordWrap(True)
        self._content_layout.addWidget(instruction)

        # Username field
        self.username_field = FloatingLabelLineEdit(label_text="Username")
        self.username_field.setFixedWidth(450)
        self.username_field.setText(user.get('username', ''))
        self._content_layout.addWidget(self.username_field)

        # First Name field
        self.first_name_field = FloatingLabelLineEdit(label_text="First Name")
        self.first_name_field.setFixedWidth(450)
        self.first_name_field.setText(user.get('first_name', ''))
        self._content_layout.addWidget(self.first_name_field)

        # Last Name field
        self.last_name_field = FloatingLabelLineEdit(label_text="Last Name")
        self.last_name_field.setFixedWidth(450)
        self.last_name_field.setText(user.get('last_name', ''))
        self._content_layout.addWidget(self.last_name_field)

        # Email field
        self.email_field = FloatingLabelLineEdit(label_text="Email Address")
        self.email_field.setFixedWidth(450)
        self.email_field.setText(user.get('email', ''))
        self._content_layout.addWidget(self.email_field)

        # Role dropdown
        self.role_dropdown = FloatingLabelComboBox(label_text="Select Role")
        self.role_dropdown.setFixedWidth(450)
        self.role_dropdown.addItem("Owner", userData="owner")
        self.role_dropdown.addItem("Admin", userData="admin")
        self.role_dropdown.addItem("Member", userData="member")

        # Set current role
        current_role = user.get('role', 'member').lower()
        role_index = {"": 0, "owner": 0, "admin": 1, "member": 2}.get(current_role, 2)
        self.role_dropdown.setCurrentIndex(role_index)

        self._content_layout.addWidget(self.role_dropdown)

        self._content_layout.addStretch()

        button_row = QHBoxLayout()
        button_row.addStretch()
        self.cancel_btn = LocksmithInvertedButton("Cancel")
        self.save_btn = LocksmithButton("Save Changes")
        button_row.addWidget(self.cancel_btn)
        button_row.addSpacing(10)
        button_row.addWidget(self.save_btn)

        super().__init__(
            parent=parent,
            title="Edit User",
            title_icon=":/assets/material-icons/edit.svg",
            content=content_widget,
            buttons=button_row,
        )

        self.cancel_btn.clicked.connect(self.close)
        self.save_btn.clicked.connect(self._on_save)

        self.setFixedWidth(530)
        self.setFixedHeight(540)

    def _validate_form(self) -> tuple[bool, list[str]]:
        """Validate form fields."""
        errors = []

        username = self.username_field.text().strip()
        if not username:
            errors.append("Username is required.")

        email = self.email_field.text().strip()
        if not email:
            errors.append("Email address is required.")
        elif "@" not in email or "." not in email.split("@")[-1]:
            errors.append("Please enter a valid email address.")

        return len(errors) == 0, errors

    def _on_save(self):
        if self._is_saving:
            return

        is_valid, errors = self._validate_form()
        if not is_valid:
            self.show_error("\n".join(errors))
            return

        self._is_saving = True
        self.save_btn.setEnabled(False)
        self.save_btn.setText("Saving...")
        self.cancel_btn.setEnabled(False)
        self.clear_error()
        self._do_save()

    @qasync.asyncSlot()
    async def _do_save(self):
        try:
            user_id = self.user.get('aid', '')
            username = self.username_field.text().strip()
            first_name = self.first_name_field.text().strip()
            last_name = self.last_name_field.text().strip()
            email = self.email_field.text().strip()
            role = self.role_dropdown.currentData()

            result = await remoting.update_account(
                app=self.app,
                account_id=user_id,
                username=username,
                email=email,
                role=role,
                first_name=first_name,
                last_name=last_name,
            )

            if not result.get('success'):
                error_msg = result.get('error', 'Unknown error')
                self.show_error(f"Failed to update user: {error_msg}")
                return

            # Success
            logger.info(f"User {username} updated successfully")
            self.close()
            if self.on_refresh:
                self.on_refresh()

        except Exception as e:
            logger.exception(f"Error updating user: {e}")
            self.show_error(str(e))

        finally:
            self._is_saving = False
            self.save_btn.setEnabled(True)
            self.save_btn.setText("Save Changes")
            self.cancel_btn.setEnabled(True)
