# -*- encoding: utf-8 -*-
"""
castellan.users.create module

Dialog for creating a new user account on the Castellan server.
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


class CreateUserDialog(LocksmithDialog):
    """Dialog for creating a new user account."""

    def __init__(
        self,
        app: "LocksmithApplication",
        on_refresh: Callable[[], None] | None = None,
        parent: "VaultPage | None" = None,
    ):
        self.app = app
        self.on_refresh = on_refresh
        self._is_creating = False

        content_widget = QWidget()
        self._content_layout = QVBoxLayout(content_widget)
        self._content_layout.setContentsMargins(0, 10, 0, 0)
        self._content_layout.setSpacing(12)

        instruction = QLabel("Create a new user account on the Castellan server.")
        instruction.setStyleSheet("font-size: 13px; color: #636466;")
        instruction.setWordWrap(True)
        self._content_layout.addWidget(instruction)

        # Identifier dropdown (moved to top)
        self.identifier_dropdown = FloatingLabelComboBox(label_text="Select Identifier")
        self.identifier_dropdown.setFixedWidth(450)
        self.identifier_dropdown.currentIndexChanged.connect(self._on_identifier_selected)
        self._content_layout.addWidget(self.identifier_dropdown)

        # Username field (renamed from Name)
        self.username_field = FloatingLabelLineEdit(label_text="Username")
        self.username_field.setFixedWidth(450)
        self._content_layout.addWidget(self.username_field)

        # First Name field
        self.first_name_field = FloatingLabelLineEdit(label_text="First Name")
        self.first_name_field.setFixedWidth(450)
        self._content_layout.addWidget(self.first_name_field)

        # Last Name field
        self.last_name_field = FloatingLabelLineEdit(label_text="Last Name")
        self.last_name_field.setFixedWidth(450)
        self._content_layout.addWidget(self.last_name_field)

        # Email field
        self.email_field = FloatingLabelLineEdit(label_text="Email Address")
        self.email_field.setFixedWidth(450)
        self._content_layout.addWidget(self.email_field)

        # Role dropdown
        self.role_dropdown = FloatingLabelComboBox(label_text="Select Role")
        self.role_dropdown.setFixedWidth(450)
        self.role_dropdown.addItem("Owner", userData="owner")
        self.role_dropdown.addItem("Admin", userData="admin")
        self.role_dropdown.addItem("Member", userData="member")
        self.role_dropdown.setCurrentIndex(2)  # Default to Member
        self._content_layout.addWidget(self.role_dropdown)

        self._content_layout.addStretch()

        button_row = QHBoxLayout()
        button_row.addStretch()
        self.cancel_btn = LocksmithInvertedButton("Cancel")
        self.create_btn = LocksmithButton("Create User")
        button_row.addWidget(self.cancel_btn)
        button_row.addSpacing(10)
        button_row.addWidget(self.create_btn)

        super().__init__(
            parent=parent,
            title="Create User",
            title_icon=":/assets/material-icons/group.svg",
            content=content_widget,
            buttons=button_row,
        )

        self.cancel_btn.clicked.connect(self.close)
        self.create_btn.clicked.connect(self._on_create)

        self.setFixedWidth(530)
        self.setFixedHeight(625)

        # Populate identifier dropdown
        self._populate_identifiers()

    def _populate_identifiers(self):
        """Populate the identifier dropdown with remote contacts."""
        if not self.app or not self.app.vault:
            return

        try:
            hby = self.app.vault.hby
            org = self.app.vault.org

            # Add placeholder
            self.identifier_dropdown.addItem("Select identifier...", userData=None)

            identifier_count = 0

            # Get remote contacts from org
            if org:
                for contact_data in org.list():
                    if isinstance(contact_data, dict):
                        aid = contact_data.get("id", "")
                        alias = contact_data.get("alias", "")
                        if alias:
                            display = f"{alias} — {aid[:16]}..."
                        else:
                            display = f"{aid[:24]}..."
                        # Store full contact data including alias
                        self.identifier_dropdown.addItem(display, userData={'aid': aid, 'alias': alias})
                        identifier_count += 1

            # Set to placeholder by default
            self.identifier_dropdown.setCurrentIndex(0)

            if identifier_count == 0:
                self.identifier_dropdown.setEnabled(False)
                self.create_btn.setEnabled(False)
                self.show_error("No remote identifiers available. Please add contacts first.")

        except Exception as e:
            logger.exception(f"Error populating identifiers: {e}")
            self.show_error(f"Error loading identifiers: {e}")

    def _on_identifier_selected(self, index: int):
        """Handle identifier selection and auto-populate username and name fields."""
        if index <= 0:
            # Placeholder selected - clear fields
            self.username_field.setText("")
            self.first_name_field.setText("")
            self.last_name_field.setText("")
            return

        contact_data = self.identifier_dropdown.currentData()
        if not contact_data or not isinstance(contact_data, dict):
            return

        alias = contact_data.get('alias', '')
        if not alias:
            return

        # Set username to full alias
        self.username_field.setText(alias)

        # Split alias on space to get first and last name
        name_parts = alias.split(None, 1)  # Split on first whitespace only
        if len(name_parts) >= 1:
            self.first_name_field.setText(name_parts[0])
        if len(name_parts) >= 2:
            self.last_name_field.setText(name_parts[1])
        else:
            self.last_name_field.setText("")

    def _validate_form(self) -> tuple[bool, list[str]]:
        """Validate form fields."""
        errors = []

        if self.identifier_dropdown.currentIndex() <= 0:
            errors.append("Please select an identifier.")

        username = self.username_field.text().strip()
        if not username:
            errors.append("Username is required.")

        email = self.email_field.text().strip()
        if not email:
            errors.append("Email address is required.")
        elif "@" not in email or "." not in email.split("@")[-1]:
            errors.append("Please enter a valid email address.")

        return len(errors) == 0, errors

    def _on_create(self):
        if self._is_creating:
            return

        is_valid, errors = self._validate_form()
        if not is_valid:
            self.show_error("\n".join(errors))
            return

        self._is_creating = True
        self.create_btn.setEnabled(False)
        self.create_btn.setText("Creating...")
        self.cancel_btn.setEnabled(False)
        self.clear_error()
        self._do_create()

    @qasync.asyncSlot()
    async def _do_create(self):
        try:
            username = self.username_field.text().strip()
            first_name = self.first_name_field.text().strip()
            last_name = self.last_name_field.text().strip()
            email = self.email_field.text().strip()
            contact_data = self.identifier_dropdown.currentData()
            identifier_aid = contact_data.get('aid') if isinstance(contact_data, dict) else contact_data
            role = self.role_dropdown.currentData()

            result = await remoting.create_account(
                app=self.app,
                name=username,
                email=email,
                identifier_aid=identifier_aid,
                role=role,
                first_name=first_name,
                last_name=last_name,
            )

            if not result.get('success'):
                error_msg = result.get('error', 'Unknown error')
                self.show_error(f"Failed to create user: {error_msg}")
                return

            # Success
            logger.info(f"User {username} created successfully")
            self.close()
            if self.on_refresh:
                self.on_refresh()

        except Exception as e:
            logger.exception(f"Error creating user: {e}")
            self.show_error(str(e))

        finally:
            self._is_creating = False
            self.create_btn.setEnabled(True)
            self.create_btn.setText("Create User")
            self.cancel_btn.setEnabled(True)
