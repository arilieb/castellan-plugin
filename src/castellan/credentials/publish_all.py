# -*- encoding: utf-8 -*-
"""
castellan.credentials.publish_all module

Dialog for publishing all local credentials to the Castellan server in bulk.
"""
from collections.abc import Callable
from typing import TYPE_CHECKING

import qasync
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel
from keri import help

from locksmith.ui.toolkit.widgets import LocksmithDialog, LocksmithButton, LocksmithInvertedButton
from ..core import remoting

if TYPE_CHECKING:
    from locksmith.core.apping import LocksmithApplication
    from locksmith.ui.vault.page import VaultPage

logger = help.ogler.getLogger(__name__)


class PublishAllConfirmationDialog(LocksmithDialog):
    """Confirmation dialog for bulk-uploading all local credentials to Castellan."""

    def __init__(
        self,
        app: "LocksmithApplication",
        on_refresh: Callable[[], None] | None = None,
        parent: "VaultPage | None" = None,
    ):
        self.app = app
        self.on_refresh = on_refresh
        self._is_publishing = False

        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(8)

        label = QLabel("Would you like to publish all credentials to Castellan server?")
        label.setStyleSheet("font-size: 13px; color: #636466;")
        label.setWordWrap(True)
        layout.addWidget(label)

        button_row = QHBoxLayout()
        button_row.addStretch()
        self.no_btn = LocksmithInvertedButton("No")
        self.yes_btn = LocksmithButton("Yes")
        button_row.addWidget(self.no_btn)
        button_row.addSpacing(10)
        button_row.addWidget(self.yes_btn)

        super().__init__(
            parent=parent,
            title="Publish All",
            title_icon=":/assets/material-icons/out-badge.svg",
            content=content_widget,
            buttons=button_row,
        )

        self.no_btn.clicked.connect(self.close)
        self.yes_btn.clicked.connect(self._on_yes)

        self.setFixedWidth(420)

    def _on_yes(self):
        if self._is_publishing:
            return
        self._is_publishing = True
        self.yes_btn.setEnabled(False)
        self.yes_btn.setText("Publishing...")
        self.no_btn.setEnabled(False)
        self.clear_error()
        self._do_publish_all()

    @qasync.asyncSlot()
    async def _do_publish_all(self):
        try:
            if not self.app or not self.app.vault or not self.app.vault.rgy:
                self.show_error("No vault open.")
                return

            reger = self.app.vault.rgy.reger
            hby = self.app.vault.hby

            # Fetch already-uploaded SAIDs
            issued_saids = await remoting.fetch_all_castellan_issued_saids(self.app)
            received_saids = await remoting.fetch_all_castellan_received_saids(self.app)

            # Get all local issued credentials
            issued_local_saids = [said for (_, said) in reger.issus.getItemIter()]
            issued_creds = reger.cloneCreds(issued_local_saids, hby.db)

            # Get all local received credentials
            received_local_saids = list()
            for pre in self.app.vault.hby.habs.keys():
                received_local_saids.extend([saider for saider in self.app.vault.rgy.reger.subjs.get(keys=(pre,))])
            received_creds = reger.cloneCreds(received_local_saids, hby.db)

            errors = []

            for cred in issued_creds:
                sad = cred['sad']
                said = sad['d']
                if said in issued_saids:
                    continue
                schema = cred.get('schema', {})
                issuer = sad.get('i', '')
                subject = sad.get('a', {})
                recipient = subject.get('i', '') if isinstance(subject, dict) else ''
                result = await remoting.upload_issued_credential(
                    app=self.app,
                    credential_said=said,
                    schema=schema,
                    issuer=issuer,
                    recipient=recipient,
                )
                if not result.get('success'):
                    errors.append(f"Issued {said[:12]}...: {result.get('error', 'Unknown')}")

            for cred in received_creds:
                sad = cred['sad']
                said = sad['d']
                if said in received_saids:
                    continue
                schema = cred.get('schema', {})
                issuer = sad.get('i', '')
                subject = sad.get('a', {})
                holder = subject.get('i', '') if isinstance(subject, dict) else ''
                result = await remoting.upload_received_credential(
                    app=self.app,
                    credential_said=said,
                    schema=schema,
                    issuer=issuer,
                    holder=holder,
                )
                if not result.get('success'):
                    errors.append(f"Received {said[:12]}...: {result.get('error', 'Unknown')}")

            if errors:
                self.show_error("Some uploads failed:\n" + "\n".join(errors))
            else:
                self.close()
                if self.on_refresh:
                    QTimer.singleShot(1000, self.on_refresh)

        except Exception as e:
            logger.exception(f"Error during publish all: {e}")
            self.show_error(str(e))
        finally:
            self._is_publishing = False
            self.yes_btn.setEnabled(True)
            self.yes_btn.setText("Yes")
            self.no_btn.setEnabled(True)
