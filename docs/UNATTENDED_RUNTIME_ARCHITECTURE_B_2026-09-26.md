# Unattended runtime architecture B — recovered write-actuator design

Date: 2026-09-26
Owner decision: **Variant B selected. Do not restore the old Wake Broker.**
Status: architecture reconstruction / implementation boundary.

## Executive conclusion

The ecosystem does **not** need a new result-writing algorithm.

A correct separation already existed across the historical Phase A / Phase B scheduler work and was later formalized in bounded relay v2:

1. a reasoning Runtime authors the result;
2. transport carries the exact authored envelope;
3. a separate mechanical actuator validates exact bindings;
4. only the actuator performs canonical GitHub persistence and terminal state transition;
5. gateway fencing protects only the short canonical persistence/closeout phase.

The unresolved problem is narrower:

> Find a reliable autonomous invocation bridge from ChatGPT Scheduled Runtime transport into a deterministic mechanical write actuator.

The old recurring Wake Broker / Execution Worker pair is not the answer and remains disabled.

## Recovered historical evidence

### 1. Event-wake Phase A / later Phase B worked end to end

On 2026-09-23, `TASK-EVENT-WAKE-RELAY-E2E-001` exercised:

- durable wake;
- gateway reservation/claim/activation;
- STOP after Phase A;
- later Execution Worker invocation;
- `ecosystem-supervisor` reinstantiation;
- exact result creation;
- durable `completed` state;
- gateway release afterwards.

The final durable result remains in:

- `tasks/TASK-EVENT-WAKE-RELAY-E2E-001/result.json`;
- `tasks/TASK-EVENT-WAKE-RELAY-E2E-001/state.json`.

This demonstrates that the old architecture already contained the conceptual write-actuator responsibility, although it was embedded in the Execution Worker.

### 2. Bounded relay v2 extracted the correct separation

`docs/BOUNDED_RUNTIME_RESULT_RELAY.md` formalized the safer sequence:

`immutable request -> reasoning Runtime -> exact relay -> validator -> mechanical persistence -> short gateway fence -> canonical closeout`.

Its important invariant is retained:

> The reasoning Scheduled Runtime holds no gateway lease.

A gateway fence is acquired only after the relay is accepted, for the shortest possible canonical persistence interval.

### 3. A dedicated Scheduled Runtime write-actuator probe failed

The isolated probe:

`runtime/probes/write-actuator-001/request.json`

asked a neutral Scheduled Runtime to perform exactly one pre-authorized GitHub `create_file` and nothing else.

The target result file was not created. Historical commit `8d894b1599ba5e1b9ce6c4e820ce13554f3eb87e` suspended the Scheduled Chat write actuator; commit `8bd94c27e0bdd1490281ac84ab950223be769705` added the isolated probe.

Therefore the failure is not explained by the old Worker's complexity. A generic consequential GitHub write from Scheduled Runtime itself is not a dependable production primitive.

### 4. Private/public GitHub did not change the result

Separate one-shot probes attempted the same narrow write against private and public repositories. Both failed.

A GitHub Issue write probe also failed.

Repository visibility is therefore not the demonstrated cause.

### 5. Google Docs is not a reliable replacement

The historical relay document:

`TEMP — ACP Runtime Identity Audit 003 Relay — 2026-09-25`

exists in the connected Google Drive and records:

`Status: BLOCKED — Google Docs write rejected by platform safety checks before submission`.

Therefore Google Docs must not be promoted to required autonomous transport.

### 6. HTML Preview is not a Scheduled Runtime bridge

Ordinary active Chat HTML Preview has demonstrated browser-side network capability.

The dedicated Scheduled Runtime Preview POST was not observed at the independently validated receiver.

Therefore HTML Preview remains research evidence only, not the autonomous return channel.

### 7. Scheduled Task mailbox is the strongest proven Chat-side transport

The separate disabled Scheduled Task mailbox pattern is repeatable and supports:

- fresh physical mailbox per attempt;
- generation/admission nonce;
- exact producer identity;
- retry quarantine;
- late-runtime confinement;
- exact payload hash;
- stale-attempt mechanical rejection.

This remains the required Agent -> transport boundary.

