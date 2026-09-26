# Mailbox ACP exact validation — 2026-09-26

Status: **VALIDATED WITH INTEGRATION LIMITATIONS**

Validated baseline: `lvlaksim1/agent-control-plane@d16785eacd041a662311c0f3014c683a309a60f8`

Gateway state at validation: `idle`, generation `58`.

Auditor was not used. Recurring Wake Broker and Execution Worker remained disabled.

## What is proven

The neutral task `TASK-RUNTIME-MAILBOX-ACP-E2E-001` proves the mailbox transport and the bounded ACP lifecycle/fencing sequence used by that proof:

- immutable request blob: `5883d88c3c72d3ceb04ecd7b894204b2d2de01df`;
- canonical request digest: `sha256:82f0433bc0b867a2ca554d05b8d13664e6fb602de8fa2f276216c261dabba82d`;
- accepted current relay D exact raw SHA-256: `53577e9d4fbdc9a1a3fa1495e6406b913c30b353868eff3001bc223b2d33cbb8`;
- stale relay C exact raw SHA-256: `f8b193260d62a41488ec8f85e648268635a26f1d5411cb28b79d39755b10c5a8`;
- current execution fence: `exec-mailbox-e2e-001-20260926T0007Z`, generation `57`;
- task completion commit: `6cfaf715b766d38bb1bd92ac78eee3e735be8da7` at `2026-09-26T00:23:52Z`;
- gateway release commit: `a1ea4e8c807e012b55fa4982332987ffbcaf04bc` at `2026-09-26T00:24:07Z`.

Independent recomputation over the exact GitHub-returned text reproduced the two raw relay SHA-256 values and the canonical request digest.

The accepted D relay matched every checked current binding: task, logical attempt, request digest/blob, execution id/generation, author, producer task, physical mailbox task/id/generation, admission nonce, relay nonce, terminal flag and exact payload hash.

The late C relay retained a valid payload hash but differed from the current admission on logical attempt, producer, physical mailbox, admission nonce and relay nonce. It is therefore mechanically stale rather than semantically judged stale.

The durable completion order is confirmed: canonical result and terminal task state were committed before gateway release.

## What is not yet proven

The previous phrase “full ACP end-to-end” is too broad if it is understood to include the ordinary production scheduler path.

### 1. The proof task bypassed registered-Agent readiness

The proof request uses `target_agent_id = execution-worker`.

`registry/agents.json` has no persistent Agent with that id. Normal `ControlPlane.ready_tasks()` skips a task whose target is absent from the Registry. Therefore this proof did not demonstrate the ordinary:

`queued task -> ready_tasks() -> registered persistent Agent -> target Runtime`

selection path.

This does not invalidate the transport/lifecycle proof; it limits its coverage.

### 2. Mailbox validation is not wired into the ordinary Worker path

The mailbox validator exists in:

- `tools/mailbox_relay.py`;
- `runtime/mailbox-relay-contract.json`;
- `docs/MAILBOX_POOL_RESULT_TRANSPORT.md`;
- `tests/test_mailbox_relay.py`.

At this validation point there is no mailbox-relay integration reference in:

- `tools/control_plane.py`;
- `tools/workflow_runtime.py`;
- `tools/result_relay.py`.

Therefore the old recurring Worker cannot be described as a production mailbox consumer merely because the standalone validator and proof exist.

### 3. There is a lifecycle-contract tension to resolve

The earlier bounded runtime relay v2 deliberately keeps the reasoning Scheduled Runtime free of any gateway lease. Only after a relay is durably received does a mechanical actuator acquire a short fence for canonical writes.

The mailbox E2E proof bound the relay itself to an already-active `execution_id/generation`, which required holding the gateway fence while the Scheduled Runtime executed.

For a production design, the stronger combination is likely:

1. immutable task/request + logical runtime attempt;
2. fresh physical mailbox + generation/admission nonce + producer identity;
3. Scheduled Runtime performs reasoning/read-only work and writes only that mailbox, while holding no gateway lease;
4. a mechanical actuator validates the exact relay and current task attempt;
5. only then it acquires a short gateway fence;
6. accepted relay/result/state records bind the mechanical persistence to that `execution_id/generation`;
7. terminal state is re-read before release.

This preserves mailbox isolation while avoiding long-lived gateway ownership across an unreliable Scheduled Runtime.

Changing the contract to this ordering is an architecture change and requires Owner-visible approval rather than being silently inferred from the proof.

## Broker / Worker conclusion

The old recurring Wake Broker / Execution Worker pair must remain disabled in its current form.

Reasons:

- current dispatcher configuration already records Scheduled Runtime GitHub-write limitations;
- the old Worker prompt assumes direct durable GitHub/gateway mutations;
- mailbox validation is not integrated into that Worker;
- the neutral mailbox proof did not exercise ordinary registered-Agent readiness;
- re-enabling the pair now would claim a production path that has not been proven.

The Broker is not required for an Owner-present, live-controller path. A live authorized controller can allocate a mailbox, schedule a bounded target Runtime, validate its relay and perform the mechanical canonical closeout.

For unattended work, a scheduler/watchdog role may still be useful, but it must be redesigned as scheduling/transport infrastructure rather than as a GitHub-mutating authority path.

## Next architecture decision

Two bounded directions remain:

### A. Owner-driven mailbox execution

No recurring Broker is required. A live authorized controller allocates a fresh mailbox and one bounded producer Runtime, then mechanically closes the task after relay validation.

Advantages: smallest surface, compatible with proven transport, no unnecessary recurring slot use.

Limitation: no unattended canonical progression while no live actuator is present.

### B. Unattended scheduler-only front end

Keep a simplified recurring scheduler/watchdog whose only job is to discover eligible GitHub work and arm a fresh producer + mailbox. The producer remains read/reason-only and writes only its mailbox.

This can perform unattended analysis, but canonical GitHub completion still requires a separately available mechanical actuator unless a reliable authorized write actuator is independently proven.

## Validation verdict

- mailbox pool isolation: **PASS**;
- exact relay integrity and stale rejection: **PASS**;
- task/request/execution lifecycle used in the neutral proof: **PASS**;
- completion-before-release ordering: **PASS**;
- normal registered-Agent scheduler selection: **NOT PROVEN by this proof**;
- mailbox integration into old recurring Worker: **NOT IMPLEMENTED at this baseline**;
- re-enable old Broker/Worker as-is: **NO**.

This report is an exact-validation correction and architecture boundary. It does not enable recurring machinery or invoke any persistent target Agent.
