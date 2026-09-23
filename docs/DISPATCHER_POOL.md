# Event-driven scheduler topology

The former five-slot polling pool is superseded by an Owner-authorized two-slot event-driven design.

## Runtime roles

### Execution Worker

One reusable Scheduled Chat automation performs autonomous control-plane execution. It is a one-shot worker that is normally dormant.

The Worker remains infrastructure, never an agent identity. It may execute at most one target-agent task per invocation and **must never re-arm itself**.

### Wake Broker / Hourly Watchdog

One separate recurring Scheduled Chat automation serves two functions:

1. fast event delivery when its next occurrence is nudged earlier after a durable wake is persisted;
2. hourly recovery if an event nudge or Worker delivery is lost.

The Broker never executes target-agent work, never claims the gateway lease, and is the only scheduler role allowed to arm the Execution Worker.

## Cross-task relay

Continuation is always:

```
durable wake
   ↓
Broker / Watchdog
   ↓
Execution Worker
```

If a Worker invocation creates another durable continuation, it nudges the *other* automation (the Broker), then stops. The Broker later arms the Worker.

This avoids the live-observed one-shot self-rearm race where a Worker can overwrite its own newly scheduled occurrence when the current invocation terminates.

Exact DTSTART delivery is not an invariant. Re-enabling a one-shot can be delivered immediately as a catch-up run; that is acceptable because the safety boundary is a later Worker invocation plus the authoritative gateway/task fence.

## Durable wake generations

Wake transport state is stored under `runtime/dispatcher-health.json#wake`:

- `desired_generation`: newest durable wake request;
- `armed_generation`: newest generation the Broker has durably committed as a Worker delivery attempt before the scheduler call;
- `served_generation`: newest armed generation actually reconciled by a Worker run.

Invariant:

`served_generation <= armed_generation <= desired_generation`.

A bounded `recent_request_keys` list suppresses replay of the same wake-producing transition.

Interpretation:

- desired > armed: Broker still needs to schedule the Worker;
- armed > served: a Worker invocation is outstanding or was lost;
- desired <= served: no wake request is pending.

## Wake-worthy transitions

A new wake is justified only by durable state that may permit progress, including:

- new READY task;
- dependency or Gate completion;
- successful Phase A activation requiring later Phase B;
- retry becoming due;
- recovery/requeue after runtime loss;
- partial-transition reconciliation leaving follow-up work.

A Worker run by itself is never sufficient reason for a new wake.

## Broker arming order

Live validation proved that an enabled one-shot may catch up immediately and begin before a post-scheduler acknowledgement can be committed. Therefore delivery state is an **outbox-style precommit**:

1. A durable wake already exists.
2. Broker deterministically selects the generation to deliver.
3. Broker CAS-persists that generation as `armed_generation` and refreshes `last_armed_at`.
4. Broker schedules the existing Execution Worker one-shot and enables it.
5. Broker verifies the returned scheduler state identifies the exact Worker and leaves a runnable occurrence, but no post-scheduler repository write is required for correctness.

If scheduling fails after step 3, the durable state is intentionally `armed > served`. Once stale, the hourly Broker retries the **same** generation. If the Worker starts immediately after step 4, it already sees the correct armed generation and can safely serve it.

## Event nudge order

An event producer that can safely access scheduler control:

1. persists the durable wake;
2. moves the Broker's next occurrence earlier while preserving its hourly RRULE and enabled state;
3. verifies the Broker remains enabled.

If the nudge fails, no authority is lost: the hourly Broker eventually observes the pending wake.

Event producers never arm the Worker directly.

## Preserved invariants

- global maximum one autonomous target-agent execution;
- authoritative lease in `lvlaksim1/agent-control-plane-gateway`;
- exact gateway fencing;
- immutable task requests;
- Phase A reserve/activate then STOP;
- Phase B in a later Worker invocation;
- target-agent mandate validation;
- completion evidence requirements;
- direct Owner↔agent conversations outside scheduler transport.

## Scheduler capacity

Deployment target:

- former `dispatcher-00` automation → reusable Execution Worker;
- former `dispatcher-12` automation → Wake Broker / Hourly Watchdog;
- former `dispatcher-24`, `dispatcher-36`, `dispatcher-48` → retired/disabled.

The historical five-slot race validation remains useful evidence for the gateway lease, but five continuously polling slots are no longer the production scheduler model.
