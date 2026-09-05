# -*- encoding: utf-8 -*-
"""
castellan.issuers.multisig.doers module

Background Doers for Castellan multisig group initialization. All outbound
multisig coordination is sent via both the castellan /messages relay and the
standard KERI Poster/mailbox transport (best-effort — a peer may have no
shared witness/mailbox, in which case only the castellan relay succeeds).

The resulting credential registry is self-backed (noBackers=True, baks=[],
toad=0) — castellan's registrar API no longer supports registering a new TEL
registry or acting as a non-transferable backer for one, so no server-side
registration step is performed here. Castellan only becomes aware of the
registry indirectly, later, if/when a credential from it is revoked (handled
already by castellan.credentials.issued.revoke, unmodified).

Classes:
    CastellanMessagePoller     — polls /messages?topic=multisig, pipes into vault parser
    GroupMultisigInceptDoer    — initiates group icp, sends EXN via castellan + mailbox
    MultisigJoinDoer           — participant joins group icp, sends response via castellan + mailbox
    CreateRegistryDoer         — creates a self-backed registry (vcp + group ixn)
    RegistryAcceptDoer         — participant co-signs registry ixn
    CounselingCompletionDoer   — resumes group counseling wait after restart
    RegistryAcceptCompletionDoer — resumes registry-acceptance wait after restart (joiner)
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from hio.base import doing
from keri.app import grouping as keri_grouping
from keri.core import coring, serdering
from keri.peer import exchanging
from keri.vdr import credentialing as vdr_credentialing

from ...core import remoting
from ...db.basing import MultisigInitState

if TYPE_CHECKING:
    from locksmith.core.apping import LocksmithApplication

from keri import help

logger = help.ogler.getLogger(__name__)

_TOPIC_MULTISIG = "multisig"


def _distribute(app: "LocksmithApplication", others: list[str], sender_pre: str,
                 exn, atc, multisig_alias: str = "") -> None:
    """Send an EXN to every recipient via both the castellan relay and the
    standard KERI mailbox (best-effort — failures there are logged, not fatal).
    """
    raw = bytes(exn.raw) + bytes(atc)
    for recpt in others:
        asyncio.get_event_loop().create_task(
            remoting.post_message(app, recpt, _TOPIC_MULTISIG, raw,
                                   sender_aid=sender_pre, multisig_alias=multisig_alias)
        )
        try:
            app.vault.postman.send(src=sender_pre, dest=recpt, serder=exn, attachment=atc)
        except Exception as _e:
            logger.warning(f"Mailbox send failed for {recpt[:16]}...: {_e}")


# ---------------------------------------------------------------------------
# CastellanMessagePoller
# ---------------------------------------------------------------------------

class CastellanMessagePoller(doing.Doer):
    """
    Polls castellan /messages?topic=multisig and pipes raw CESR bytes into
    the vault parser so the Multiplexor can route them and create notifications.

    Must be registered as a vault doer via app.vault.extend([poller]).
    """

    def __init__(self, app: "LocksmithApplication", exc, tock: float = 10.0):
        self.app = app
        self.exc = exc
        self._kel_load_ready: bool = False
        super().__init__(tock=tock)
        logger.info("CastellanMessagePoller initialized")

    def mark_kel_load_ready(self):
        """Called once by UploadedIdentifierPoller after its first KEL-fetch cycle."""
        self._kel_load_ready = True
        logger.info("CastellanMessagePoller: initial KEL load confirmed, message processing enabled")

    def recur(self, tyme):
        asyncio.get_event_loop().create_task(self._poll())
        return False

    async def _poll(self):
        from keri.core import parsing

        db = self.app.vault.plugin_state.get("castellan", {}).get("db")
        identity = db.castellan_multisig_identity.get(keys=("self",)) if db else None
        castellan_aid = identity.chosen_identifier_aid if identity else None

        if not self._kel_load_ready:
            logger.debug("CastellanMessagePoller: waiting for initial KEL load before processing messages")
            return

        if not castellan_aid:
            return

        result = await remoting.fetch_messages(
            self.app, aid=castellan_aid, topic=_TOPIC_MULTISIG, unread_only=True
        )

        if not result.get("success"):
            logger.info(f"Failed to fetch messages: {result.get('error', 'Unknown error')}")
            return

        messages = result.get("messages", [])
        if not messages:
            return

        logger.info(f"Successfully fetched {len(messages)} messages")

        self.exc.processEscrow()
        self._drain_cues(pending_alias="")

        parser = parsing.Parser(
            kvy=self.app.vault.hby.kvy,
            rvy=self.app.vault.hby.rvy,
            exc=self.exc,
            local=False,
        )

        for msg in messages:
            raw_str = msg.get("raw", "")
            if not raw_str:
                continue
            try:
                raw = raw_str.encode("utf-8") if isinstance(raw_str, str) else raw_str
                parser.parse(ims=bytearray(raw), local=False)
                await remoting.mark_message_read(self.app, msg["id"])
                alias = msg.get("multisig_alias", "")
                self._drain_cues(pending_alias=alias)
            except Exception as e:
                logger.warning(f"Failed to process message {msg.get('id')}: {e}")

        # Re-process exchanger escrows after the full batch in case a peer KEL
        # arrived concurrently from the identifier poller during this poll cycle.
        self.exc.processEscrow()
        self._drain_cues(pending_alias="")

    def _drain_cues(self, pending_alias: str = ""):
        """Convert exchanger cues into new_notification Qt signals."""
        while self.exc.cues:
            cue = self.exc.cues.popleft()
            kin = cue.get("kin")

            if kin == "saved":
                said = cue.get("said", "")
                if not said:
                    continue

                exn = self.app.vault.hby.db.exns.get(keys=(said,))
                if exn is None:
                    logger.warning(f"Cue references exn said={said} but not found in db")
                    continue

                route = exn.ked.get("r", "")
                logger.info(f"Castellan exchanger saved exn: route={route} said={said}")

                signals = getattr(self.app.vault, "signals", None)
                if signals and hasattr(signals, "new_notification"):
                    signals.new_notification.emit({"r": route, "d": said, "multisig_alias": pending_alias})

            elif kin == "query":
                q = cue.get("q", {})
                logger.info(f"Castellan exchanger needs key state query: {q}")

            else:
                logger.debug(f"Castellan exchanger cue ignored: kin={kin}")


# ---------------------------------------------------------------------------
# GroupMultisigInceptDoer
# ---------------------------------------------------------------------------

class GroupMultisigInceptDoer(doing.DoDoer):
    """
    Initiates a group multisig inception and distributes the EXN via castellan
    messages and the standard KERI mailbox.
    """

    def __init__(self, app: "LocksmithApplication", alias: str, mhab,
                 smids: list[str], rmids: list[str] | None = None,
                 isith: str | int | None = None, nsith: str | int | None = None,
                 wits: list[str] | None = None, toad: int = 0,
                 signal_bridge=None, **kwargs):
        self.app = app
        self.hby = app.vault.hby
        self.alias = alias
        self.mhab = mhab
        self.smids = smids
        self.rmids = rmids if rmids is not None else smids
        self.isith = isith if isith is not None else str(len(smids))
        self.nsith = nsith if nsith is not None else self.isith
        self.wits = wits or []
        self.toad = toad
        self.signal_bridge = signal_bridge
        self.kwargs = kwargs
        self.counselor = app.vault.counselor
        super().__init__(doers=[doing.doify(self.incept_do)])

    def incept_do(self, tymth, tock=0.0, **opts):
        self.wind(tymth)
        self.tock = tock
        _ = (yield self.tock)

        try:
            if self.signal_bridge:
                self.signal_bridge.emit_doer_event(
                    "CastellanGroupMultisigInceptDoer", "group_inception_started",
                    {"alias": self.alias, "smids": self.smids},
                )

            self.app.vault.plugin_state.setdefault("castellan", {})["group_join_tracker"] = set()

            ghab = self.hby.makeGroupHab(
                group=self.alias,
                mhab=self.mhab,
                smids=self.smids,
                rmids=self.rmids,
                isith=self.isith,
                nsith=self.nsith,
                wits=self.wits,
                toad=self.toad,
                **self.kwargs,
            )
            icp = ghab.makeOwnInception(allowPartiallySigned=True)
            icp_serder = serdering.SerderKERI(raw=icp)

            exn, atc = keri_grouping.multisigInceptExn(
                hab=self.mhab,
                smids=self.smids,
                rmids=self.rmids,
                icp=icp,
            )

            others = [pre for pre in self.smids if pre != self.mhab.pre]
            _distribute(self.app, others, self.mhab.pre, exn, atc, multisig_alias=self.alias)

            if self.signal_bridge:
                self.signal_bridge.emit_doer_event(
                    "CastellanGroupMultisigInceptDoer", "group_inception_exn_sent",
                    {"alias": self.alias, "pre": ghab.pre, "recipients": others,
                     "smids": self.smids, "isith": str(self.isith), "nsith": str(self.nsith), "toad": str(self.toad)}
                )

            prefixer = coring.Prefixer(qb64=ghab.pre)
            seqner = coring.Seqner(sn=0)
            saider = coring.Saider(qb64=icp_serder.said)
            self.counselor.start(ghab=ghab, prefixer=prefixer, seqner=seqner, saider=saider)

            if self.signal_bridge:
                self.signal_bridge.emit_doer_event(
                    "CastellanGroupMultisigInceptDoer", "group_inception_waiting",
                    {"alias": self.alias, "pre": ghab.pre},
                )

            while not self.counselor.complete(prefixer, seqner):
                yield self.tock

            _others = {pre for pre in self.smids if pre != self.mhab.pre}

            while True:
                _confirmed = self.app.vault.plugin_state.get("castellan", {}).get(
                    "group_join_tracker", set()
                )
                if _others.issubset(_confirmed):
                    break
                yield self.tock

            logger.info(f"Group '{self.alias}' ({ghab.pre}) created successfully")
            if self.signal_bridge:
                self.signal_bridge.emit_doer_event(
                    "CastellanGroupMultisigInceptDoer", "group_identifier_created",
                    {"alias": self.alias, "pre": ghab.pre, "success": True},
                )

        except Exception as e:
            logger.exception(f"GroupMultisigInceptDoer failed: {e}")
            if self.signal_bridge:
                self.signal_bridge.emit_doer_event(
                    "CastellanGroupMultisigInceptDoer", "group_inception_failed",
                    {"alias": self.alias, "error": str(e), "success": False},
                )
        finally:
            self.app.vault.remove([self])
            return


# ---------------------------------------------------------------------------
# MultisigJoinDoer
# ---------------------------------------------------------------------------

class MultisigJoinDoer(doing.DoDoer):
    """
    Participant-side: joins a group icp proposal and sends the signed response
    via castellan messages and the standard KERI mailbox.
    """

    def __init__(self, app: "LocksmithApplication", alias: str, proposal_said: str,
                 mhab, signal_bridge=None):
        self.app = app
        self.hby = app.vault.hby
        self.alias = alias
        self.proposal_said = proposal_said
        self.mhab = mhab
        self.signal_bridge = signal_bridge
        self.counselor = app.vault.counselor
        super().__init__(doers=[doing.doify(self.join_do)])

    def join_do(self, tymth, tock=0.0, **opts):
        self.wind(tymth)
        self.tock = tock
        _ = (yield self.tock)

        try:
            exn, pathed = exchanging.cloneMessage(self.hby, said=self.proposal_said)
            if exn is None:
                raise ValueError(f"Proposal EXN not found: {self.proposal_said}")

            payload = exn.ked.get("a", {})
            smids = payload.get("smids", [])
            rmids = payload.get("rmids", smids)

            embeds = exn.ked.get("e", {})
            icp_sad = embeds.get("icp")
            if icp_sad is None:
                raise ValueError("No icp found in proposal embeds")
            oicp = serdering.SerderKERI(sad=icp_sad)

            from keri import kering
            inits = {
                "isith": oicp.ked["kt"],
                "nsith": oicp.ked["nt"],
                "estOnly": kering.TraitCodex.EstOnly in oicp.ked.get("c", []),
                "DnD": kering.TraitCodex.DoNotDelegate in oicp.ked.get("c", []),
                "toad": oicp.ked["bt"],
                "wits": oicp.ked["b"],
            }

            ghab = self.hby.makeGroupHab(
                group=self.alias, mhab=self.mhab,
                smids=smids, rmids=rmids, **inits,
            )
            own_icp = ghab.makeOwnInception(allowPartiallySigned=True)

            # Persist role and alias immediately so vault restart can resume
            # counseling via CounselingCompletionDoer (cannot rely on the
            # signal path for this).
            try:
                db = self.app.vault.plugin_state.get("castellan", {}).get("db")
                if db is not None:
                    _s = db.castellan_multisig_init.get(keys=(self.alias,)) or MultisigInitState(group_alias=self.alias)
                    _s.is_proposer = False
                    _s.group_isith = str(inits["isith"])
                    _s.group_nsith = str(inits["nsith"])
                    _s.group_toad = str(inits["toad"])
                    db.castellan_multisig_init.pin(keys=(self.alias,), val=_s)
            except Exception:
                pass

            own_serder = serdering.SerderKERI(raw=own_icp)

            resp_exn, resp_atc = keri_grouping.multisigInceptExn(
                hab=self.mhab, smids=smids, rmids=rmids, icp=own_icp,
            )

            others = [pre for pre in smids if pre != self.mhab.pre]
            _distribute(self.app, others, self.mhab.pre, resp_exn, resp_atc)

            prefixer = coring.Prefixer(qb64=ghab.pre)
            seqner = coring.Seqner(sn=0)
            saider = coring.Saider(qb64=own_serder.said)
            self.counselor.start(ghab=ghab, prefixer=prefixer, seqner=seqner, saider=saider)

            _smids = list(self.hby.db.signingMembers(pre=ghab.pre))

            if self.signal_bridge:
                self.signal_bridge.emit_doer_event(
                    "CastellanMultisigJoinDoer", "group_join_waiting",
                    {"alias": self.alias, "pre": ghab.pre, "smids": _smids,
                     "isith": str(inits["isith"]), "nsith": str(inits["nsith"]), "toad": str(inits["toad"])},
                )

            while not self.counselor.complete(prefixer, seqner):
                yield self.tock

            logger.info(f"Joined group '{self.alias}' ({ghab.pre})")
            if self.signal_bridge:
                self.signal_bridge.emit_doer_event(
                    "CastellanMultisigJoinDoer", "group_identifier_joined",
                    {"alias": self.alias, "pre": ghab.pre, "success": True},
                )

        except Exception as e:
            logger.exception(f"MultisigJoinDoer failed: {e}")
            if self.signal_bridge:
                self.signal_bridge.emit_doer_event(
                    "CastellanMultisigJoinDoer", "group_join_failed",
                    {"alias": self.alias, "error": str(e), "success": False},
                )
        finally:
            self.app.vault.remove([self])
            return


# ---------------------------------------------------------------------------
# CreateRegistryDoer
# ---------------------------------------------------------------------------

class CreateRegistryDoer(doing.DoDoer):
    """
    Initiates multisig registry creation (self-backed vcp + group ixn) and
    distributes the /multisig/vcp EXN to group members via castellan messages
    and the standard KERI mailbox.

    The registry is self-backed (noBackers=True, baks=[], toad=0) — castellan's
    registrar API no longer supports registering a new TEL registry or acting
    as a non-transferable backer, so there is no server-side registration step.

    Reuses the vault's counselor (app.vault.counselor) rather than creating
    a new one. Signals completion so the progress screen can advance.
    """

    def __init__(self, app: "LocksmithApplication", hab_alias: str,
                 registry_name: str, signal_bridge=None):
        self.app = app
        self.hby = app.vault.hby
        self.rgy = app.vault.rgy
        self.hab_alias = hab_alias
        self.registry_name = registry_name
        self.signal_bridge = signal_bridge
        self.counselor = app.vault.counselor
        super().__init__(doers=[doing.doify(self.create_do)])

    def create_do(self, tymth, tock=0.0, **opts):
        self.wind(tymth)
        self.tock = tock
        _ = (yield self.tock)

        try:
            hab = self.hby.habByName(self.hab_alias)
            if hab is None:
                raise ValueError(f"Identifier '{self.hab_alias}' not found")

            existing_registry = self.rgy.registryByName(self.registry_name)

            if existing_registry is not None:
                # Restart path: registry was persisted in a prior session.
                # Skip creation and IXN; go straight to completion polling.
                registry = existing_registry
                registrar = vdr_credentialing.Registrar(
                    hby=self.hby, rgy=self.rgy, counselor=self.counselor
                )
                self.extend([registrar])
                logger.info(
                    f"CreateRegistryDoer: '{self.registry_name}' already exists "
                    f"— resuming completion wait"
                )
            else:
                # Fresh creation path — self-backed registry.
                from keri.app.habbing import GroupHab
                registry = self.rgy.makeRegistry(
                    name=self.registry_name,
                    prefix=hab.pre,
                    noBackers=True,
                    baks=[],
                    toad=0,
                    nonce=coring.randomNonce(),
                )

                regd = getattr(registry, "regd", registry.regk)
                rseal = {"i": registry.regk, "s": "0", "d": regd}
                anc = hab.interact(data=[rseal])
                aserder = serdering.SerderKERI(raw=bytes(anc))

                registrar = vdr_credentialing.Registrar(
                    hby=self.hby, rgy=self.rgy, counselor=self.counselor
                )
                self.extend([registrar])
                registrar.incept(iserder=registry.vcp, anc=aserder)

                if self.signal_bridge:
                    self.signal_bridge.emit_doer_event(
                        "CastellanCreateRegistryDoer", "registry_inception_started",
                        {"name": self.registry_name, "regk": registry.regk},
                    )

                # For GroupHab: broadcast /multisig/vcp EXN via castellan + mailbox
                if isinstance(hab, GroupHab):
                    try:
                        exn, atc = keri_grouping.multisigRegistryInceptExn(
                            ghab=hab,
                            vcp=registry.vcp.raw,
                            anc=anc,
                            usage=f"Registry: {self.registry_name}",
                        )
                        smids = self.hby.db.signingMembers(pre=hab.pre)
                        others = [pre for pre in smids if pre != hab.mhab.pre]
                        _distribute(self.app, others, hab.mhab.pre, exn, atc)
                    except Exception as e:
                        logger.warning(f"Failed to send /multisig/vcp EXN: {e}")

            # Shared completion path (both fresh and restart)
            while not registrar.complete(pre=registry.regk, sn=0):
                self.rgy.processEscrows()
                yield self.tock

            self.remove([registrar])

            logger.info(f"Registry '{self.registry_name}' created: {registry.regk}")
            if self.signal_bridge:
                self.signal_bridge.emit_doer_event(
                    "CastellanCreateRegistryDoer", "registry_created",
                    {"name": self.registry_name, "regk": registry.regk, "success": True},
                )

        except Exception as e:
            logger.exception(f"CreateRegistryDoer failed: {e}")
            if self.signal_bridge:
                self.signal_bridge.emit_doer_event(
                    "CastellanCreateRegistryDoer", "registry_creation_failed",
                    {"name": self.registry_name, "error": str(e), "success": False},
                )
        finally:
            self.app.vault.remove([self])
            return


# ---------------------------------------------------------------------------
# RegistryAcceptDoer
# ---------------------------------------------------------------------------

class RegistryAcceptDoer(doing.DoDoer):
    """
    Participant-side: accepts a /multisig/vcp registry proposal by co-signing
    the group interaction event and sending the response via castellan
    messages and the standard KERI mailbox.
    """

    def __init__(self, app: "LocksmithApplication", proposal_said: str,
                 mhab, signal_bridge=None):
        self.app = app
        self.hby = app.vault.hby
        self.rgy = app.vault.rgy
        self.proposal_said = proposal_said
        self.mhab = mhab
        self.signal_bridge = signal_bridge
        self.counselor = app.vault.counselor
        super().__init__(doers=[doing.doify(self.accept_do)])

    def accept_do(self, tymth, tock=0.0, **opts):
        self.wind(tymth)
        self.tock = tock
        _ = (yield self.tock)

        try:
            exn, pathed = exchanging.cloneMessage(self.hby, said=self.proposal_said)
            if exn is None:
                raise ValueError(f"VCP proposal EXN not found: {self.proposal_said}")

            embeds = exn.ked.get("e", {})
            vcp_sad = embeds.get("vcp")
            anc_sad = embeds.get("anc")
            if vcp_sad is None or anc_sad is None:
                raise ValueError("Missing vcp or anc in /multisig/vcp embeds")

            vcp_serder = serdering.SerderKERI(sad=vcp_sad)

            payload = exn.ked.get("a", {})
            gid = payload.get("gid", "")

            ghab = self.hby.habs.get(gid) or self.hby.habByName(gid)

            # Guard: ensure our own group inception has finalized (sn=0 in cgms) before
            # we attempt to create sn=1 group IXN. Needed in N-party setups where the
            # proposer may send /multisig/vcp before all joiners have cleared their
            # inception escrow.
            _inc_prefixer = coring.Prefixer(qb64=ghab.pre)
            _inc_seqner = coring.Seqner(sn=0)

            while not self.counselor.complete(_inc_prefixer, _inc_seqner):
                yield self.tock

            if ghab is None:
                raise ValueError(f"Group hab not found for gid {gid[:16]}...")

            usage = payload.get("usage", "")
            _reg_name = usage.removeprefix("Registry: ") if usage.startswith("Registry: ") else (
                vcp_serder.ked.get("i", self.proposal_said[:16]))

            # Create the same self-backed registry locally.
            registry = self.rgy.makeRegistry(
                name=_reg_name,
                prefix=ghab.pre,
                noBackers=True,
                baks=[],
                toad=0,
                nonce=vcp_serder.ked.get("n", coring.randomNonce()),
            )

            # Co-sign the group ixn
            regd = getattr(registry, "regd", registry.regk)
            rseal = {"i": registry.regk, "s": "0", "d": regd}
            own_anc = ghab.interact(data=[rseal])
            own_anc_serder = serdering.SerderKERI(raw=bytes(own_anc))

            registrar = vdr_credentialing.Registrar(
                hby=self.hby, rgy=self.rgy, counselor=self.counselor
            )
            self.extend([registrar])
            registrar.incept(iserder=registry.vcp, anc=own_anc_serder)

            # Send our signed response via castellan + mailbox
            resp_exn, resp_atc = keri_grouping.multisigRegistryInceptExn(
                ghab=ghab,
                vcp=registry.vcp.raw,
                anc=own_anc,
                usage=f"Registry: {registry.regk[:16]}",
            )
            smids = self.hby.db.signingMembers(pre=ghab.pre)
            others = [pre for pre in smids if pre != self.mhab.pre]
            _distribute(self.app, others, self.mhab.pre, resp_exn, resp_atc)

            if self.signal_bridge:
                self.signal_bridge.emit_doer_event(
                    "CastellanRegistryAcceptDoer", "registry_accept_waiting",
                    {"regk": registry.regk, "own_aid": self.mhab.pre},
                )

            while not registrar.complete(pre=registry.regk, sn=0):
                self.rgy.processEscrows()
                yield self.tock

            self.remove([registrar])

            logger.info(f"Accepted and completed registry {registry.regk}")
            if self.signal_bridge:
                self.signal_bridge.emit_doer_event(
                    "CastellanRegistryAcceptDoer", "registry_accepted",
                    {"regk": registry.regk, "success": True},
                )

        except Exception as e:
            logger.exception(f"RegistryAcceptDoer failed: {e}")
            if self.signal_bridge:
                self.signal_bridge.emit_doer_event(
                    "CastellanRegistryAcceptDoer", "registry_accept_failed",
                    {"error": str(e), "success": False},
                )
        finally:
            self.app.vault.remove([self])
            return


# ---------------------------------------------------------------------------
# Restart-resume doers
# ---------------------------------------------------------------------------

class CounselingCompletionDoer(doing.DoDoer):
    """
    Resumes waiting for counselor completion after vault restart.

    Created by CastellanPlugin.on_vault_opened() for any group whose inception
    escrow (db.gpse) was still open when the vault was closed. Emits the same
    signal as the original doer so initiate.py advances identically to the
    non-restart path.
    """

    def __init__(self, app: "LocksmithApplication", prefixer, seqner, ghab,
                 is_proposer: bool):
        self.app = app
        self.counselor = app.vault.counselor
        self.prefixer = prefixer
        self.seqner = seqner
        self.ghab = ghab
        self.is_proposer = is_proposer
        super().__init__(doers=[doing.doify(self.complete_do)])

    def complete_do(self, tymth, tock=0.0, **opts):
        self.wind(tymth)
        self.tock = tock
        _ = (yield self.tock)

        while not self.counselor.complete(self.prefixer, self.seqner):
            yield self.tock

        logger.info(
            f"CounselingCompletionDoer: counseling complete for "
            f"'{self.ghab.name}' ({'proposer' if self.is_proposer else 'joiner'})"
        )

        signals = getattr(self.app.vault, "signals", None)
        if signals:
            if self.is_proposer:
                signals.emit_doer_event(
                    "CastellanGroupMultisigInceptDoer", "group_identifier_created",
                    {"alias": self.ghab.name, "pre": self.ghab.pre, "success": True},
                )
            else:
                signals.emit_doer_event(
                    "CastellanMultisigJoinDoer", "group_identifier_joined",
                    {"alias": self.ghab.name, "pre": self.ghab.pre, "success": True},
                )

        try:
            self.app.vault.remove([self])
        except Exception:
            pass
        return


class RegistryAcceptCompletionDoer(doing.DoDoer):
    """Resumes waiting for registry acceptance completion after vault restart (joiner)."""

    def __init__(self, app, registry, signal_bridge=None):
        self.app = app
        self.registry = registry
        self.rgy = app.vault.rgy
        self.counselor = app.vault.counselor
        self.signal_bridge = signal_bridge
        super().__init__(doers=[doing.doify(self.complete_do)])

    def complete_do(self, tymth, tock=0.0, **opts):
        self.wind(tymth)
        self.tock = tock
        _ = (yield self.tock)
        registrar = vdr_credentialing.Registrar(hby=self.app.vault.hby, rgy=self.rgy, counselor=self.counselor)
        self.extend([registrar])
        while not registrar.complete(pre=self.registry.regk, sn=0):
            self.rgy.processEscrows()
            yield self.tock
        self.remove([registrar])

        signals = getattr(self.app.vault, "signals", None)
        if signals:
            signals.emit_doer_event(
                "CastellanRegistryAcceptDoer", "registry_accepted",
                {"regk": self.registry.regk, "success": True},
            )
        try:
            self.app.vault.remove([self])
        except Exception:
            pass
        return
