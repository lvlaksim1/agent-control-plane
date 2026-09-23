# Five-slot shared dispatcher pool

The pool contains five identical Scheduled Chat workers offset by 12 minutes within each hour.

| slot | minute |
| --- | ---: |
| dispatcher-00 | 00 |
| dispatcher-12 | 12 |
| dispatcher-24 | 24 |
| dispatcher-36 | 36 |
| dispatcher-48 | 48 |

The pool does **not** create five agent runtimes in parallel. All workers reconcile the same queue and the same public transactional gateway lease. Exactly one target-agent execution may hold that lease.

## Wake semantics

A slot invocation performs one bounded reconciliation cycle and at most one target-agent task. If the global lease is already held, it may only perform protocol-defined recovery for that exact execution; otherwise it exits without starting another agent.

Five hourly clocks therefore reduce average autonomous wake latency while respecting the user's plan limit and the one-runtime invariant.

## Human interaction

The pool is irrelevant to direct interactive chats. Owner ↔ Project Manager, Owner ↔ Auditor, Owner ↔ Supervisor, and Owner ↔ future Specialists remain direct entry points.

## Gateway requirement

The lease gateway must serialize concurrent requests without dropping pending workflows. Its GitHub Actions concurrency group therefore uses `queue: max`; the lease state machine itself still accepts at most one active claim.

## Admission test

Before treating the pool as operational:

1. all five scheduler objects must carry the same protocol revision, differing only by slot_id and schedule;
2. two or more near-simultaneous probe claims must produce one accepted active lease and rejected/no-op competitors, with no duplicate target write;
3. after release, the gateway must return idle at a newer generation;
4. no dispatcher may mutate another dispatcher schedule;
5. no project target is used for the concurrency probe.