### 8. GitHub Actions already proves the mechanical-writer concept

`lvlaksim1/agent-control-plane-gateway` is a public deterministic actuator for gateway lease state.

Its workflow serializes requests, validates current state, applies a compare-and-set transition, writes through GitHub, re-reads the result, and emits a receipt.

The actuator logic is therefore not hypothetical.

However its historical invocation channel is a GitHub Issue. Because Scheduled Runtime GitHub Issue creation can itself be blocked, the workflow does not solve the Runtime -> actuator invocation bridge by itself.

## Selected architecture B — no old Broker

The production architecture is separated into four responsibilities.

### B1. Minimal Scheduler / Launcher

A lightweight Scheduled Chat runtime.

Responsibilities only:

- read canonical GitHub task state;
- determine one eligible task;
- allocate a fresh logical attempt;
- allocate/arm a fresh physical mailbox;
- create/arm a one-shot target Runtime;
- record only Chat-side scheduling metadata that the Scheduled Task surface reliably supports.

It is **not** a persistent Agent.
It does **not** hold project responsibility.
It does **not** write canonical GitHub task/result state.
It is not the old Wake Broker.

### B2. Target Agent Runtime

A separate runtime reinstantiates exactly one persistent Agent.

Responsibilities:

- read immutable request and required authoritative state;
- perform the bounded reasoning/work;
- author a terminal relay;
- write exactly that relay to its assigned mailbox.

It holds no gateway lease during reasoning.
It does not perform required direct GitHub writes.

### B3. Mailbox Collector / Validator

Infrastructure, not a persistent Agent.

Responsibilities:

- read the current mailbox candidate;
- verify task id, logical attempt, request digest/blob, author id, mailbox id/generation, admission nonce, relay nonce, terminal flag and exact payload hash;
- reject stale/quarantined candidates mechanically;
- produce an accepted exact envelope without reinterpretation.

This role may run together with B1 if the same Scheduled Chat launcher runtime is available, but acceptance does not itself mutate canonical GitHub state.

### B4. Deterministic Write Actuator

A narrow non-reasoning external mechanism.

Responsibilities:

1. accept only a validated, exact envelope;
2. independently revalidate immutable bindings and current canonical task state;
3. acquire a short gateway execution fence;
4. persist the exact authored relay/evidence;
5. persist canonical result;
6. persist terminal task state;
7. read back terminal state;
8. release the gateway;
9. emit an immutable receipt.

The actuator must never infer, summarize, repair or rewrite Agent judgment.

## The one remaining architecture gap

The missing bridge is:

`B3 accepted mailbox envelope -> B4 deterministic write actuator`.

Already rejected as required bridges:

- direct Scheduled Runtime GitHub Contents write;
- direct Scheduled Runtime GitHub Issue creation;
- producer self-update as the sole transport;
- Google Docs write;
- autonomous Scheduled Runtime HTML Preview POST;
- Work-based webhook execution.

The next engineering task is therefore **not scheduler redesign**. It is to implement and prove one narrow Runtime-to-actuator invocation surface that is allowed from Scheduled Runtime and whose server side performs only the bounded B4 operation.

## Acceptance criteria for the invocation bridge

A candidate bridge is accepted only if it passes all of the following without Auditor:

1. three sequential successful generations;
2. one deliberate lost Runtime;
3. retry into a different physical mailbox;
4. late stale old-runtime write after the retry is already accepted;
5. exact byte-for-byte payload preservation;
6. idempotent duplicate submission;
7. stale request/attempt/nonce rejection;
8. no gateway lease held during Agent reasoning;
9. short-fence canonical persistence only after relay acceptance;
10. terminal state read-back before release;
11. no client-project mutation outside the bounded test target;
12. recovery after launcher/runtime loss from durable GitHub + mailbox evidence.

Only after this bridge passes should one ordinary Registry-backed persistent-Agent task be run end to end.

## Explicit non-goals

- Do not restore the old Wake Broker.
- Do not re-enable the old Execution Worker.
- Do not use Work.
- Do not use Auditor during process debugging.
- Do not begin Agent Catalog / Agent Factory / Master Plan 8.9.
