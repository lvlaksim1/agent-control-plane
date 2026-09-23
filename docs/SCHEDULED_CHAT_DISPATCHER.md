# Scheduled Chat Dispatcher Protocol

The Dispatcher is infrastructure, not a persistent agent.

Each run is a reconciliation loop:

1. Read this protocol, Registry, global lease, task requests/states/gates/runtime metadata.
2. Use GitHub server/commit time when an expiry decision is required; never guess time from model memory.
3. If the lease is active and not proven expired, exit without claiming another task.
4. If an active lease is proven expired, fence it first by CAS (generation N -> idle generation N+1), then repair/requeue/quarantine the task projection.
5. Compute READY deterministically: queued, retry window elapsed, all gates satisfied, dependencies completed, target agent executable and automatic_execution_allowed.
6. Select one task by effective priority, age, then task_id.
7. Fetch runtime/lease.json and retain its exact blob SHA.
8. CAS-write the lease first with generation+1, unique execution_id, target agent and slot. A 409 means another Dispatcher won; stop.
9. Re-fetch the lease and verify ownership.
10. CAS-update task state to claimed with the exact execution_id/generation, then re-fetch it. **Do not reinstate the agent and do not perform any target write unless this claimed projection is durably visible and matches the lease.** If this state write fails, release/fence the lease and stop.
11. Only then reinstate the existing target agent from Registry home_repository@authority_ref and run its ENTRYPOINT protocol.
11. The target agent validates task authority against its own mandate. Task delivery and tool access never create authority.
12. Mark active only after successful reinstantiation/authority validation.
13. Before every consequential write, re-fetch lease and require exact task_id + agent_id + execution_id + generation.
15. Write immutable checkpoints after meaningful durable progress.
16. On execution failure, fence/release first, then apply retry/backoff/quarantine policy.
17. Completion requires verified evidence satisfying completion_contract. While the lease is still active: write result.json bound to request_digest + execution_id + generation; CAS-update and re-read task state as completed; **only after completed state is durable** release/fence the lease.
18. At the start of every run, reconcile completed-result drift before READY: if lease is idle and a valid result.json exists but task state is not completed, verify result/gates and repair task state to completed. Such a task must never be selected again.
19. Do not manually start a dependent task; the next dispatcher run recomputes READY.
20. Persist a bounded infrastructure heartbeat to `runtime/dispatcher-health.json` using CAS: observed control-plane HEAD, slot_id, run outcome, and dispatch timestamp. This heartbeat grants no task ownership.\n21. If no READY task exists, record `no-ready-work` in the heartbeat and exit.

A Dispatcher may execute at most one target-agent execution per scheduled invocation. It must never combine identities from different agents in one run.
