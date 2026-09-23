# Claim, Fencing and Recovery Protocol

## Claim

1. Reconcile repository state.
2. If global lease is active, do not claim.
3. Compute READY and select deterministically.
4. Verify Registry target and immutable request digest.
5. Produce authoritative GitHub time pulse.
6. Prepare generation = old_generation + 1 and unique execution_id.
7. CAS-write runtime/lease.json using the exact blob SHA read earlier.
8. On 409 Conflict stop: claim lost.
9. Re-fetch and verify exact ownership token.
10. Persist queued -> claimed task projection.
11. Reinstate target agent from home_repository@authority_ref via entrypoint.
12. Target agent validates invocation/authority and reconciles live state.
13. Persist claimed -> active.

The dispatcher does not acquire the target agent's authority merely by holding the lease.

## Consequential-write barrier

Immediately before every target mutation, release, permission change, durable agent-state mutation, task completion or equivalent consequential action:
- fetch lease;
- verify exact task_id, agent_id, execution_id, generation;
- if any field differs, stop before the write.

## Renewal

A live execution may renew by CAS while ownership still matches. Renewal does not change generation. A fenced execution may never renew.

## Runtime loss

Runtime loss is not task failure. Recovery requires authoritative GitHub time proving lease expiry.

Persistence order is mandatory:
1. fence by CAS: active(g=N) -> idle(g=N+1);
2. increment runtime loss and requeue/quarantine.

Never requeue first.

## Partial transition reconciliation

GitHub does not atomically update two independent files, so lease is authoritative and task state is repairable:
- claim persisted but task still queued -> repair to claimed from lease;
- fence persisted but task still claimed/active -> clear stale projection and apply recovery policy.

## Checkpoints

Checkpoint files are immutable. latest_checkpoint is only a navigation pointer.

Store completed externally meaningful steps, verified evidence refs, exact target refs/commits where relevant, and next action. Never store private chain-of-thought.

On resume, select newest valid checkpoint, reinstate the same agent, then revalidate live state before acting.

## Runtime authority revision after live E2E

The private control-plane lease defined the original CAS model and remains useful for deterministic tests. In deployed Scheduled Chat runtime, the authoritative lease is held by `lvlaksim1/agent-control-plane-gateway`, whose public GitHub Actions workflow serializes claim/renew/release/recover transitions. This preserves the same fencing invariant while avoiding dependence on a Scheduled Chat being permitted to make the lock mutation itself.
