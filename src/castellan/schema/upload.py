# -*- encoding: utf-8 -*-
"""
castellan.schema.upload module

Dialog for uploading schemas to the Castellan server.
Uses ExtensibleSelectorWidget for multi-select.
"""
import json
from collections.abc import Callable
from typing import TYPE_CHECKING

import qasync
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel
from keri import help

from locksmith.ui.toolkit.widgets import LocksmithDialog, LocksmithButton, LocksmithInvertedButton
from locksmith.ui.toolkit.widgets.extensible import ExtensibleSelectorWidget
from ..core import remoting

if TYPE_CHECKING:
    from locksmith.core.apping import LocksmithApplication
    from locksmith.ui.vault.page import VaultPage

logger = help.ogler.getLogger(__name__)


class UploadSchemaDialog(LocksmithDialog):
    """Dialog for uploading one or more schemas to the Castellan server."""

    def __init__(
        self,
        app: "LocksmithApplication",
        on_refresh: Callable[[], None] | None = None,
        parent: "VaultPage | None" = None,
    ):
        self.app = app
        self.on_refresh = on_refresh
        self._is_uploading = False

        content_widget = QWidget()
        self._content_layout = QVBoxLayout(content_widget)
        self._content_layout.setContentsMargins(0, 10, 0, 0)
        self._content_layout.setSpacing(12)

        instruction = QLabel("Select schemas to upload to the Castellan server.")
        instruction.setStyleSheet("font-size: 13px; color: #636466;")
        instruction.setWordWrap(True)
        self._content_layout.addWidget(instruction)

        self.schema_selector = ExtensibleSelectorWidget(
            dropdown_label="Select Schema",
            selector_dropdown_items=[],
            max_scrollable_height=200,
        )
        self.schema_selector.setFixedWidth(450)
        self._content_layout.addWidget(self.schema_selector)
        self._content_layout.addStretch()

        button_row = QHBoxLayout()
        button_row.addStretch()
        self.cancel_btn = LocksmithInvertedButton("Cancel")
        self.upload_btn = LocksmithButton("Upload")
        button_row.addWidget(self.cancel_btn)
        button_row.addSpacing(10)
        button_row.addWidget(self.upload_btn)

        super().__init__(
            parent=parent,
            title="Upload Schemas",
            title_icon=":/assets/material-icons/schema.svg",
            content=content_widget,
            buttons=button_row,
        )

        self.cancel_btn.clicked.connect(self.close)
        self.upload_btn.clicked.connect(self._on_upload)

        self.setFixedWidth(530)

        # Populate dropdown async
        self._populate_dropdown()

    def showEvent(self, event):
        super().showEvent(event)
        self.schema_selector.set_dialog(self)

    @qasync.asyncSlot()
    async def _populate_dropdown(self):
        """Populate the selector with local schemas not yet on Castellan."""
        if not self.app or not self.app.vault or not self.app.vault.rgy:
            return

        try:
            existing_saids = await remoting.fetch_all_castellan_schema_saids(self.app)
            print(f"EXSITING SAIDS {existing_saids}")


            items = []
            for (schema_said,), schemer in self.app.vault.hby.db.schema.getItemIter():
                if schema_said in existing_saids:
                    continue

                sad = schemer.sed
                title = sad.get('title', 'Untitled Schema')
                version = sad.get('version', '1.0.0')
                description = sad.get('description', '')

                display_text = f"{title} v{version}"
                items.append((display_text, {
                    'said': schema_said,
                    'title': title,
                    'version': version,
                    'description': description,
                    'sad': sad,
                }))

            if items:
                self.schema_selector._populate_dropdown(items)
            else:
                self.schema_selector.selector_dropdown.setPlaceholderText("No schemas available to upload")
                self.upload_btn.setEnabled(False)

        except Exception as e:
            logger.exception(f"Error populating upload dropdown: {e}")
            self.show_error(f"Error loading schemas: {e}")

    def _on_upload(self):
        if self._is_uploading:
            return

        selected = self.schema_selector.get_selected_items()
        if not selected:
            self.show_error("Select at least one schema to upload.")
            return

        self._is_uploading = True
        self.upload_btn.setEnabled(False)
        self.upload_btn.setText("Uploading...")
        self.clear_error()
        self._do_upload(selected)

    @qasync.asyncSlot()
    async def _do_upload(self, selected: list):
        errors = []
        try:
            for _text, data in selected:
                if data is None:
                    continue
                result = await remoting.upload_schema(
                    app=self.app,
                    schema_said=data['said'],
                    sad=data['sad'],
                )
                if not result.get('success'):
                    errors.append(f"{data['title']}: {result.get('error', 'Unknown error')}")

            if errors:
                self.show_error("Some uploads failed:\n" + "\n".join(errors))
            else:
                self.close()
                if self.on_refresh:
                    self.on_refresh()
        except Exception as e:
            logger.exception(f"Error during upload: {e}")
            self.show_error(str(e))
        finally:
            self._is_uploading = False
            self.upload_btn.setEnabled(True)
            self.upload_btn.setText("Upload")
