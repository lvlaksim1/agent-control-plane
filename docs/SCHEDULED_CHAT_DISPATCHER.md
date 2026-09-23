# Scheduled Chat Execution Worker Protocol

The scheduler uses one reusable one-shot Execution Worker plus one hourly Watchdog. Both are infrastructure, not persistent agents. Direct Owner↔agent conversations remain first-class and do not use scheduler transport.

A wake changes only *when* work is reconsidered. It never grants authority.

## Entry reconciliation

At every Execution Worker invocation:

1. read `runtime/dispatcher-config.json`, `runtime/dispatcher-pool.json`, `runtime/dispatcher-health.json`, Registry, task requests/states/gates/runtime metadata, and the authoritative gateway lease;
2. validate the current wake state and capture `desired_generation`;
3. reconcile partial transitions and any exact existing gateway lease before selecting new work;
4. execute at most one bounded control-plane cycle.

## Two-phase target execution

**A gateway reservation/activation never authorizes target execution in the same invocation.**

### Phase A — reserve and activate, then stop

1. Require gateway idle and deterministically select at most one READY task.
2. Request gateway `claim`; successful claim must commit `reserved`.
3. CAS-write private task state to `claimed` with exact execution_id, generation, slot_id=`execution-worker`, claimed_at and request_blob_sha; re-read.
4. Capture the claimed-state Git blob SHA.
5. Request gateway `activate` with the exact fence plus `activation_projection_blob_sha`.
6. Proceed only if canonical gateway lease is `active` and records that exact receipt.
7. Record the same activation receipt in the private claim and re-read.
8. Persist a new durable wake request keyed by this exact activated execution, because Phase B must occur in a later invocation.
9. Re-arm the same Execution Worker for a future one-shot run using the configured minimum delay and set `is_enabled=true`; verify both the future schedule and enabled state before recording the corresponding armed generation.
10. Mark the current wake generation served.
11. **STOP. Do not reinstate the target agent and do not perform target writes.**

If re-arm fails, leave the durable wake pending. The hourly Watchdog must recover it.

### Phase B — execute in a later invocation

A later Execution Worker may begin target-agent reinstantiation only when:

- gateway state is `active`;
- private task state is `claimed`;
- private claim contains `activation_projection_blob_sha`;
- gateway and private claim exactly match task_id + target agent_id + execution_id + generation + slot_id + request_blob_sha + activation_projection_blob_sha.

Then:

1. reinstate the existing target agent from Registry home_repository@authority_ref and execute its ENTRYPOINT protocol;
2. target agent validates issuer, authority provenance, target identity, objective, scope, constraints, requested effects and completion contract against its own mandate;
3. CAS-update private task state to `active`;
4. before every consequential target/control-plane write require the exact active fence/receipt match;
5. persist immutable checkpoints after meaningful durable progress;
6. if execution exceeds the lease window, renew only while the exact fence remains valid;
7. on execution failure, fence/release first, then apply retry/backoff/quarantine policy.

## Completion

While the exact active fence remains valid:

1. write `result.json` exactly to `runtime/dispatcher-write-contract.json`;
2. CAS-update task state to `completed` with `claim=null`; re-read;
3. only after durable completion request exact gateway release and verify canonical gateway idle at a newer generation;
4. recompute READY/recovery state;
5. if another durable reason for progress exists, persist a new wake request and re-arm the Execution Worker;
6. mark the current wake generation served;
7. stop.

A worker invocation never re-arms itself merely because it ran.

## Wake transport contract

Wake state is `runtime/dispatcher-health.json#wake`.

- `desired_generation`: latest requested wake;
- `armed_generation`: latest successfully scheduled wake;
- `served_generation`: latest wake reconciled by a worker invocation.

Wake requests use deterministic `request_key` values. Recent keys suppress replay.

Re-arm ordering is mandatory:

1. durable wake request;
2. scheduler update of the existing Execution Worker with a future one-shot schedule and `is_enabled=true`;
3. verify the worker is enabled and scheduled in the future;
4. durable armed-generation acknowledgement.

Duplicate invocation is safe because task state and the gateway lease remain authoritative.

## Hourly Watchdog

The Watchdog never executes target-agent work.

Each hourly run:

1. reconcile Registry, tasks, gates, runtime metadata, wake state and authoritative gateway lease;
2. detect READY work, due retries, stale/lost wake delivery, or protocol-defined lease recovery;
3. create a durable wake request if needed;
4. if desired > armed, or an outstanding armed generation is stale, re-arm the Execution Worker;
5. record the matching armed generation after successful scheduler update;
6. otherwise no-op.

The Watchdog is the guaranteed slow recovery path; event wake is the normal fast path.

## Recovery

- reserved + queued: repair the same task to claimed, activate, request Phase-B wake, then stop;
- reserved + claimed: activate from exact current claimed projection, request Phase-B wake, then stop;
- active + claimed without locally recorded receipt: verify canonical receipt against a valid historical claimed-state blob, record it, request Phase-B wake if necessary, then stop;
- expired reserved/active lease: fence before requeue/quarantine, then request a recovery wake if progress is possible;
- completed task with valid result and idle gateway: repair completion projection only; never execute twice.

## Authority and routing

Supervisor is not a mandatory gateway. Owner or a registered active agent may issue a task only with the required authority basis. Target-side mandate validation is always required. Wake delivery, scheduler identity, Registry membership, lease reservation or tool access never expand authority.
