# -*- encoding: utf-8 -*-
"""
castellan.db.basing module

castellan-specific dataclasses and database (castellanBaser).
"""
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

from keri import help
from keri.db import dbing, koming

if TYPE_CHECKING:
    from locksmith.core.apping import LocksmithApplication

logger = help.ogler.getLogger(__name__)

@dataclass
class CastellanSettings:
    """Persisted settings for the Castellan plugin."""

    publish_mode: str = "registrar"  # "registrar" | "serviceprovider"
    issuer_aid: str = ""
    username: str = ""
    registry_name: str = ""
    registrar_aid: str = ""
    registrar_url: str = ""


@dataclass
class MultisigIdentityState:
    """
    Track the local identifier chosen to represent this vault in the Castellan
    peer-discovery network (uploaded to castellan so other participants can
    discover it when forming a multisig group).

    Singleton — a vault has one identity it registers for peer discovery,
    even though that identity may go on to form multiple groups.
    """
    chosen_identifier_alias: str = ""
    chosen_identifier_aid: str = ""
    identifier_uploaded: bool = False


@dataclass
class MultisigInitState:
    """
    Track multi-step progress for a single Castellan multisig group-initialization
    flow. Keyed by group_alias (not a singleton) so multiple past/concurrent
    group-setup attempts can coexist, e.g. once surfaced through an issuers CRUD.
    """
    group_alias: str
    init_step: int = 3               # 3=group co-signing, 4=registry co-signing
    is_proposer: bool = True
    init_complete: bool = False
    section4_started: bool = False   # registry phase revealed but not yet counselor-complete
    group_signed_aids: list = field(default_factory=list)     # AIDs confirmed in group icp
    registry_signed_aids: list = field(default_factory=list)  # AIDs confirmed in registry
    group_isith: str = "1"           # signing threshold — persisted for joiner display
    group_nsith: str = "1"           # rotation threshold
    group_toad: str = "0"            # TOAD


class CastellanBaser(dbing.LMDBer):
    """Plugin-owned database for castellan/Castellan state.

    Manages Castellan accounts, teams, and other state
    in a separate LMDB from the core castellanBaser.
    """
    TailDirPath = "keri/cast"
    AltTailDirPath = ".keri/cast"
    TempPrefix = "rt"

    def __init__(self, name="castellan", headDirPath=None, reopen=True, **kwa):
        self.castellan_settings = None
        self.castellan_multisig_identity = None
        self.castellan_multisig_init = None

        super(CastellanBaser, self).__init__(name=name, headDirPath=headDirPath, reopen=reopen, **kwa)

    def reopen(self, readonly=False, **kwa):
        super(CastellanBaser, self).reopen(readonly, **kwa)

        self.castellan_settings = koming.Komer(
            db=self,
            subkey='casset.',
            schema=CastellanSettings,
        )

        self.castellan_multisig_identity = koming.Komer(
            db=self,
            subkey='msid.',
            schema=MultisigIdentityState,
        )

        self.castellan_multisig_init = koming.Komer(
            db=self,
            subkey='msinit.',
            schema=MultisigInitState,
        )

        return self.env