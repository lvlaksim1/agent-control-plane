# Agent Control Plane

Durable GitHub control plane for the owner's persistent-agent ecosystem.

This repository is **infrastructure, not an agent**. It has no Project Manager or Service Agent identity and intentionally has no Context Capsule of its own.

## Runtime boundary

Intended execution model:

durable wake -> reusable Scheduled Chat Execution Worker -> GitHub control plane -> reinstate target persistent agent from its home Context Capsule -> execute bounded task -> persist evidence

Constraints:

- ordinary Chat only;
- no ChatGPT Work dependency;
- no OpenAI API dependency;
- no always-on local PC/browser;
- GitHub is the durable coordination/state substrate;
- persistent agent identity and memory remain in each agent's home repository;
- tool access never grants authority.

This repository has proven items 1–19, including real persistent Project Manager → Auditor routing and Context Capsule interoperability. Direct Owner↔agent conversations remain first-class and do not use scheduler transport.

## Implemented foundation

1. Control Plane v1 specification and state machines.
2. Dedicated private infrastructure repository.
3. Agent Registry v1 with Supervisor, Context Capsule PM, and Auditor.
4. Immutable Task Request contract protected by a digest stored in mutable task state.
5. Deterministic dependency graph / READY selection with cycle rejection, priority aging, FIFO tie-breaks.
6. Global GitHub-CAS ownership lease: one autonomous runtime maximum.
7. Fencing token (generation + execution_id) checked before consequential writes.
8. Immutable checkpoints plus deterministic stale-runtime recovery and quarantine threshold.
9. Execution-failure retry/backoff/quarantine metadata.
10. Explicit durable Gate engine.
11. Deterministic persistent-agent invocation package.
12. Evidence-backed completion verifier.
13. Automatic DAG continuation through READY recomputation.

## Repository layout

registry/agents.json — persistent-agent routing registry
runtime/lease.json — sole atomic runtime ownership record
runtime/time-pulse.json — GitHub-time anchoring record
tasks/<task_id>/request.json — immutable task intent
tasks/<task_id>/state.json — recoverable mutable projection
tasks/<task_id>/checkpoints/ — immutable checkpoints
schemas/ — machine-readable contracts
tools/control_plane.py — deterministic validator/planner; no network access
tests/ — pure state-machine regressions
docs/ — normative protocol

## Critical invariants

- request.json is immutable after task creation. state.json.request_digest detects mutation.
- The authoritative runtime lease is the public transactional `lvlaksim1/agent-control-plane-gateway@main:runtime/lease.json`; private `runtime/lease.json` is retained only as the original foundation reference.
- Claim persistence order is lease CAS first, task projection second.
- Recovery persistence order is fence first, task requeue/quarantine second.
- GitHub 409 Conflict on lease update means claim loss; the caller stops.
- Before a consequential write, re-read the lease and verify task_id, agent_id, execution_id, and generation.
- Checkpoints contain durable facts/evidence and next action, never hidden chain-of-thought.
- Recovery reinstates the same agent_id from its authoritative home repository and reconciles live target state.
- A task envelope cannot expand the target agent's mandate.

## Validation

`tools/control_plane.py` is a deterministic repository validator/planner, not the production runtime.

This repository is private and must not spend the account's private GitHub-hosted Actions minutes. Its exact-commit verification is therefore executed by the public `lvlaksim1/repo-factory` workflow `Verify Private Repository`.

The verification profile for this repository runs:

```
python -m compileall -q tools
python -m unittest discover -s tests
```

The verifier accepts only an exact 40-character commit SHA and the allowlisted `agent-control-plane` profile. No Actions artifacts or cache are uploaded.

There is intentionally no private-repository GitHub-hosted CI workflow here.
\n## Workflow runtime\n\n`tools/workflow_runtime.py` extends the foundation state machine without changing the authority of `runtime/lease.json`. It adds retry/backoff, gates, reinstantiation packages, completion evidence, and DAG continuation. The scheduled dispatcher must follow `docs/SCHEDULED_CHAT_DISPATCHER.md`.\n
## Transactional gateway

Live Scheduled Chat E2E showed that direct private-repository lease acquisition can be declined by the Scheduled Chat tool safety layer. The solution does not weaken fencing: an isolated public GitHub Actions gateway now performs only serialized lease state transitions. It stores no private task content. The Chat runtime requests claim/release and verifies the committed lease before acting.


## Proven real-agent integration

The strict workflow `WF-REAL-PM-AUDITOR-002` proved:

- the existing Context Capsule Project Manager can be reinstantiated by a dispatcher and execute a bounded read-only task;
- a committed gateway claim can survive Scheduled Chat runtime loss and be resumed with the same execution token;
- strict result envelopes and terminal `claim=null` are enforced;
- the Project Manager can issue a dependent task directly to the persistent Auditor without Supervisor as issuer;
- the Auditor can reinstate independently, verify the PM evidence read-only, publish its own audit evidence, and complete under the same fencing rules;
- direct human project-development chat remains separate from autonomous dispatcher latency.


## Event-driven scheduler redesign

The Owner-authorized pre-scaling scheduler redesign is complete and independently verified.

Production topology:

- one reusable **hourly-anchored Execution Worker** whose next occurrence may be retargeted earlier by the Broker;
- one **Wake Broker / Hourly Watchdog** that performs event delivery and recovery but never target-agent work;
- durable wake generations in `runtime/dispatcher-health.json#wake`;
- the authoritative gateway lease, two-phase activation, fencing, immutable task intent, mandate validation, and evidence-backed completion remain preserved;
- interactive-first routing is task-scoped: a fresh live carrier blocks only its own scheduler-visible task/chain, while unrelated autonomous work remains schedulable;
- expired live-carried queued work is result-aware before fallback: an exact valid pre-expiry live success repairs to terminal completed state instead of executing twice, while absent/invalid/mismatched/post-expiry results retain legitimate fallback and unverifiable result chronology fails closed.

Independent closure evidence:

- EW-001..EW-003 — CLOSED / High confidence;
- PTC-001..PTC-003 — CLOSED / High confidence;
- final focused report: `project-manager-auditor/audits/AUD-2026-09-24-PTC-002-RETEST-002.md`.

See `docs/DISPATCHER_POOL.md` and `docs/SCHEDULED_CHAT_DISPATCHER.md`.

Agent Catalog / Agent Factory / item 20 remain out of scope and inactive.

## Fixed Agent runtime identity

Persistent Agent identity is now runtime-affine: one live or Scheduled Chat runtime carries at most one persistent `agent_id`.

For Agent-to-Agent work:

- responsibility/authority remains semantics version 2;
- a different target Agent requires `runtime:separate-target` and a fresh target runtime;
- interactive bounded delegation uses `continuation:manual-pull` by default, leaving the verified child result durable in GitHub for later caller inspection;
- autonomous continuation uses `continuation:automatic-new-runtime` plus a precreated dependency-bound `runtime:caller-continuation` task, so the caller resumes in a later fresh Worker runtime;
- explicit handoff remains distinct and creates no implicit caller return;
- historical pending live-return continuation objects remain recovery-compatible, but they may be consumed only by a fresh Worker runtime bound to the recorded caller, never by changing identity inside the current runtime.

Every user-visible Agent/infrastructure message follows the Moscow-time source header contract in `docs/RUNTIME_IDENTITY_AND_USER_MESSAGES.md`. The header is diagnostic only; repository-backed reinstantiation remains identity authority.

This mechanism does not make Supervisor a mandatory dispatcher and does not affect unrelated autonomous scheduler work.
