# -*- encoding: utf-8 -*-
"""
castellan.issuers.create_registry module

Dialog for creating a credential registry for an identifier.
"""
import qasync
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout
from keri import help
from keri.core import coring, eventing
from keri.kering import TraitDex
from keri.vdr import eventing as veventing

from locksmith.ui.toolkit.widgets import (
    LocksmithDialog, LocksmithInvertedButton, LocksmithButton, FloatingLabelLineEdit
)
from ..core import remoting

logger = help.ogler.getLogger(__name__)


class CreateRegistryDialog(LocksmithDialog):
    """Dialog for creating a credential registry for an identifier."""

    def __init__(self, app, identifier: dict, on_refresh=None, parent=None):
        self.app = app
        self.identifier = identifier
        self.on_refresh = on_refresh
        self._is_creating = False
        self.aid = identifier.get('aid')

        if not self.aid:
            raise ValueError("Identifier must have an AID")

        # Build form
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(20, 20, 20, 20)
        content_layout.setSpacing(16)

        # Registry name input
        self.name_field = FloatingLabelLineEdit(label_text="Registry Name")
        self.name_field.setPlaceholderText("Enter a name for this registry")
        content_layout.addWidget(self.name_field)

        # Buttons
        button_row = QHBoxLayout()
        button_row.addStretch()
        self.cancel_btn = LocksmithInvertedButton("Cancel")
        self.create_btn = LocksmithButton("Create")
        button_row.addWidget(self.cancel_btn)
        button_row.addWidget(self.create_btn)
        button_row.addStretch()

        content_layout.addLayout(button_row)

        super().__init__(
            parent=parent,
            title="Create Credential Registry",
            title_icon=":/assets/material-icons/shield_lock.svg",
            content=content_widget,
            buttons=None,  # Buttons already in content
        )

        self.cancel_btn.clicked.connect(self.close)
        self.create_btn.clicked.connect(self._on_create)
        self.setFixedSize(480, 280)

    def _validate_form(self) -> tuple[bool, list[str]]:
        """Validate form inputs."""
        errors = []

        registry_name = self.name_field.text().strip()
        if not registry_name:
            errors.append("Registry name is required.")

        return len(errors) == 0, errors

    def _on_create(self):
        """Handle Create button click."""
        if self._is_creating:
            return

        # Validate
        is_valid, errors = self._validate_form()
        if not is_valid:
            self.show_error("\n".join(errors))
            return

        # Guard and update UI
        self._is_creating = True
        self.create_btn.setEnabled(False)
        self.create_btn.setText("Creating...")
        self.cancel_btn.setEnabled(False)
        self.clear_error()

        # Start async operation
        self._do_create()

    @qasync.asyncSlot()
    async def _do_create(self):
        """Create registry and upload to server."""
        try:
            multisig_id = self.identifier.get('id')
            registry_name = self.name_field.text().strip()

            # Get hab
            if not self.app.vault or not self.app.vault.hby:
                self.show_error("No local vault available")
                return

            hab = self.app.vault.hby.habs.get(self.aid)
            if not hab:
                self.show_error(f"Identifier {self.aid} is not controlled locally")
                return

            member_index = hab.smids.index(hab.mhab.pre)
            tholder = hab.kever.tholder

            # If our signature is enough to create the registry, do so, otherwise create without parsing
            if tholder.satisfy([member_index]):
                registry = self.app.vault.rgy.makeRegistry(
                    name=registry_name,
                    prefix=hab.pre,
                    noBackers=True,
                    baks=[],
                    toad=0,
                    nonce=coring.randomNonce(),
                )

                # Create registry seal
                regd = getattr(registry, "regd", registry.regk)
                rseal = {"i": registry.regk, "s": "0", "d": regd}

                # Create and sign IXN to anchor the VCP
                anc = hab.interact(data=[rseal])

                seqner = coring.Seqner(sn=hab.kever.sner.num)
                saider = coring.Saider(qb64=hab.kever.serder.said)
                registry.anchorMsg(pre=registry.regk,
                                   regd=registry.regd,
                                   seqner=seqner,
                                   saider=saider)

                hab.kvy.processEscrows()
                self.app.vault.rgy.processEscrows()

                # Get event bytes
                vcp_bytes = bytearray()
                for msg in self.app.vault.rgy.reger.clonePreIter(registry.regk):
                    vcp_bytes.extend(msg)

                if not vcp_bytes:
                    raise ValueError("Failed to retrieve registry event bytes")

                ixn_bytes = bytes(anc)

            else:
                # Create registry locally
                logger.info(f"Creating registry '{registry_name}' for {self.aid}")

                self.vcp = veventing.incept(hab.pre,
                                           baks=[],
                                           toad=0,
                                           nonce=coring.randomNonce(),
                                           cnfg=[TraitDex.NoBackers],
                                           code=coring.MtrDex.Blake3_256)

                # Create registry seal
                regd = self.vcp.said
                rseal = {"i": self.vcp.pre, "s": "0", "d": regd}

                # Create and sign IXN to anchor the VCP
                kever = hab.kever
                serder = eventing.interact(pre=kever.prefixer.qb64,
                                           dig=kever.serder.said,
                                           sn=kever.sner.num + 1,
                                           data=[rseal])

                sigers = hab.sign(ser=serder.raw)
                anc = eventing.messagize(serder, sigers=sigers)

                # Get event bytes
                vcp_bytes = bytearray()
                for msg in self.app.vault.rgy.reger.clonePreIter(self.vcp.pre):
                    vcp_bytes.extend(msg)
                ixn_bytes = bytes(anc)

            # Upload to server
            result = await remoting.create_multisig_registry(
                app=self.app,
                multisig_id=multisig_id,
                vcp_bytes=bytes(vcp_bytes),
                ixn_bytes=ixn_bytes,
                registry_name=registry_name,
            )

            if not result.get('success'):
                error_msg = result.get('error', 'Unknown error')
                self.show_error(f"Failed to create registry: {error_msg}")
                return

            # Success
            logger.info(f"Registry '{registry_name}' created successfully")
            self.close()
            if self.on_refresh:
                self.on_refresh()

        except Exception as e:
            logger.exception(f"Error creating registry: {e}")
            self.show_error(f"Error creating registry: {str(e)}")

        finally:
            # Restore button state
            self._is_creating = False
            self.create_btn.setEnabled(True)
            self.create_btn.setText("Create")
            self.cancel_btn.setEnabled(True)
