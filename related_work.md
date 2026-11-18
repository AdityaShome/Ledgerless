# Related work

Status of each entry: **found** means the paper exists and the description below matches its
abstract or search summary; I have not read any paper in full, so check details against the paper
before publication. **unchecked** means not yet looked up.

- **Temporal and durable execution for LLM agents.** (unchecked, well-known) One control plane
  keeps a readable event history and replays workflow code from it, giving exactly-once-style
  behavior inside one organization. We assume no shared control plane or readable log across
  organizations, so we recover from minimal signed evidence at each hop. Our benchmark's Temporal
  system is an in-process stand-in and is labelled an upper bound.
- **LangGraph durable execution.** (unchecked) Checkpoints graph state so a run resumes after
  failure, inside one deployment. It does not address a remote organization whose effect may or
  may not have run. Verify against current docs.
- **SagaLLM** (Chang and Geng, arXiv 2503.11951, PVLDB 18, 2025). (found) Adds saga-style
  compensating transactions, context management and validation agents to multi-agent LLM planning
  inside one orchestrator. Our Saga baseline models the orchestrator-with-full-view idea and shows
  its limits: it duplicates when hops do not dedup, and it cannot undo an in-doubt effect it
  cannot see. We do not model SagaLLM's validation or context agents.
- **Microsoft AgentMesh.** (unchecked) Described in the guide as trust quarantine, not recovery.
  We use quarantine only as a safe outcome of `decide()`.
- **Beyond Single-Use Tokens: Durable Authorization State for Replay-Resistant LLM Agent
  Actions** (arXiv 2608.01710, Aug 2026). (found) Argues that single-use tokens are not enough:
  an agent can get a fresh authorization for a semantically equivalent action ("semantic replay"),
  so the issuer must keep durable state over the action and its execution budget (their system:
  CapLease, compared with a stateful server ledger). This is the closest prior work to our F5
  and digest idea. Differences to check against the paper: it keeps state at an issuer, we keep
  signed evidence at each executing organization and add a cross-organization resolve call; our
  digest dedup is keyed on the intended effect, theirs on the authorization.
- **From Agent Loops to Structured Graphs** (arXiv 2604.11378, Apr 2026). (found, likely the
  April 2026 paper named in the guide; not confirmed) Reported to formalize three problems that
  classical workflow engines did not face: non-deterministic node output, reasoning failures as an
  error mode, and non-idempotent retry. Motivates our re-planning scenario (F5). Confirm this is
  the intended paper and read its retry section.
- **Where Does Exactly-Once Live?** (arXiv 2609.29095, Sep 2026). (found, newly discovered, not
  in the guide) Studies duplicate side effects in LLM agents under retry using a hidden effect
  ledger, across model, harness and tool contract. Directly relevant to our duplicate-effect
  metric. Read before claiming novelty.
- **A2ABreak: Systematic Security Analysis of the A2A Protocol** (arXiv 2609.10871, 2026).
  (found) Builds a finite-state model of the A2A lifecycle and reports eleven protocol-level
  weaknesses; secondary commentary says the protocol lacks a delegation context or chain-of-custody
  primitive. We add a `chain_id` in intent metadata, as an extension and not a core change.
- **Strabo: Declarative Specification and Implementation of Agentic Interaction Protocols**
  (arXiv 2606.05043, 2026). (found) States that A2A is mostly informally specified, with
  ambiguities such as whether a canceled task can resume, and proposes bridging it to a declarative
  protocol language. It does not verify A2A. Our TLA+ model covers only the recovery protocol,
  not the A2A state machine.
- **Classical roots.** Chandy-Lamport snapshots (consistent global state without a coordinator),
  two-phase commit in-doubt resolution (ask the coordinator what happened; our `resolveIntent` asks
  the executor instead), and sagas (Garcia-Molina and Salem, compensating transactions).
