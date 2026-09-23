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
9. Re-fetch the lease and verify ownership before updating task projection.
10. Mark task claimed, then reinstate the existing target agent from Registry home_repository@authority_ref and run its ENTRYPOINT protocol.
11. The target agent validates task authority against its own mandate. Task delivery and tool access never create authority.
12. Mark active only after successful reinstantiation/authority validation.
13. Before every consequential write, re-fetch lease and require exact task_id + agent_id + execution_id + generation.
14. Write immutable checkpoints after meaningful durable progress.
15. On execution failure, fence/release first, then apply retry/backoff/quarantine policy.
16. Completion requires verified evidence satisfying completion_contract. Persist result, then complete task and release/fence the lease.
17. Do not manually start a dependent task; the next dispatcher run recomputes READY.
18. If no READY task exists, exit quietly.

A Dispatcher may execute at most one target-agent execution per scheduled invocation. It must never combine identities from different agents in one run.
