# Scheduled Chat Execution Worker Protocol

The scheduler uses two infrastructure automations:

1. one reusable hourly-anchored **Execution Worker** whose next occurrence may be retargeted earlier; and
2. one recurring **Wake Broker / Hourly Watchdog**.

Direct Owner↔agent conversations remain first-class and do not use scheduler transport. A wake changes only *when* work is reconsidered. It never grants authority.

## Operational suspension gate

The protocol below defines the required semantics when a valid write actuator is available. It does **not** authorize assuming that Scheduled Chat can mutate GitHub.

Observed 25 September 2026 Scheduled Chat runs could read the control-plane state while required consequential GitHub writes were blocked by the platform safety layer before submission. Therefore the recurring Broker and Worker are operationally suspended.

Before either recurring role is re-enabled, prove in the same execution environment that it can perform the exact required durable mutations while preserving all existing fences. Until then:

- inability to persist the wake outbox precommit, gateway transition, task CAS, checkpoint, result, or completion state is a hard fail-closed blocker;
- never skip, weaken, reorder, or simulate a required durable mutation;
- do not interpret scheduler delivery, a visible message, Registry membership, or read access as write authority/capability;
- a separate Agent runtime may be used read-only when identity separation is required, but it must stop short of target/control-plane mutation and may return only an exact deterministic relay package for a separately authorized mechanical actuator.


## Per-task live-carrier gate

There is no global interactive shutdown.

For every candidate task, read and validate its canonical `state.json#carrier` before scheduler claim or Phase-B target reinstantiation:

- fresh `mode=live` carrier lease → this task is not scheduler-eligible;
- expired `mode=live` with `fallback_after_expiry=true` → this task becomes scheduler-eligible;
- `mode=hold` → this task remains blocked until its carrier is explicitly cleared;
- `carrier=null` → normal scheduler eligibility.

A live carrier on TASK-A must never block unrelated TASK-B. The Broker and Worker remain operational while the Owner is online and may continue other autonomous work.

A live carrier is valid only for work whose persistent Agent identity is already bound to that live runtime. It is an execution-ownership fence for **same-agent** work; it is never permission to change persistent identity.

For cross-Agent work the interactive path is:

```
live caller runtime (agent_id A)
      ↓
persist immutable child task in GitHub
      ↓
child carries runtime:separate-target
      ↓
Wake Broker → Execution Worker
      ↓
fresh target runtime (agent_id B)
```

The caller runtime remains Agent A. It does not attach a live carrier to an Agent-B child and it never reinstantiates Agent B itself. For `continuation:manual-pull`, verified child output stays durable in GitHub until the Owner later invokes the caller and asks it to inspect the result. For `continuation:automatic-new-runtime`, the caller precreates a dependency-bound `runtime:caller-continuation` task that will later reinstate Agent A in a **new** Worker runtime.

A live same-agent runtime may still use a task carrier for its own scheduler-visible task/chain. If that runtime disappears, carrier expiry permits the declared autonomous fallback for that same task. This is a continuity fence, not a cross-Agent transport mechanism.

### Direct-live acquisition and execution fence

A scheduler-visible task MUST have its live carrier established before direct interactive execution proceeds.

For a new task, create the immutable request, then create the queued state with its carrier already present. For an existing queued task, acquire the carrier by CAS on that same state projection. Acquisition is allowed only from `queued + claim=null`; a claimed/active task cannot be taken over silently.

Because scheduler Phase A also CAS-updates `state.json`, carrier-vs-claim races resolve on one object. After carrier acquisition, and immediately before every consequential direct-live write, re-read both state and the authoritative gateway. Require:

- the same task remains `queued` with `claim=null`;
- the same fresh `carrier_id` remains present;
- the gateway does not own this same task as `reserved` or `active`.

If any check fails, direct-live work stops and ownership is reconciled before target effects.

### Direct-live completion

Direct-live completion does not use the autonomous gateway fence. It has its own carrier fence.

