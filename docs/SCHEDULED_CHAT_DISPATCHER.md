# Scheduled Chat Dispatcher Protocol

The Dispatcher is infrastructure, not a persistent agent. Direct Owner↔agent conversations are first-class and do not use this scheduler pool.

## Two-phase target execution

**A gateway claim is only a reservation. A reserved lease never authorizes target-agent reinstantiation or target writes.**

### Phase A — reserve and arm, then stop

1. Reconcile Registry, tasks, gates, runtime metadata, and the authoritative gateway lease.
2. If gateway is idle, compute READY deterministically and select at most one task.
3. Request gateway `claim`. A successful claim MUST commit gateway state `reserved`, never `active`.
4. CAS-write the private task projection to `claimed` with exact execution_id, generation, slot_id, claimed_at, request_blob_sha; re-read it.
5. Capture the Git blob SHA of that durably visible claimed state.
6. Request gateway `activate` using exact fence fields plus `activation_projection_blob_sha=<claimed state blob SHA>`.
7. Proceed only if the canonical gateway lease is `active` and records that exact activation projection receipt.
8. CAS-update the private claim to record the same `activation_projection_blob_sha`; re-read it.
9. **STOP THE DISPATCHER INVOCATION. Do not reinstate the target agent and do not perform any target write in the reservation/activation invocation.**

If the runtime dies:
- `reserved + queued`: repair the same task to claimed, then activate; never create a second claim.
- `reserved + claimed`: activate from the exact current claimed projection and stop.
- `active + claimed` without locally recorded receipt: verify the gateway receipt refers to a valid historical claimed-state Git blob for the same task/fence, record the receipt, and stop.
- release/fence first if any identity, request blob, or projection evidence conflicts.

### Phase B — execute in a later dispatcher invocation

10. A later dispatcher may begin target-agent reinstantiation only when:
   - gateway state is `active`;
   - private task state is `claimed`;
   - private claim contains `activation_projection_blob_sha`;
   - gateway and private claim exactly match task_id + target agent_id + execution_id + generation + slot_id + request_blob_sha + activation_projection_blob_sha.
11. Reinstate the existing target agent from Registry home_repository@authority_ref and execute its ENTRYPOINT recovery protocol.
12. The target agent validates issuer, authority provenance, target identity, objective, scope, constraints, requested effects, and completion contract against its own mandate. Routing, tools, registry membership, reservation, or activation never create authority.
13. CAS-update private task state to `active` while retaining the activation receipt; re-read it.
14. **Before every consequential target/control-plane write**, require deterministic admission: private state `active`, gateway lease `active`, and the full exact receipt/fence match above. Otherwise stop before the write.
15. Persist immutable checkpoints after meaningful durable progress. Never persist hidden chain-of-thought.
16. If execution will exceed the lease window, renew only while the exact active fence and activation receipt still match.
17. On execution failure, fence/release first, then apply retry/backoff/quarantine policy.

### Completion

18. While the exact active fence remains valid, write `result.json` exactly to `runtime/dispatcher-write-contract.json`. Every required evidence item must be independently verified and satisfy completion_contract.
19. CAS-update task state to `completed` with `claim=null`; re-read it.
20. Only after completed state is durable request exact gateway `release`; verify canonical gateway becomes idle at a newer generation.
21. Persist bounded dispatcher health. Do not manually start dependent work; a later dispatcher recomputes READY.

## Recovery and reconciliation

- A completed task with valid result and idle gateway may have its completion projection repaired; it must never execute twice.
- An expired reserved/active lease is fenced before task requeue/quarantine.
- A task may never be selected for a new claim while the gateway holds its prior execution.
- Gateway response is trusted only after canonical committed lease re-read.
- A dispatcher executes at most one target-agent execution per invocation and never combines agent identities.

## Human and issuer routing

Supervisor is not a mandatory gateway. Owner may work directly with any persistent agent. A task may be issued by Owner or a registered active agent with explicit authority basis. Target-side mandate validation is always required.

## Gateway trust boundary

The public gateway stores only opaque execution coordination. It never receives project objective/content, Context Capsule state, completion evidence, or target secrets.
