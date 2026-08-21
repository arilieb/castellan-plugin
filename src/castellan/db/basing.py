# -*- encoding: utf-8 -*-
"""
castellan.db.basing module

castellan-specific dataclasses and database (castellanBaser).
"""
from dataclasses import dataclass
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

        super(CastellanBaser, self).__init__(name=name, headDirPath=headDirPath, reopen=reopen, **kwa)

    def reopen(self, readonly=False, **kwa):
        super(CastellanBaser, self).reopen(readonly, **kwa)

        self.castellan_settings = koming.Komer(
            db=self,
            subkey='casset.',
            schema=CastellanSettings,
        )

        return self.env