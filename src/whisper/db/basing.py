# -*- encoding: utf-8 -*-
"""
whisper.db.basing module

Whisper-specific dataclasses and database (WhisperBaser).
"""
from dataclasses import dataclass
from typing import TYPE_CHECKING

from keri import help
from keri.db import dbing, koming

if TYPE_CHECKING:
    from locksmith.core.apping import LocksmithApplication

logger = help.ogler.getLogger(__name__)


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


def sync_account_to_whisper(app: "LocksmithApplication") -> bool:
    """
    Sync the current healthKERI account into the whisper plugin state.

    Reads the account from plugin_state["healthkeri"], constructs a WhisperAccount,
    persists it to the whisper DB, updates plugin_state["whisper"], and initializes
    the ESSR client.  Returns True on success, False if nothing to sync.

    Called when a "hk_account_created" doer event is received on the vault signal bus,
    so the whisper plugin can react without a direct dependency on healthKERI.
    """
    if not app.vault:
        return False

    hk_state = app.vault.plugin_state.get("healthkeri", {})
    whisper_state = app.vault.plugin_state.get("whisper", {})

    hk_account = hk_state.get("account")
    whisper_db = whisper_state.get("db")

    if hk_account is None or whisper_db is None:
        logger.warning("sync_account_to_whisper: missing healthkeri account or whisper db")
        return False

    # Build WhisperAccount from HealthKERIAccount (identical fields)
    whisper_account = WhisperAccount(
        aid=hk_account.aid,
        alias=hk_account.alias,
        email=hk_account.email,
        receiveEmail=hk_account.receiveEmail,
        cellPhone=hk_account.cellPhone,
        receiveText=hk_account.receiveText,
        firstName=hk_account.firstName,
        lastName=hk_account.lastName,
        username=hk_account.username,
        default_team=hk_account.default_team,
    )

    # Persist and update in-memory state
    whisper_db.whisperAccounts.pin(keys=(hk_account.aid,), val=whisper_account)
    whisper_state["account"] = whisper_account

    hk_team = hk_state.get("team")

    if hk_team is None:
        logger.warning("sync_account_to_whisper: missing healthkeri team")
        return False

    # Build WhisperAccount from HealthKERIAccount (identical fields)
    whisper_team = WhisperTeam(
        name=hk_team.name,
        email=hk_team.email,
        id=hk_team.id,
        members=hk_team.members,
        projects=hk_team.projects,
        paymentMethods=hk_team.paymentMethods,
        stripeCustomerId=hk_team.stripeCustomerId,
        identifierLimit=hk_team.identifierLimit,
        watcherLimit=hk_team.watcherLimit,
        witnessLimit=hk_team.witnessLimit,
        mailboxLimit=hk_team.mailboxLimit,
    )

    # Persist and update in-memory state
    whisper_db.whisperTeams.pin(keys=(hk_team.name,), val=whisper_team)
    whisper_state["team"] = whisper_team

    # Initialize ESSR client for whisper
    try:
        from locksmith.core.essring import APIClient
        hab = app.vault.hby.habs.get(hk_account.aid)
        if hab is not None:
            whisper_state["essr"] = APIClient(
                url=app.protectedUrl,
                root=app.root,
                hby=app.vault.hby,
                hab=hab,
            )
    except Exception as e:
        logger.warning(f"sync_account_to_whisper: could not init ESSR: {e}")

    logger.info(f"sync_account_to_whisper: synced account {hk_account.aid} into whisper state")
    return True