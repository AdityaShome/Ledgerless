"""In-process chain simulator running the real recovery library over a faulty network.

Systems are configurations of one engine (see SystemConfig), so baselines and ablations share
every other code path. Synchronous and seeded: same (config, plan, seed) gives the same run.
"""

from __future__ import annotations

import dataclasses
import json
import random
from dataclasses import dataclass, field

from agents.tools.fake_tools import TOOL_KINDS, FakeTool
from agents.toy_llm_agent import HopSpec, PlannedRequest, ToyLLMAgent
from bench.faults import Crash, FaultPlan, FaultState
from recovery.crypto import generate_keypair, sha256_hex
from recovery.decide import Action, Evidence, decide
from recovery.intents import DigestPolicy, Granularity, Intent, compute_digest
from recovery.receipts import Receipt, make_receipt, verify_receipt
from recovery.service import RecoveryService
from recovery.store import Store, StoreConflict


@dataclass(frozen=True)
class SystemConfig:
    name: str
    dedup: str = "none"  # none | request_id | digest
    resolve: bool = False  # on timeout: resolveIntent + decide()
    verify_receipts: bool = False
    reconcile: bool = False  # replicas union receipts before executing
    granularity: Granularity = Granularity.MEDIUM
    max_retries: int = 3
    resolve_tries: int = 3


DEFAULT_SDK = SystemConfig("default_sdk")
REQUEST_ID = SystemConfig("request_id", dedup="request_id")
OURS = SystemConfig("ours", dedup="digest", resolve=True, verify_receipts=True, reconcile=True)

POLICY = DigestPolicy(medium_keys=("amount",))


@dataclass
class Response:
    ok: bool
    receipt: Receipt | None = None
    status: str = "ok"
    children: list[Response] = field(default_factory=list)


@dataclass
class RunResult:
    system: str
    scenario: str
    seed: int
    intended: int
    duplicates: int
    missing: int
    completed: bool
    quarantined: bool
    alerts: int
    messages: int
    bytes_total: int
    recovery_bytes: int
    resolves: int
    replans: int
    replay_decisions: int
    victim: str

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


@dataclass
class Replica:
    store: Store
    svc: RecoveryService


class Hop:
    def __init__(self, spec: HopSpec, world: World):
        self.spec = spec
        self.world = world
        self.tool = FakeTool(spec.tool)
        self.priv, self.pub = generate_keypair()
        self.replicas = [
            Replica(s, RecoveryService(s, self.priv, spec.name)) for s in (Store(), Store())
        ]

    def process(self, req: PlannedRequest, intent: Intent | None, replica_idx: int) -> Response:
        w, cfg = self.world, self.world.cfg
        rep = self.replicas[replica_idx]
        executed = False
        receipt: Receipt | None = None
        status = "ok"

        if cfg.dedup == "digest":
            assert intent is not None
            if cfg.reconcile:
                for other in self.replicas:
                    if other is not rep:
                        try:
                            rep.store.merge_from(other.store)
                        except StoreConflict:
                            pass
            state, receipt = rep.svc.begin(intent)
            if state == "refused":
                return Response(False, receipt, "refused")
            if state == "proceed":
                ref = self.tool.apply(self.spec.target, self.spec.amount)
                receipt = rep.svc.commit(intent, ref, intent.parent_receipt)
                executed = True
            else:
                status = "done"
        elif cfg.dedup == "request_id":
            existing = rep.store.get_receipt(req.req_id)
            if existing is not None:
                receipt, status = existing, "done"
            else:
                ref = self.tool.apply(self.spec.target, self.spec.amount)
                receipt = make_receipt(
                    self.priv, req.req_id, sha256_hex(req.req_id.encode()), "committed", ref, None
                )
                rep.store.put_receipt(w.chain_id, receipt)
                executed = True
        else:
            self.tool.apply(self.spec.target, self.spec.amount)
            executed = True

        if executed and w.faults.fire("crash_after_effect", self.spec.name):
            rep.svc.abandon(req.req_id)
            raise Crash()

        children: list[Response] = []
        for child in self.spec.children:
            resp = w.call(w.hops[child], receipt.hash if receipt else None)
            children.append(resp)
            if not resp.ok:
                return Response(False, receipt, "child_failed", children)
        return Response(True, receipt, status, children)


