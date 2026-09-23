# Gates, Retry and Completion Evidence

## Retry

Runtime loss and execution failure are different.

- runtime loss: lease expires without a clean agent outcome; use the existing runtime_loss_count and fence before requeue.
- execution failure: the live fenced agent reports a bounded execution/tool/target failure; task runtime metadata increments failure_count and applies retry_policy.
- after max_attempts, quarantine instead of looping indefinitely.

## Gates

A gate is a first-class durable blocker. Waiting/cancelled gates prevent READY and completion.

Supported types: owner_decision, authority, external_dependency, audit, release_approval.

A gate can only be satisfied by required_actor_id. Resolving a gate never expands an agent mandate.

## Completion evidence

result.json is separate from task state. Every evidence item must include kind, reference, verified=true, verified_by and verified_at.

completion_contract.required_evidence names the minimum evidence kinds/counts. The runtime must independently inspect the referenced GitHub commit/run/report/file before marking that evidence verified.

No self-asserted "done" can move a task to completed.
