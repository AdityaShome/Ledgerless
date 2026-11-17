# Ledgerless

**Recovery Without the Log: consistent recovery of cross-organization A2A delegation chains under non-deterministic re-execution.**

Ledgerless is a research project and reference implementation for recovering failed multi-agent task chains when no party can read the full execution log.

## The problem

In a cross-organization [A2A](https://a2a-protocol.org) chain (A → B → C), each organization sees only its own hop. When a hop fails:

- The upstream agent cannot tell whether a downstream side effect (a payment, an email, a booking) actually committed.
- Replaying an LLM agent may choose a different action, so request-level idempotency keys no longer match and the effect can run twice.
- Server replicas of the same agent can hold divergent task state, with no shared store.

Existing recovery approaches (Temporal, LangGraph durable execution, SagaLLM) assume one control plane with a readable log. Ledgerless targets recovery under **partial log observability** and **non-deterministic re-execution**.

## The idea

Recover from minimal, signed commit evidence exchanged between hops. Never from internal logs.

1. **Write-ahead intents.** Before any side effect, the executor declares an intent in A2A task metadata (`x-recovery`). The intent carries a digest of the semantically relevant fields (`action_type`, `target`, key params). Executors dedup on `(chain_id, digest)`, not on request ID, so a re-planned request for the same effect is recognised.
2. **Hash-chained effect receipts.** After commit, the executor returns an Ed25519-signed receipt. Receipts link through `prev`, so the latest verifiable receipt per hop is a consistent cut. `effect_ref` is an opaque ID and leaks no internal state.
3. **In-doubt resolution RPC.** A new JSON-RPC method, `recovery/resolveIntent`, returns `committed`, `tombstone` or `unknown`. A tombstone is a durable guarantee that the intent will never execute.
4. **Decision rule.** A pure function `decide(evidence) -> Action`:

| Evidence | Action |
|---|---|
| Valid receipt | resume past it |
| Tombstone | replay |
| Intent declared, no receipt, callee reachable | call `resolveIntent`, decide again |
| Intent declared, callee unreachable past timeout | quarantine |
| Receipt present, upstream aborted | compensate |
| Invalid receipt signature | quarantine and alert |

Safety properties: a committed receipt is never forgotten, and an intent never executes twice. Replicas reconcile by taking the union of receipts and resolving open intents.

## Research questions

- **RQ1.** Does request-ID idempotency fail under LLM re-planning on replay, and how often?
- **RQ2.** Do write-ahead intents plus effect receipts eliminate duplicate and lost effects across hops?
- **RQ3.** What does it cost in latency, message overhead and bytes disclosed per hop?
- **RQ4.** How does intent-digest granularity trade false dedup against missed dedup?

Claims under test (not assumed): C1 request-ID dedup duplicates grow with re-plan probability; C2 zero duplicate and zero lost effects on faults F1–F6; C3 correctness matches a single-control-plane Temporal upper bound without sharing one; C4 overhead stays under a stated bound. Failed claims will be reported as such.

## Status

| Phase | Scope | State |
|---|---|---|
| 0 | Repo skeleton, pinned deps, CI | Done |
| 1 | TLA+ model and TLC checking | Done (see caveats in `formal/results.md`) |
| 2 | Core library: crypto, intents, receipts, store, `decide` | Done, 30 tests |
| 3 | A2A integration: middleware, `resolveIntent`, agents A → B → C over HTTP | Next |
| 4 | Fault injection (F1–F7) and toy re-planning agents | Planned |
| 5 | Baselines: default SDK, request-ID idempotency, saga, Temporal (upper bound) | Planned |
| 6 | Experiments and results | Planned |
| 7 | Write-up support | Planned |

No experimental results exist yet. The only checked results so far are the formal-model runs in `formal/results.md`.

## Repository layout

```
recovery/    core library (crypto, intents, receipts, store, decide); no LLM calls
formal/      TLA+ spec, TLC configs, model notes and results
agents/      toy re-planning agent and fake side-effecting tools (planned)
bench/       fault injection, scenarios, runner, metrics (planned)
baselines/   comparison systems (planned)
tests/       pytest suite
results/     experiment outputs (planned)
DECISIONS.md design choices not covered by the guide
a2a-recovery-agent-guide.md  full project specification
```

## Quick start

Requires Python 3.11+.

```
python -m venv .venv
.venv\Scripts\activate          # Windows; use source .venv/bin/activate elsewhere
pip install -e ".[dev]"
ruff check .
pytest
```

### Model checking

Requires Java 17+ and `tla2tools.jar` placed in `tools/` (not committed). From `formal/`:

```
java -cp ../tools/tla2tools.jar tlc2.TLC -config A2ARecovery.cfg A2ARecovery.tla          # intents: invariants hold
java -cp ../tools/tla2tools.jar tlc2.TLC -config A2ARecovery_live.cfg A2ARecovery.tla     # liveness
java -cp ../tools/tla2tools.jar tlc2.TLC -config A2ARecovery_nointents.cfg A2ARecovery.tla # baseline: finds a duplicate effect
```

## Scope and non-goals

- No Byzantine fault tolerance. Organizations may crash or lose messages but sign honestly; forged receipts are detected, not tolerated.
- No changes to core A2A message types. The extension uses message metadata and one new RPC, with no fork of the A2A SDK.
- No production key management (file-based keys) and no GUI.

## Related work

Temporal and durable execution for agents, LangGraph durable execution, SagaLLM, Microsoft AgentMesh, A2ABreak, Strabo, and the classical roots: Chandy-Lamport snapshots, two-phase-commit in-doubt resolution and sagas. A per-item comparison will live in `related_work.md`.