class World:
    def __init__(
        self,
        cfg: SystemConfig,
        plan: FaultPlan,
        seed: int,
        depth: int = 3,
        fanout: int = 1,
        scenario: str = "",
    ):
        self.cfg, self.plan, self.seed, self.scenario = cfg, plan, seed, scenario
        self.rng = random.Random(seed)
        self.chain_id = f"chain-{seed}"
        self.agent = ToyLLMAgent(random.Random(seed * 7919 + 1), plan.p_replan)
        self.hops: dict[str, Hop] = {}
        self.order: list[str] = []
        self._build(depth, fanout)
        self.faults = FaultState(plan, victim=self.rng.choice(self.order))
        self.messages = 0
        self.bytes_total = 0
        self.recovery_bytes = 0
        self.resolves = 0
        self.alerts = 0
        self.quarantined = False

    # -- topology: a chain of `depth` hops; fanout > 1 gives the root `fanout` branches
    def _build(self, depth: int, fanout: int) -> None:
        specs: list[HopSpec] = []

        def spec(name: str, i: int, children: tuple[str, ...]) -> HopSpec:
            return HopSpec(name, TOOL_KINDS[i % 4], f"target-{name}", 10 + i, children)

        branches = []
        for b in range(fanout):
            names = [f"h{d}.{b}" for d in range(1, depth)]
            for d, n in enumerate(names):
                nxt = (names[d + 1],) if d + 1 < len(names) else ()
                specs.append(spec(n, d + 1 + b, nxt))
            if names:
                branches.append(names[0])
        specs.append(spec("h0", 0, tuple(branches)))
        for s in specs:
            self.hops[s.name] = Hop(s, self)
        self.order = [s.name for s in specs]

    # -- messaging
    def _count(self, nbytes: int, recovery: int = 0) -> None:
        self.messages += 1
        self.bytes_total += nbytes
        self.recovery_bytes += recovery

    def _route(self, attempt: int) -> int:
        return attempt % 2 if self.plan.failover else 0

    def _intent(self, req: PlannedRequest, parent_hash: str | None) -> Intent | None:
        if self.cfg.dedup != "digest":
            return None
        spec = self.hops[req.hop].spec
        digest = compute_digest(
            spec.tool, spec.target, req.params, POLICY, self.cfg.granularity
        )
        return Intent(req.req_id, self.chain_id, parent_hash, digest, "t")

    def _net(self, hop: Hop, req: PlannedRequest, intent: Intent | None, attempt: int):
        body = len(json.dumps(req.params))
        rec = len(json.dumps(intent.to_dict())) if intent else 0
        self._count(body + rec, rec)
        idx = self._route(attempt)
        try:
            resp = hop.process(req, intent, idx)
            if self.faults.fire("dup_request", hop.spec.name):
                self._count(body + rec, rec)
                hop.process(req, intent, idx)
        except Crash:
            return None
        if self.faults.fire("drop_response", hop.spec.name):
            return None
        if resp.receipt is not None and self.faults.fire("forge_receipt", hop.spec.name):
            bad = dataclasses.replace(resp.receipt, effect_ref="forged")
            resp = dataclasses.replace(resp, receipt=bad)
        rrec = len(json.dumps(resp.receipt.to_dict())) if resp.receipt else 0
        self._count(8 + rrec, rrec)
        return resp

    def _resolve(self, hop: Hop, req: PlannedRequest, intent: Intent, attempt: int):
        self.resolves += 1
        self._count(120, 120)
        if self.faults.resolve_blocked(hop.spec.name):
            return None
        rep = hop.replicas[self._route(attempt + 1)]
        if self.cfg.reconcile:
            for other in hop.replicas:
                if other is not rep:
                    try:
                        rep.store.merge_from(other.store)
                    except StoreConflict:
                        pass
        res = rep.svc.resolve(self.chain_id, intent.intent_id, intent.digest)
        self._count(60 + len(json.dumps(res)), len(json.dumps(res)))
        return res

    def _resolve_action(self, hop: Hop, req, intent, attempt: int) -> Action:
        decide(Evidence(intent_declared=True, callee_reachable=True))  # -> RESOLVE
        tries = 0
        while True:
            tries += 1
            last = tries >= self.cfg.resolve_tries
            res = self._resolve(hop, req, intent, attempt)
            if res is None:
                ev = Evidence(intent_declared=True, callee_reachable=False, timed_out=last)
            elif res["state"] == "unknown":
                ev = Evidence(intent_declared=True, resolve_unknown=True, timed_out=last)
            else:
                r = Receipt.from_dict(res["receipt"])
                ev = Evidence(
                    receipt=r, signature_valid=verify_receipt(r, hop.pub), intent_declared=True
                )
            act = decide(ev)
            if act is not Action.WAIT:
                return act

    def call(self, hop: Hop, parent_hash: str | None) -> Response:
        """Caller-side logic for one downstream hop, including retries."""
        cfg, spec = self.cfg, hop.spec
        req = self.agent.next(self.chain_id, spec)
        for attempt in range(cfg.max_retries + 1):
            intent = self._intent(req, parent_hash)
            resp = self._net(hop, req, intent, attempt)
            if resp is not None:
                forged = (
                    cfg.verify_receipts
                    and resp.receipt is not None
                    and not verify_receipt(resp.receipt, hop.pub)
                )
                if forged:
                    self.alerts += 1
                    self.quarantined = True
                    return Response(False, status="alert")
                return resp
            # timeout / crash: nothing known about the remote effect
            if cfg.resolve and intent is not None:
                act = self._resolve_action(hop, req, intent, attempt)
                if act is Action.RESUME:
                    req = self.agent.original(self.chain_id, spec)
                elif act is Action.REPLAY:
                    req = self.agent.replay(self.chain_id, spec)
                else:  # QUARANTINE / QUARANTINE_ALERT
                    self.quarantined = True
                    if act is Action.QUARANTINE_ALERT:
                        self.alerts += 1
                    return Response(False, status="quarantine")
            else:
                req = self.agent.replay(self.chain_id, spec)
        return Response(False, status="gave_up")

    def run(self) -> RunResult:
        root = self.hops["h0"]
        resp = self.call(root, None)
        dup = sum(h.tool.duplicates() for h in self.hops.values())
        missing = sum(1 for h in self.hops.values() if not h.tool.effects)
        return RunResult(
            system=self.cfg.name,
            scenario=self.scenario,
            seed=self.seed,
            intended=len(self.hops),
            duplicates=dup,
            missing=missing,
            completed=resp.ok and self._all_ok(resp),
            quarantined=self.quarantined,
            alerts=self.alerts,
            messages=self.messages,
            bytes_total=self.bytes_total,
            recovery_bytes=self.recovery_bytes,
            resolves=self.resolves,
            replans=self.agent.replans,
            replay_decisions=self.agent.replay_decisions,
            victim=self.faults.victim,
        )

    @staticmethod
    def _all_ok(resp: Response) -> bool:
        return resp.ok and all(World._all_ok(c) for c in resp.children)


def run_one(
    cfg: SystemConfig, scenario: str, plan: FaultPlan, seed: int, depth: int = 3, fanout: int = 1
) -> RunResult:
    return World(cfg, plan, seed, depth, fanout, scenario).run()
