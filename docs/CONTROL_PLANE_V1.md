# Control Plane v1 — Normative Specification

Status: 0.1.0-dev foundation.

## Purpose

The control plane routes durable tasks to persistent agents without binding a Scheduled Task slot to a specific agent. It separates identity/state (agent home Context Capsule), immutable task intent, global execution ownership, execution evidence, and disposable Chat runtime.

The control plane itself has no agent identity, mandate, opinions, or professional memory.

## Entities

Agent: Registry record keyed by stable agent_id with home repository, authority ref, entrypoint and automatic-execution flag.

Task Request: tasks/<task_id>/request.json. Immutable after creation. It contains issuer, target agent, objective, authority basis, scope, constraints, target, priority, dependencies and completion contract. A request cannot expand an agent's mandate.

Task State: tasks/<task_id>/state.json. Recoverable mutable projection. States: queued, claimed, active, waiting, blocked, quarantined, completed, cancelled, superseded. It is not ownership authority.

Execution: one materialization of a target persistent agent for one task, identified by execution_id and global generation.

Lease: runtime/lease.json. Sole atomic ownership record. V1 permits exactly one active autonomous execution.

Checkpoint: immutable file under tasks/<task_id>/checkpoints/. Contains completed externally meaningful steps, verified evidence and next action, never private chain-of-thought.

Gate: reserved entity for a later stage; not active in the foundation.

Dependency: V1 hard relation depends_on. Envelope also reserves workflow_id, parent_task_id and relation for later DAG templates.

## READY computation

A task is READY only when request/state validate, request digest matches, state=queued, target agent exists and is executable, automatic_execution_allowed=true, every dependency exists and is completed, and the graph is acyclic.

Selection is deterministic: effective priority descending, creation time ascending, task_id lexical ascending.

Base priority: critical=400, high=300, normal=200, low=100. Anti-starvation aging adds one band per seven full waiting days, capped at critical.

The production Registry intentionally disables automatic execution for all agents until later integration.

## GitHub CAS ownership

GitHub Contents API blob SHA is the compare-and-swap token.

Claim protocol:
1. fetch lease and remember its blob SHA;
2. require idle;
3. compute generation+1 and unique execution_id;
4. use GitHub time-pulse protocol when scheduling is activated;
5. CAS-write lease using the exact previously read blob SHA;
6. GitHub 409 means another slot won: stop;
7. re-fetch and verify lease;
8. update task projection to claimed;
9. reinstate target agent;
10. after invocation/authority validation, mark task active.

Lease is written first. A crash before task-state update is repaired from the authoritative lease.

## Fencing

Ownership token is (task_id, agent_id, execution_id, generation).

Before every consequential write, the autonomous runtime re-reads lease and requires exact token equality. Task state alone never proves ownership.

Recovery advances generation before requeue, so a late zombie runtime fails its next fence check.

## Checkpoint and recovery

Checkpoint before long waits and after meaningful durable progress.

Expired-runtime recovery order:
1. establish authoritative current time;
2. fence first: CAS active(g=N) -> idle(g=N+1);
3. increment task runtime_loss_count;
4. requeue while retaining latest_checkpoint;
5. at v1 threshold 3, quarantine instead.

If a crash occurs between fence and task update, later reconciliation repairs the stale task projection.

Resume:
1. choose latest valid immutable checkpoint;
2. reinstate same target agent_id from Registry;
3. execute its Context Capsule recovery protocol;
4. reconcile current GitHub/target evidence;
5. treat checkpoint as starting evidence, not a freshness exemption;
6. continue only within mandate and immutable task scope.

## Authoritative time

When dispatcher scheduling is activated, expiry/renewal uses GitHub commit time, not model/local-clock guesses.

runtime/time-pulse.json provides: CAS pulse write -> fetch exact pulse commit -> commit.committer.date.

Time pulse never grants ownership; lease CAS does.

## Failure/reconciliation rules

- active lease + queued task projection: repair projection to claimed;
- idle/fenced lease + stale claimed/active projection: clear stale ownership projection;
- request digest mismatch: never execute;
- unknown/disabled agent: not READY;
- missing dependency: not READY;
- dependency cycle: validation failure;
- GitHub CAS conflict: re-read; never force overwrite;
- stale execution: no consequential write after fence mismatch.

## Delegation, responsibility, and authority hardening

New executable agent-to-agent tasks use responsibility semantics version 2.

Responsibility, authority, and execution ownership are independent. An execution lease never transfers commitment ownership or authority.

For bounded delegation, the issuer remains commitment owner and return target.

For explicit handoff, the issuer remains the current commitment owner until the target Agent durably accepts the proposed transfer in its own authoritative state. ACP may store `state.json#responsibility_acceptance` only as a request-bound evidence projection of that Agent-state transition. The projection itself grants no authority.

Nested delegation preserves root authority provenance and may only attenuate authority: child allowed effects are a subset, inherited forbidden effects and constraints are retained, and a parent may forbid subdelegation entirely.

Historical terminal responsibility-v1 artifacts remain readable. Nonterminal agent-to-agent execution requires responsibility semantics version 2.
