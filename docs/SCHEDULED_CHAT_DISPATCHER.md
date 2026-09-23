# Scheduled Chat Execution Worker Protocol

The scheduler uses two infrastructure automations:

1. one reusable one-shot **Execution Worker**; and
2. one recurring **Wake Broker / Hourly Watchdog**.

Direct Owner↔agent conversations remain first-class and do not use scheduler transport. A wake changes only *when* work is reconsidered. It never grants authority.

## Why the relay exists

Live validation showed that a one-shot Scheduled Task can race with its own completion if it tries to re-arm itself while the current invocation is still active. Re-enabling an expired one-shot may also be delivered as an immediate catch-up run rather than exactly at the requested future DTSTART.

Therefore the Execution Worker **must never schedule itself**.

Continuation uses a cross-task relay:

```
durable work/wake
      ↓
Wake Broker / Watchdog
      ↓
arms Execution Worker
      ↓
Execution Worker
      ↓
if continuation is needed:
persist new wake → nudge Broker → STOP
```

The Broker may run immediately or near the requested time; correctness never depends on exact wall-clock delivery. The only required semantic boundary is that Phase B occurs in a later Execution Worker invocation.

## Entry reconciliation

At every Execution Worker invocation use a **lease-first fast path**:

1. read `runtime/dispatcher-config.json`, `runtime/dispatcher-pool.json`, `runtime/dispatcher-health.json`, Registry, and the authoritative gateway lease;
2. validate wake state and capture the exact `armed_generation` that caused this invocation as `invocation_generation`; never treat a newer unarmed desired generation as served;
3. if the gateway is `reserved` or `active`, fetch only the exact referenced task request/state/runtime/gates plus contract files needed to reconcile that execution;
4. reconcile that exact execution before considering a new claim;
5. only when the gateway is idle may the worker scan queued task states and compute READY deterministically;
6. execute at most one bounded control-plane cycle.

## Two-phase target execution

**A gateway reservation/activation never authorizes target execution in the same Execution Worker invocation.**

### Phase A — reserve and activate, then stop

1. Require gateway idle and deterministically select at most one READY task.
2. Request gateway `claim`; successful claim must commit `reserved`.
3. CAS-write private task state to `claimed` with exact execution_id, generation, slot_id=`execution-worker`, claimed_at and request_blob_sha; re-read.
4. Capture the claimed-state Git blob SHA.
5. Request gateway `activate` with the exact fence plus `activation_projection_blob_sha`.
6. Proceed only if canonical gateway lease is `active` and records that exact receipt.
7. Record the same activation receipt in the private claim and re-read.
8. Persist a deterministic durable wake keyed by the activated execution because Phase B requires a later Execution Worker invocation.
9. Nudge the Wake Broker / Watchdog by scheduling that separate recurring automation for a near-future run while preserving its hourly RRULE; verify it remains enabled.
10. Mark only `invocation_generation` served.
11. **STOP. Do not reinstate the target agent and do not perform target writes.**

The Worker never writes `armed_generation`; only the Broker may acknowledge that a worker generation was actually scheduled.

If the Broker nudge fails, leave the durable wake pending. Its hourly cadence is the guaranteed recovery path.

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
5. if another durable reason for progress exists, persist a new wake and nudge the Broker;
6. mark only `invocation_generation` served;
7. stop.

A Worker invocation never schedules the Worker itself.

## Wake transport contract

Wake state is `runtime/dispatcher-health.json#wake`.

- `desired_generation`: latest requested wake;
- `armed_generation`: latest generation the Broker has successfully scheduled on the Worker;
- `served_generation`: latest armed generation actually reconciled by a Worker invocation.

Invariant:

`served_generation <= armed_generation <= desired_generation`.

Wake requests use deterministic `request_key` values. Recent keys suppress replay.

## Wake Broker / Hourly Watchdog

The Broker never executes target-agent work and never claims a gateway lease.

It runs in two modes using the same recurring automation:

- **event nudge**: another infrastructure/client runtime moves its next occurrence earlier after persisting a durable wake;
- **hourly watchdog**: the RRULE guarantees eventual recovery if the nudge or worker delivery is lost.

Each Broker run:

1. reconcile Registry, task/gate/runtime metadata, wake state and authoritative gateway lease;
2. detect READY work, due retry, partial reserved/active transitions, stale/lost wake delivery, or protocol-defined lease recovery;
3. create a deterministic durable wake if work exists but no sufficient wake is pending;
4. if `desired_generation > armed_generation`, or an already-armed unserved generation is stale, schedule the existing Execution Worker for a one-shot run and set `is_enabled=true`;
5. verify the returned scheduler state names the exact Worker and is enabled for a runnable one-shot occurrence; exact wall-clock timing is not a correctness assumption;
6. only then persist the matching `armed_generation` and `last_armed_at`;
7. otherwise no-op.

The Broker never updates its own schedule while it is executing.

## Event producers

After an authorized runtime creates a durable wake it MAY nudge the Broker for fast delivery by moving the Broker's next occurrence earlier while preserving its recurring hourly schedule. If it cannot do so safely, it leaves the wake pending for the next hourly Broker run.

An event producer must never schedule the Execution Worker directly. This keeps all worker arming serialized through one Broker role.

## Recovery

- reserved + queued: Worker repairs the same task to claimed, activates it, records the receipt, requests Phase-B wake, nudges Broker, then stops;
- reserved + claimed: Worker activates from the exact current claimed projection, records receipt, requests Phase-B wake, nudges Broker, then stops;
- active + claimed without locally recorded receipt: Worker verifies canonical receipt against the exact historical claimed-state blob, records it, requests Phase-B wake if necessary, nudges Broker, then stops;
- expired reserved/active lease: fence before requeue/quarantine, then request recovery wake if progress is possible;
- completed task with valid result and idle gateway: repair completion projection only; never execute twice.

## Authority and routing

Supervisor is not a mandatory gateway. Owner or a registered active agent may issue a task only with the required authority basis. Target-side mandate validation is always required. Wake delivery, scheduler identity, Registry membership, lease reservation or tool access never expand authority.