Before declaring the live engagement complete:

1. require the exact fresh live-carrier fence;
2. write evidence-backed `result.json` with `execution_mode=live`, immutable request binding, and exact `carrier_id`;
3. verify the completion contract;
4. CAS `state.json` to `completed` with `claim=null` and `carrier=null`;
5. re-read the terminal state.

If the runtime is lost before any valid success result becomes durable, carrier expiry permits ordinary autonomous fallback.

If a valid live `result.json` is already durable but the runtime is lost before step 4 terminalizes `state.json`, that partial completion MUST be reconciled before scheduler claim. Use the authoritative Git commit time for the current result blob, not `result.completed_at`. When the live result is bound to the exact immutable request/blob and exact carrier_id, satisfies all completion evidence/gates, and its Git commit is not later than the carrier lease expiry, CAS-repair `state.json` to `completed`, clear claim/carrier, re-read, and do not execute the target. If the result is absent, invalid, mismatched, or authoritatively committed after expiry, normal fallback remains eligible. If a result is present but the authoritative Git commit time for its current blob cannot be established, fail closed: do not claim or execute the task until chronology is resolved.

## Cross-Agent runtime and continuation contract

Every new Agent-issued task is validated against the fixed-runtime execution policy before it can become READY or begin target execution.

### Bounded delegation

`responsibility.semantics_version=2` remains authoritative for responsibility and authority. Bounded delegation means the caller keeps the commitment and project responsibility, while transport grants no additional authority.

For a different target `agent_id`, the immutable request MUST carry:

- `runtime:separate-target`;
- exactly one of `continuation:manual-pull` or `continuation:automatic-new-runtime`.

The child is always reinstantiated in a fresh target Worker runtime.

For `continuation:manual-pull`, child completion is terminal for automatic routing: write and verify the durable result, complete the child, and stop. No caller continuation is generated. The Owner may later invoke the caller, which reads the exact durable child result.

For `continuation:automatic-new-runtime`, the caller precreates a distinct dependency-bound task that targets itself and carries `runtime:caller-continuation`. That task is same-Agent continuation work, not another delegation, and therefore carries no responsibility-transfer contract. It remains blocked until the exact child reaches verified terminal completion. A later Worker invocation reinstantiates the caller in a new runtime.

### Explicit handoff

New executable handoffs still use responsibility semantics version 2 and remain a proposed responsibility transfer requiring independently verified target-home acceptance. A handoff to a different persistent Agent also carries `runtime:separate-target`, but it carries no caller-continuation constraint. Terminal completion creates no implicit return.

### Historical continuation compatibility

Older already-durable `state.json#continuation` objects remain readable for crash-safe compatibility. They may arise from historical live bounded delegation or from repair of a historical pre-migration live result.

They are **recovery-only**:

- no current runtime may consume them by switching persistent `agent_id`;
- a fresh Worker invocation may recover an expired pending continuation by binding that runtime to the recorded caller;
- the Worker verifies the exact child state/result, reinstantiates only that caller, acknowledges the continuation before consequential caller work, and never re-executes the completed child;
- a fresh historical `live_lease_until` merely delays recovery until expiry; it does not authorize same-runtime delivery;
- consumed continuations are never redelivered.

Nested historical continuations unwind one immediate caller at a time through separate runtimes. Supervisor is not inserted as a mandatory routing hop.

