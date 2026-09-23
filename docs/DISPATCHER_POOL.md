# Event-driven scheduler topology

The former five-slot polling pool is superseded by an Owner-authorized event-driven design.

## Runtime roles

### Execution Worker

One reusable Scheduled Chat automation performs autonomous control-plane execution. It is a one-shot worker that is normally dormant and is re-armed only when durable control-plane state requires another reconciliation/execution cycle.

The worker remains infrastructure, never an agent identity. It may execute at most one target-agent task per invocation.

### Hourly Watchdog

One separate recurring Scheduled Chat automation runs hourly. It does not execute target-agent work. It reconciles task readiness, wake delivery state and the authoritative gateway lease, and re-arms the Execution Worker only when durable work or recovery is required.

## Durable wake generations

Wake transport state is stored under `runtime/dispatcher-health.json#wake`:

- `desired_generation`: newest durable wake request;
- `armed_generation`: newest generation successfully scheduled on the worker;
- `served_generation`: newest generation actually reconciled by a worker run.

A bounded `recent_request_keys` list suppresses replay of the same wake-producing transition.

Interpretation:

- desired > armed: the worker still needs to be scheduled;
- armed > served: a worker invocation is outstanding or was lost;
- desired <= served: no wake request is pending.

## Wake-worthy transitions

A new wake is justified only by durable state that may permit progress, including:

- new READY task;
- dependency or Gate completion;
- successful Phase A activation requiring later Phase B;
- retry becoming due;
- recovery/requeue after runtime loss;
- reconciliation leaving follow-up work.

A worker run by itself is never sufficient reason to re-arm.

## Re-arm ordering

1. Persist a wake request.
2. Re-arm the existing Execution Worker by setting a future one-shot run and `is_enabled=true`.
3. Verify the scheduler update shows the worker enabled with that future run.
4. Persist the corresponding armed generation.

If step 4 is lost, a duplicate re-arm is safe. If the worker never runs, the Watchdog detects an outstanding stale armed generation and re-arms it.

## Preserved invariants

The topology does not change:

- global maximum one autonomous target-agent execution;
- authoritative lease in `lvlaksim1/agent-control-plane-gateway`;
- exact gateway fencing;
- immutable task requests;
- Phase A reserve/activate then STOP;
- Phase B in a later invocation;
- target-agent mandate validation;
- completion evidence requirements;
- direct Owner↔agent conversations outside scheduler transport.

## Scheduler capacity

Deployment target:

- former `dispatcher-00` automation → reusable Execution Worker;
- former `dispatcher-12` automation → hourly Watchdog;
- former `dispatcher-24`, `dispatcher-36`, `dispatcher-48` → retired/disabled.

The historical five-slot race validation remains useful evidence for the gateway lease, but five continuously polling slots are no longer the production scheduler model.
