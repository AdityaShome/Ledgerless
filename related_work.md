# Related work

Each entry says how this project differs. Items marked (verify) are named in the project guide
and have not been checked against the source; confirm details and add full citations before
publication.

- **Temporal and durable execution for LLM agents.** One control plane keeps a readable event
  history and replays workflow code from it, giving exactly-once-style behavior inside one
  organization. We assume no shared control plane or readable log across organizations, so we
  recover from minimal signed evidence at each hop. Our benchmark's Temporal system is an
  in-process stand-in and is labelled an upper bound.
- **LangGraph durable execution.** Checkpoints graph state so a run resumes after failure, inside
  one deployment. It does not address a remote organization whose effect may or may not have run.
  (verify against current docs)
- **SagaLLM.** Compensation and consistency inside one orchestrator that sees all steps. Our Saga
  baseline models this and shows its limits: it duplicates when hops do not dedup, and it cannot
  undo an in-doubt effect it cannot see. (verify)
- **Microsoft AgentMesh.** Trust and quarantine between agents. It is about whether to trust a
  peer, not about recovering a chain after a failure. We use quarantine only as a safe outcome
  of `decide()`. (verify)
- **Durable authorization state for replay-resistant agent actions (arXiv 2608.01710).** Closest in
  spirit: persisting state so replays are not re-authorized. We add receipts and a cross-
  organization resolve RPC. (verify; read the paper before claiming a difference)
- **April 2026 paper on non-deterministic node output and non-idempotent retry in agent
  workflows.** Motivates the re-planning problem (our F5). Still to be found and cited.
- **A2ABreak.** Notes that A2A has no chain identifier. We add a `chain_id` in intent metadata.
  (verify)
- **Strabo.** Observes that the A2A state machine is informally specified. Our TLA+ model covers
  only the recovery protocol, not the whole A2A state machine. (verify)
- **Classical roots.** Chandy-Lamport snapshots (consistent global state without a coordinator),
  two-phase commit in-doubt resolution (ask the coordinator what happened; our `resolveIntent` asks
  the executor instead), and sagas (Garcia-Molina and Salem, compensating transactions).
