# Agent Control Plane

Durable GitHub control plane for the owner's persistent-agent ecosystem.

This repository is **infrastructure, not an agent**. It has no Project Manager or Service Agent identity and intentionally has no Context Capsule of its own.

## Runtime boundary

Intended execution model:

ordinary ChatGPT Scheduled Task -> GitHub control plane -> reinstate target persistent agent from its home Context Capsule -> execute bounded task -> persist evidence

Constraints:

- ordinary Chat only;
- no ChatGPT Work dependency;
- no OpenAI API dependency;
- no always-on local PC/browser;
- GitHub is the durable coordination/state substrate;
- persistent agent identity and memory remain in each agent's home repository;
- tool access never grants authority.

This repository currently implements foundation plan items 1–8 only. No Scheduled Task is connected yet and all registered agents have automatic execution disabled.

## Implemented foundation

1. Control Plane v1 specification and state machines.
2. Dedicated private infrastructure repository.
3. Agent Registry v1 with Supervisor, Context Capsule PM, and Auditor.
4. Immutable Task Request contract protected by a digest stored in mutable task state.
5. Deterministic dependency graph / READY selection with cycle rejection, priority aging, FIFO tie-breaks.
6. Global GitHub-CAS ownership lease: one autonomous runtime maximum.
7. Fencing token (generation + execution_id) checked before consequential writes.
8. Immutable checkpoints plus deterministic stale-runtime recovery and quarantine threshold.

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
- runtime/lease.json is the only atomic ownership record.
- Claim persistence order is lease CAS first, task projection second.
- Recovery persistence order is fence first, task requeue/quarantine second.
- GitHub 409 Conflict on lease update means claim loss; the caller stops.
- Before a consequential write, re-read the lease and verify task_id, agent_id, execution_id, and generation.
- Checkpoints contain durable facts/evidence and next action, never hidden chain-of-thought.
- Recovery reinstates the same agent_id from its authoritative home repository and reconciles live target state.
- A task envelope cannot expand the target agent's mandate.

## Validation

tools/control_plane.py is a deterministic repository validator/planner, not the production runtime. Validation can be run from an external GitHub-hosted validation job when this private repository has no assignable hosted runner.

python3 tools/control_plane.py validate --root .
python3 -m unittest discover -s tests -v

There is intentionally no OS/Python matrix and no always-on CI requirement: the control plane itself is GitHub state plus the ordinary-Chat protocol.
