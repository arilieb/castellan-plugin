# -*- encoding: utf-8 -*-
"""
whisper.db.basing module

Whisper-specific dataclasses and database (WhisperBaser).
"""
from dataclasses import dataclass

from keri.db import dbing, koming


@dataclass
class WhisperAccount:
    """
    Track HealthKERI account information.

    This dataclass stores the user's healthKERI account details including
    their associated identifier, contact information, and notification preferences.
    """
    aid: str
    alias: str
    email: str
    receiveEmail: bool
    cellPhone: str
    receiveText: bool
    firstName: str
    lastName: str
    username: str
    default_team: str | None = None


@dataclass
class WhisperTeam:
    """
    Track Whisper team information.

    This dataclass stores team details for Whisper account organization,
    including team membership and resource limits.
    """
    name: str
    email: str
    id: str | None = None
    members: list[dict[str, str]] | None = None
    projects: list[str] | None = None
    paymentMethods: str | None = None
    stripeCustomerId: str | None = None
    identifierLimit: int | None = None
    watcherLimit: int | None = None
    witnessLimit: int | None = None
    mailboxLimit: int | None = None



class WhisperBaser(dbing.LMDBer):
    """Plugin-owned database for Whisper/Weirwood state.

    Manages Weirwood accounts, teams, and other state
    in a separate LMDB from the core WhisperBaser.
    """
    TailDirPath = "keri/rt"
    AltTailDirPath = ".keri/rt"
    TempPrefix = "rt"

    def __init__(self, name="whisper", headDirPath=None, reopen=True, **kwa):
        self.whisperAccounts = None
        self.whisperTeams = None

        super(WhisperBaser, self).__init__(name=name, headDirPath=headDirPath, reopen=reopen, **kwa)

    def reopen(self, **kwa):
        super(WhisperBaser, self).reopen(**kwa)

        # TODO: Change subkey and potentially ...DirPath and TempPrefix vars when implementing unique whisper acc
        self.whisperAccounts = koming.Komer(
            db=self,
            subkey='hkAccounts.',
            schema=WhisperAccount,
            seperator='>'
        )

        self.whisperTeams = koming.Komer(
            db=self,
            subkey='hkTeams.',
            schema=WhisperTeam,
            seperator='>'
        )
        return self.env