Direct Owner invocation remains first-class and does not require synthetic inter-Agent metadata.

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
4. reconcile that exact execution before considering new work;
5. when the gateway is idle, first inspect the captured wake key. If it has form `return:<task_id>:<continuation_id>`, treat it only as historical recovery work: fetch that completed task and exact result; in this fresh Worker invocation bind the runtime to the recorded caller, acknowledge the exact continuation before caller effects, never switch this runtime to another persistent Agent, and never re-execute the child;
6. before general READY scanning, detect any other completed tasks with expired historical pending caller continuations and service at most one recovery before claiming new child work;
7. otherwise inspect `task-ready:<task_id>`, fetch that task's request/state/runtime/gates and validate its per-task carrier;
8. before treating any **expired live-carried queued task** as scheduler-eligible, explicitly inspect whether `result.json` exists and obtain the authoritative Git commit time for its current blob. If it is an exact valid pre-expiry live success, CAS-repair the task to `completed` and do not claim it; if absent/invalid/mismatched/authoritatively post-expiry, normal fallback may proceed; if a result is present but commit chronology is unavailable, fail closed and do not execute;
9. only after that reconciliation may the exact wake-addressed task be selected as READY; if none is available, scanning other queued tasks must apply the same expired-live result reconciliation rule and still exclude fresh live carriers and explicit holds;
10. execute at most one bounded control-plane cycle.

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
2. target agent validates issuer, root/immediate authority provenance, target identity, objective, scope, inherited constraints, allowed/forbidden effects and completion contract against its own mandate;
3. for `explicit_handoff`, target persists a structured acceptance record in its own authoritative Agent state, re-reads that record from the immutable target-home commit, verifies repository/ref/path/blob/content and the exact request digest, then CAS-projects `responsibility_acceptance` under the exact current gateway or live-carrier fence; responsibility remains with the caller until this succeeds;
4. CAS-update private task state to `active`; activation fails closed for an explicit handoff without a valid acceptance receipt;
5. before every consequential target/control-plane write require the exact active fence/receipt match and, for explicit handoff, a valid acceptance receipt;
6. persist immutable checkpoints after meaningful durable progress;
7. if execution exceeds the lease window, renew only while the exact fence remains valid;
8. on execution failure, fence/release first, then apply retry/backoff/quarantine policy.

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
4. only when no unarmed/stale delivery exists, reconcile Registry and task/gate/runtime metadata to detect expired historical pending caller continuations, dependency-ready caller-continuation tasks, new scheduler-eligible READY work, due retry, partial reserved/active transitions or protocol-defined recovery; fresh same-agent live carriers and per-task holds exclude only their own tasks;
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
- expired historical live + queued/unclaimed + exact valid pre-expiry live result: CAS-repair to completed before scheduler claim; for historical bounded delegation the same repair MAY preserve/project the pending caller continuation from the original live carrier, then recover that caller only in a fresh Worker runtime without re-executing the child;
- expired same-agent live + queued/unclaimed + absent/invalid/mismatched/post-expiry result: ordinary fallback eligibility may proceed;
- completed historical bounded-delegation task + pending continuation + fresh continuation lease: do not deliver it in the current runtime; wait for expiry;
- completed historical bounded-delegation task + pending continuation + expired continuation lease: persist/request a deterministic `return:<task_id>:<continuation_id>` wake, then let a fresh Worker runtime reinstate the exact caller, acknowledge continuation before caller effects, and never re-execute the child;
- completed task with consumed historical continuation: do not redeliver caller;
- completed task with valid result and idle gateway: repair completion projection only; never execute twice.

## Authority and routing

Supervisor is not a mandatory gateway. Owner or a registered active agent may issue a task only with the required authority basis. Target-side mandate validation is always required. Wake delivery, scheduler identity, Registry membership, lease reservation or tool access never expand authority.

## Owner-derived root authority grant

For new Owner-derived work that may be delegated, `authority_basis.grant` is the normalized immutable root grant. It carries allowed effects, forbidden effects, scope, inherited constraints, and subdelegation policy. Direct Owner execution remains first-class and needs no agent responsibility envelope. If an Agent creates the first agent-to-agent child, ACP requires the child to preserve the same root provenance and prove that allowed effects/scope only narrow, forbidden effects/constraints are preserved or strengthened, and root subdelegation is permitted. A root agent delegation without a represented parent task must carry the same normalized grant in its own immutable authority basis. Nested v2 delegations additionally cannot widen parent task scope.
