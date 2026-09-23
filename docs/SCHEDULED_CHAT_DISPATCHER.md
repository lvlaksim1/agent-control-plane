# Scheduled Chat Dispatcher Protocol

The Dispatcher is infrastructure, not a persistent agent.

Each run is a reconciliation loop:

1. Read this protocol, Registry, global lease, task requests/states/gates/runtime metadata. For each task, GitHub's current blob SHA of `request.json` must equal `state.request_blob_sha`; this is the runtime immutability check. `request_digest` remains an offline deterministic validation field and Scheduled Chat does not need to recompute it.
2. Runtime lease authority is `lvlaksim1/agent-control-plane-gateway@main:runtime/lease.json`. The private `runtime/lease.json` is no longer runtime authority. Lease transitions are requested by creating a `[ACP_LEASE]` issue in the gateway with the exact JSON operation; the gateway serializes transitions in GitHub Actions and commits the lease before reporting acceptance.
3. If the lease is active and not proven expired, exit without claiming another task.
4. If an active lease is proven expired, fence it first by CAS (generation N -> idle generation N+1), then repair/requeue/quarantine the task projection.
5. Compute READY deterministically: queued, retry window elapsed, all gates satisfied, dependencies completed, target agent executable and automatic_execution_allowed.
6. Select one task by effective priority, age, then task_id.
7. Read the authoritative gateway lease. If idle, create one `[ACP_LEASE]` Issue with operation `claim`, opaque task/agent IDs, unique execution_id, slot_id, current request_blob_sha and lease_minutes.
8. Read the gateway Issue result and authoritative lease. Continue only if the gateway reports `accepted:true` and the committed lease exactly matches task_id + agent_id + execution_id + request_blob_sha. A denied claim means another dispatcher owns the runtime; stop.
9. Gateway generation returned by the accepted claim is the execution fencing generation.
10. CAS-update private task state to claimed with the exact gateway execution_id/generation, then re-fetch it. **Do not reinstate the agent and do not perform any target write unless this claimed projection is durably visible and matches the authoritative gateway lease.** If this state write fails, request an exact gateway `release` and stop.
11. Only then reinstate the existing target agent from Registry home_repository@authority_ref and run its ENTRYPOINT protocol.
12. The target agent validates task authority against its own mandate. Task delivery and tool access never create authority.
13. Mark active only after successful reinstantiation/authority validation.
14. Before every consequential write, re-fetch the authoritative gateway lease and require exact task_id + agent_id + execution_id + generation + request_blob_sha.
15. Write immutable checkpoints after meaningful durable progress.
16. On execution failure, fence/release first, then apply retry/backoff/quarantine policy.
17. Completion requires verified evidence satisfying completion_contract. While the gateway lease is still active: write result.json bound to request_digest + request_blob_sha + execution_id + generation; CAS-update and re-read task state as completed; **only after completed state is durable** request an exact gateway `release` and verify the committed gateway lease is idle at a newer generation.
18. At the start of every run, reconcile completed-result drift before READY: if the authoritative gateway lease is idle and a valid result.json exists but task state is not completed, verify result/gates and repair task state to completed. Such a task must never be selected again.
19. Do not manually start a dependent task; the next dispatcher run recomputes READY.
20. Persist a bounded infrastructure heartbeat to `runtime/dispatcher-health.json` using CAS: observed control-plane HEAD, slot_id, run outcome, and dispatch timestamp. This heartbeat grants no task ownership.
21. If no READY task exists, record `no-ready-work` in the heartbeat and exit.

A Dispatcher may execute at most one target-agent execution per scheduled invocation. It must never combine identities from different agents in one run.

Runtime result binding: `result.json.request_blob_sha` must equal the immutable `state.request_blob_sha`. This lets Scheduled Chat verify request identity directly from GitHub metadata while the offline validator still enforces canonical `request_digest`.

## Gateway trust boundary

The public gateway is a transactional lock service only. It never sees objectives, target repositories, completion evidence, mandates, Context Capsules, or project content. READY selection and authority validation remain private/control-plane responsibilities.
