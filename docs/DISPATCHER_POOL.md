# Event-driven scheduler topology

The former five-slot polling pool is superseded by an Owner-authorized two-slot event-driven design.

## Interactive-first boundary

Interactive-first routing is **per task / per work chain**, not a global scheduler mode.

A scheduler-visible task carried by the live Owner-facing runtime MUST record a renewable carrier lease in the same CAS projection the scheduler claims: `tasks/<task_id>/state.json#carrier`:

- `mode=live`: the task is owned by the live chat/runtime until `lease_until`; scheduler selection and scheduler Phase-B execution for that task are blocked while the lease is fresh.
- expired `live` lease with `fallback_after_expiry=true`: the scheduler may pick up that task if the live runtime disappeared or stopped renewing it.
- `mode=hold`: explicit per-task Owner pause with no expiry.
- `carrier=null`: no live carrier; normal autonomous scheduler eligibility applies.

The key invariant is isolation: **a live carrier blocks only its own task/chain**. Broker and Worker remain available to service unrelated autonomous tasks while the Owner is online.

When the Owner is online, an inter-agent handoff for the current chain is:

```
live Owner runtime
      ↓
persist task / handoff in GitHub
      ↓
attach/renew live carrier on that task
      ↓
reinstantiate the next persistent agent immediately
in the same live runtime
```

No scheduler wait is introduced into the interactive path. Scheduler slots are fallback delivery for unattended tasks and for live-carried tasks whose carrier lease later expires.

### Live-carrier ownership transition

Carrier acquisition is an execution-ownership transition, not advisory metadata.

- for a new live-carried task, publish the immutable request first and create the queued state with the live carrier already present; do not expose a carrier-free queued state;
- for an existing queued task, install the carrier by CAS-updating the exact same `state.json` object a Worker would CAS to `claimed`;
- acquisition is valid only from `status=queued`, `claim=null`;
- if scheduler claim and carrier acquisition race, only one CAS may win; the loser re-reads and stops/reconciles;
- before each consequential direct-live write, re-read task state and the authoritative gateway and verify the same fresh `carrier_id`; if the gateway owns this same task as reserved/active, do not perform direct-live target work until that scheduler ownership is reconciled.

### Live completion and fallback

Successful live execution MUST terminalize the ACP projection before carrier expiry:

1. persist evidence-backed `result.json` with `execution_mode=live` and exact `carrier_id`;
2. while the same live-carrier fence is still fresh, CAS `state.json` to `status=completed`, `claim=null`, `carrier=null`;
3. re-read the terminal state.

If the live runtime disappears before writing any valid live result, normal scheduler fallback may execute the still-nonterminal task after carrier expiry.

If the runtime disappears **after a valid live result is durable but before the terminal state CAS**, the scheduler MUST reconcile that partial completion before any fallback execution: inspect the exact current `result.json` plus its authoritative Git commit time. If it is a valid live success bound to the exact request/blob and exact carrier_id, all completion evidence/gates are satisfied, and the result commit is not later than the carrier lease expiry, CAS-repair the task to `completed`, clear carrier/claim, re-read, and do not execute the target. Missing, invalid, mismatched, or post-expiry results do not suppress legitimate fallback.

This recovery closes the crash window between durable result publication and terminal task-state projection. `result.completed_at` is metadata only and is never used as ownership timing evidence.

## Runtime roles

### Execution Worker

One reusable Scheduled Chat automation performs autonomous control-plane execution. It keeps an hourly recurring RRULE as a durable scheduler anchor, but ordinary hourly occurrences use a health/gateway fast-noop unless an unserved wake or exact partial gateway execution exists.

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

This avoids both the live-observed self-rearm race and the later-observed unreliable reuse of an already-fired one-shot. The Worker is therefore a recurring scheduler slot whose next occurrence may be retargeted earlier by the Broker while preserving its RRULE.

Exact DTSTART delivery is not an invariant. Retargeting the recurring Worker may be delivered late or as catch-up; that is acceptable because the safety boundary is a later Worker invocation plus the authoritative gateway/task fence.

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

## Broker wake-first fast path

The Broker MUST evaluate delivery state before scanning task bundles:

- `desired > armed` → arm the desired generation immediately;
- `armed > served` and stale → retry that same armed generation immediately;
- only when neither condition applies may the Broker scan task/gate/runtime state to discover newly READY work.

This keeps wake delivery bounded even when the control-plane task history grows and prevents scheduler recovery from timing out while enumerating unrelated tasks.

## Broker arming order

Live validation proved that an enabled one-shot may catch up immediately and begin before a post-scheduler acknowledgement can be committed. Therefore delivery state is an **outbox-style precommit**:

1. A durable wake already exists.
2. Broker deterministically selects the generation to deliver.
3. Broker CAS-persists that generation as `armed_generation` and refreshes `last_armed_at`.
4. Broker retargets the existing recurring Execution Worker's next occurrence and keeps it enabled while preserving `RRULE:FREQ=HOURLY`.
5. Broker verifies the returned scheduler state identifies the exact Worker, remains enabled, and still carries the hourly RRULE, but no post-scheduler repository write is required for correctness.

If scheduling fails after step 3, the durable state is intentionally `armed > served`. Once stale, the hourly Broker retries the **same** generation even if the Worker automation still appears enabled or retains an old/past DTSTART; those scheduler fields do not prove delivery. If the Worker starts immediately after step 4, it already sees the correct armed generation and can safely serve it.

## Event nudge order

An event producer that can safely access scheduler control:

1. persists the durable wake;
2. moves the Broker's next occurrence earlier while preserving its hourly RRULE and enabled state;
3. verifies the Broker remains enabled.

If the nudge fails, no authority is lost: the hourly Broker eventually observes the pending wake.

Event producers never arm the Worker directly.


## Recurring Worker idle fast-noop

The Worker is not a second work-discovery poller. On a natural hourly occurrence it reads only wake transport state plus the authoritative gateway first. If the gateway is idle and there is no `armed_generation > served_generation`, it stops without scanning task bundles. If a gateway partial transition exists, it reconciles that exact execution; if an unserved wake exists, it handles that generation normally.

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

- former `dispatcher-00` automation → reusable hourly-anchored Execution Worker whose next occurrence is retargeted by Broker events;
- former `dispatcher-12` automation → Wake Broker / Hourly Watchdog;
- former `dispatcher-24`, `dispatcher-36`, `dispatcher-48` → retired/disabled.

The historical five-slot race validation remains useful evidence for the gateway lease, but five continuously polling slots are no longer the production scheduler model.
