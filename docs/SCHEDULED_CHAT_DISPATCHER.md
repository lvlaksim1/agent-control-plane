# Scheduled Chat Execution Worker Protocol

The scheduler uses two infrastructure automations:

1. one reusable hourly-anchored **Execution Worker** whose next occurrence may be retargeted earlier; and
2. one recurring **Wake Broker / Hourly Watchdog**.

Direct Owner↔agent conversations remain first-class and do not use scheduler transport. A wake changes only *when* work is reconsidered. It never grants authority.

## Per-task live-carrier gate

There is no global interactive shutdown.

For every candidate task, read and validate its `runtime.json#carrier` before scheduler claim or Phase-B target reinstantiation:

- fresh `mode=live` carrier lease → this task is not scheduler-eligible;
- expired `mode=live` with `fallback_after_expiry=true` → this task becomes scheduler-eligible;
- `mode=hold` → this task remains blocked until its carrier is explicitly cleared;
- `carrier=null` → normal scheduler eligibility.

A live carrier on TASK-A must never block unrelated TASK-B. The Broker and Worker remain operational while the Owner is online and may continue other autonomous work.

For the task currently carried by the live Owner runtime, continuation is immediate and scheduler-free:

```
live Owner runtime
      ↓
persist task / engagement in GitHub
      ↓
record/renew TASK-specific live carrier
      ↓
reinstantiate the next persistent agent directly
in the same live runtime
```

If that live runtime disappears, its task becomes eligible after the carrier lease expires. This is a continuity fallback, not a scheduled delay in the interactive path.

## Why the relay exists

Live validation showed two scheduler hazards: self-rearming a currently running one-shot can race with completion, and repeatedly reusing an already-fired one-shot can leave a newly requested occurrence enabled but undelivered for an unbounded interval. Therefore v4 uses a recurring hourly Worker as a stable scheduler anchor; only the Broker may retarget its next occurrence earlier, and the hourly RRULE must be preserved.

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

The Broker or Worker may run late or as catch-up delivery; correctness never depends on exact wall-clock delivery. Live validation also showed that a Worker can start before a Broker performs a post-scheduler acknowledgement, so the Broker must commit the delivery generation **before** scheduling the Worker. The required semantic boundary is a later Execution Worker invocation plus the exact durable fence.

## Entry reconciliation

At every Execution Worker invocation use a **lease-first fast path**. A natural hourly Worker occurrence is not permission to scan for work: if the gateway is idle and there is no `armed_generation > served_generation`, stop after the wake/gateway check without scanning task bundles.


1. read `runtime/dispatcher-config.json`, `runtime/dispatcher-pool.json`, `runtime/dispatcher-health.json`, Registry, and the authoritative gateway lease;
2. validate wake state and capture the exact `armed_generation` that caused this invocation as `invocation_generation`; never treat a newer unarmed desired generation as served;
3. if the gateway is `reserved` or `active`, fetch only the exact referenced task request/state/runtime/gates plus contract files needed to reconcile that execution;
4. reconcile that exact execution before considering a new claim;
5. when the gateway is idle, first inspect the captured wake's `last_request.request_key`; if it has the exact form `task-ready:<task_id>`, fetch that task's request/state/runtime/gates, validate its per-task carrier, and select it only when it is queued, READY, and scheduler-eligible;
6. only if no exact wake-addressed scheduler-eligible READY task is available may the worker scan other queued tasks, excluding only tasks with fresh live carriers or explicit holds;
7. execute at most one bounded control-plane cycle.

## Authoritative gateway requests

The deployed lease authority is `lvlaksim1/agent-control-plane-gateway@main`. Before a claim/activate/renew/release/recover request, read its current `runtime/lease.json` and gateway `README.md`.

Submit a gateway transition by creating one Issue in that repository with exact title `[ACP_LEASE]` and a complete JSON body. The workflow serializes accepted transitions and commits canonical lease state before reporting success.

Required bodies:

- claim: `{"operation":"claim","task_id":"...","agent_id":"...","execution_id":"...","slot_id":"execution-worker","request_blob_sha":"<40-char blob>","lease_minutes":45}`
- activate: `{"operation":"activate","task_id":"...","agent_id":"...","execution_id":"...","generation":N,"request_blob_sha":"<40-char blob>","activation_projection_blob_sha":"<40-char claimed-state blob>"}`
- renew: exact owner fields plus `{"operation":"renew","lease_minutes":45}`
- release: exact owner fields plus `{"operation":"release"}`
- recover_expired: `{"operation":"recover_expired","generation":N}`

After each request, re-read canonical `runtime/lease.json`; do not infer acceptance from Issue creation alone. A `claim` must yield `reserved`; `activate` must yield `active` with the exact receipt.

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

Lifecycle ordering uses **authoritative Git/gateway commit chronology**, not the embedded `result.completed_at` value. `completed_at` is parseable execution-local metadata only; it must never be used to prove that completion preceded release.

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
- `armed_generation`: latest generation the Broker has durably committed as a Worker delivery attempt before touching scheduler state;
- `served_generation`: latest armed generation actually reconciled by a Worker invocation.

Invariant:

`served_generation <= armed_generation <= desired_generation`.

Wake requests use deterministic `request_key` values. Recent keys suppress replay.

## Wake Broker / Hourly Watchdog

The Broker never executes target-agent work and never claims a gateway lease.

It runs in two modes using the same recurring automation:

- **event nudge**: another infrastructure/client runtime moves its next occurrence earlier after persisting a durable wake;
- **hourly watchdog**: the RRULE guarantees eventual recovery if the nudge or worker delivery is lost.

Each Broker run uses a **wake-first fast path**:

1. read `runtime/dispatcher-config.json`, `runtime/dispatcher-health.json`, scheduler topology and the authoritative gateway lease first;
2. if `desired_generation > armed_generation`, immediately choose `desired_generation` for delivery without scanning unrelated tasks;
3. if `armed_generation > served_generation` and that delivery is stale, immediately choose the same `armed_generation` for retry without scanning unrelated tasks;
4. only when no unarmed/stale delivery exists, reconcile Registry and task/gate/runtime metadata to detect new scheduler-eligible READY work, due retry, partial reserved/active transitions or protocol-defined recovery; fresh live carriers and per-task holds exclude only their own tasks;
5. create a deterministic durable wake if such work exists but no sufficient wake is pending, then choose that new generation;
6. a stale `armed_generation > served_generation` **forces a new Worker scheduling attempt even if the Worker automation still reports enabled or carries an old/past DTSTART**; scheduler metadata is not proof of delivery;
7. **before any scheduler call**, CAS-persist the chosen generation as `armed_generation` with a fresh `last_armed_at`; this durable delivery intent makes an immediate/catch-up Worker invocation safe;
8. retarget the existing recurring Execution Worker's next occurrence, preserve its `RRULE:FREQ=HOURLY`, and keep `is_enabled=true`;
9. verify the returned scheduler state names the exact Worker, is enabled/runnable for the newly requested occurrence, and still carries its hourly RRULE; exact wall-clock timing is not a correctness assumption;
10. do not require any post-scheduler GitHub write for correctness. If the scheduler call fails or the Broker runtime dies after step 6, `armed_generation > served_generation` becomes stale and the hourly Broker retries the **same** generation;
11. otherwise no-op.

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
