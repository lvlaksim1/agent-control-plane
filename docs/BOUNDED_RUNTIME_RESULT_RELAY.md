# Bounded Scheduled Runtime Result Relay v3

This protocol defines how Agent Control Plane uses a separate ChatGPT Scheduled Runtime when that runtime can perform substantial read-only reasoning but its external write capabilities and its own Scheduled Task metadata publication are not deterministic.

Scheduled Runtime is treated as **best-effort compute with at-least-once launch semantics and lossy result egress**, not as a transactional RPC worker. GitHub remains the canonical state store. Scheduled Task metadata is transport only.

Auditor remains suspended while this protocol is stabilized.

## 1. Architectural split

```text
canonical ACP task + immutable request
        ↓
controller allocates one fixed Scheduled Runtime slot
        ↓
controller durably writes a transport ticket
        ↓
controller arms the slot with one bounded immutable execution prompt
        ↓
fresh Scheduled Runtime performs read-only reasoning
        ↓
runtime attempts one terminal self-metadata publication
        ↓
controller observes Scheduled Task metadata
        ↓
exact ticket/envelope validation
        ↓
raw relay + receipt + exact payload become durable in GitHub
        ↓
only now: short mechanical gateway-fenced persistence
        ↓
canonical result/state durable and re-read
        ↓
gateway release
```

The reasoning runtime does not hold an ACP gateway lease and does not perform GitHub/Drive/Dropbox writes.

## 2. Two independent retry domains

v2 incorrectly coupled runtime transport loss to the semantic ACP task attempt. v3 separates them.

- `logical_attempt` is the semantic execution epoch of the ACP task. It advances only when task semantics require a new execution attempt.
- `delivery_try` is a transport retry inside the same `logical_attempt`.
- `transport_generation` is the unique slot allocation generation for one Scheduled Runtime delivery.

If a Scheduled Runtime runs but no acceptable relay is published, no canonical project side effect occurred. Therefore only `delivery_try` and `transport_generation` advance. The ACP task's semantic attempt does not advance merely because result transport failed.

A transport retry may repeat the same read-only reasoning against exactly the same immutable inputs in a new runtime.

## 3. Fixed Scheduled Runtime slots

The canonical slot pool is `runtime/scheduled-runtime-slots.json`.

Two reusable slots are reserved so that one can remain in quiescence while another carries a retry. Slots are disabled while idle. Allocation is serialized by a GitHub CAS update of the slot-pool file.

A slot has:
- stable `slot_id`;
- stable Scheduled Task identity;
- current lifecycle state;
- last allocated `transport_generation`;
- current ticket reference when busy;
- `quiescent_until` after a run.

The controller MUST NOT reuse a slot while it is `armed`, `running`, `awaiting-relay` or `quiescent`.

The Scheduled Task metadata API has no compare-and-swap primitive. A late old runtime can therefore overwrite metadata of a reused task. v3 mitigates this by generation binding plus a mandatory quiescence period and by accepting only the exact current ticket. A stale overwrite can never become canonical.

## 4. Transport ticket

Before the slot is armed, the controller durably creates:

```text
tasks/<task_id>/relay/<logical_attempt>/<transport_generation>/ticket.json
```

The ticket schema is version 1 and contains:

- `task_id`;
- `logical_attempt`;
- immutable `request_digest` and `request_blob_sha`;
- exact `transport_task_id`;
- `transport_slot_id`;
- positive integer `transport_generation`;
- positive integer `delivery_try`;
- fresh `admission_nonce`;
- fresh `relay_id`;
- fresh `relay_nonce`;
- `expected_author_id`;
- `allowed_payload_kind`;
- `scheduled_not_before`;
- `relay_deadline_at`;
- `slot_quiescence_until`;
- `status`.

Required temporal ordering:

```text
scheduled_not_before < relay_deadline_at < slot_quiescence_until
```

The ticket MUST be durable before the Scheduled Task is armed.

## 5. Arming order

Allocation and launch use this order:

1. re-read ACP task/request and require immutable request bindings;
2. CAS allocate an idle slot and a new `transport_generation`;
3. persist the exact ticket;
4. re-read the ticket;
5. update the Scheduled Task prompt/title with the immutable execution instruction;
6. enable/re-arm it for one future run;
7. record scheduler acknowledgment in transport state.

If arming fails after the ticket became durable, mark that delivery as `launch-failed`; do not advance `logical_attempt`.

The runtime prompt must contain all relay binding coordinates explicitly. For a persistent Agent it must still require fresh reinstantiation from the Agent's canonical `ENTRYPOINT.md`; prompt-carried identity claims are not authority.

## 6. Scheduled Runtime behavior

One invocation may reinstate at most one persistent Agent and may never switch persistent identity.

The runtime may:
- read the target Agent home repository and immutable task/evidence required by the engagement;
- reason within the Agent mandate;
- construct one bounded terminal payload;
- perform exactly one final `automations.update` publication to its own Scheduled Task.

It must not:
- write GitHub, Drive, Dropbox or project state;
- acquire an ACP gateway lease;
- create another persistent Agent identity;
- reinterpret its own failure to publish as task failure.

For infrastructure probes, no persistent Agent is reinstantiated.

### Optional admission marker

A runtime may make a best-effort early title-only update such as:

```text
ACP_ADMITTED|<transport_generation>|<admission_nonce>
```

This marker is diagnostic only. Absence of the marker does not prove semantic failure because current evidence shows that a Scheduled Runtime may run without successfully performing even this first metadata update.

Production prompts should therefore minimize tool calls and normally prefer one terminal publication after reasoning. The admission nonce remains mandatory in the final envelope even if no admission marker was observed.

## 7. Relay v3 envelope

The final Scheduled Task prompt is replaced with:

```text
ACP_RUNTIME_RELAY_V3|<compact JSON object>
```

Required fields:

- `schema_version=3`
- `relay_id`
- `transport_task_id`
- `transport_slot_id`
- `transport_generation`
- `task_id`
- `logical_attempt`
- `delivery_try`
- `request_digest`
- `request_blob_sha`
- `admission_nonce`
- `relay_nonce`
- `author_id`
- `author_kind` = `persistent-agent` or `infrastructure`
- `status` = terminal `complete` or `blocked`
- `terminal=true`
- `payload_kind`
- `payload_encoding=utf-8`
- `payload_text`
- `payload_sha256`
- `authored_at_msk`

The complete prompt is bounded to 12000 characters. Larger work must be split into coherent task stages, not silently truncated.

The runtime SHOULD set a compact title:

```text
ACP_READY|<transport_generation>|<short relay/payload digest>
```

in the same final metadata update when practical. The title is an optimization/diagnostic marker; the prompt envelope is the transport payload.

## 8. Publication observation and deadlines

`last_run_time` proves only that the Scheduled Task invocation was recorded. It is **not** proof that all child-runtime effects have finished.

Observed evidence includes historical successful publications more than one minute after `last_run_time`. Therefore the controller uses explicit deadlines, not immediate post-run failure inference.

Initial conservative tuning:
- publication grace after observed run: 3 minutes;
- relay deadline from scheduled start: 10 minutes;
- slot quiescence after relay deadline: 15 minutes.

The controller may accept a valid current-generation relay at any time up to `relay_deadline_at`.

After the deadline:
- unchanged/non-relay metadata -> `transport-lost`;
- malformed current-generation relay -> `relay-invalid`;
- stale generation/nonce/attempt -> `relay-stale`.

A transport loss increments only `delivery_try`, allocates a new generation (preferably on the other idle slot), and re-executes the same immutable read-only semantic attempt.

## 9. Acceptance and fail-closed rules

The executable source is `tools/result_relay.py`.

Acceptance requires exact match to the current transport ticket:
- task id;
- `logical_attempt`;
- `delivery_try`;
- transport task id;
- slot id;
- generation;
- request digest/blob SHA;
- admission nonce;
- relay id/nonce;
- expected author;
- allowed payload kind;
- terminal flag;
- Moscow timestamp;
- size limit;
- exact UTF-8 payload SHA-256.

Never infer freshness from title or `last_run_time`. For canonical acceptance, the controller also records the platform Scheduled Task metadata `updated_at` value and requires it to be no later than the ticket's `relay_deadline_at`. The child-authored `authored_at_msk` is provenance, not transport-freshness authority.

Historical `ACP_RUNTIME_RELAY_V1|` and `ACP_RUNTIME_RELAY_V2|` may be parsed for diagnostics but cannot be accepted as a new v3 canonical result.

## 10. Canonical relay persistence

For one accepted generation:

```text
tasks/<task_id>/relay/<logical_attempt>/<transport_generation>/ticket.json
tasks/<task_id>/relay/<logical_attempt>/<transport_generation>/raw.txt
tasks/<task_id>/relay/<logical_attempt>/<transport_generation>/acceptance.json
tasks/<task_id>/relay/<logical_attempt>/<transport_generation>/payload.txt
```

`raw.txt` is the exact Scheduled Task prompt relay.
`payload.txt` is the exact UTF-8 `payload_text`.
`acceptance.json` is mechanical provenance derived from validated fields and includes the platform `transport_updated_at` timestamp used to prove publication was inside the ticket deadline.

One logical attempt may have multiple transport ticket directories, but only one canonical accepted relay. Exact duplicate observation is an idempotent no-op. Any conflicting second relay after acceptance fails closed.

## 11. Mechanical persistence phase

Only after raw relay, receipt and payload are durable and re-read may a write actuator acquire a short gateway fence if target/control-plane writes require it.

The actuator:
1. re-reads immutable request and current base preconditions;
2. acquires/activates the exact gateway fence when required;
3. applies only exact authored operations;
4. does not improve, complete or reinterpret the Agent's judgment;
5. persists result and terminal task state;
6. re-reads durable completion;
7. releases the gateway only after completion is proven.

If an authored base commit/blob has drifted, the actuator stops and records a persistence conflict. It does not silently rebase the Agent's package.

During stabilization the live Supervisor runtime is the authorized mechanical actuator. Direct Scheduled Runtime GitHub writes are not part of this protocol.

## 12. Failure taxonomy

Transport and semantic failures are distinct:

- `launch-failed` — controller could not arm the Scheduled Task;
- `launch-miss` — no invocation observed for the allocated generation;
- `admission-miss` — invocation observed but no diagnostic admission marker;
- `egress-miss` — invocation ran but no final relay arrived before deadline;
- `relay-invalid` — relay malformed or integrity check fails;
- `relay-stale` — wrong generation/delivery/nonces/logical attempt;
- `semantic-blocked` — valid Agent-authored `status=blocked`;
- `persistence-conflict` — accepted package cannot be applied because canonical base preconditions changed;
- `actuator-failure` — mechanical closeout failed under an otherwise valid accepted relay.

`admission-miss` alone never advances/retries a task. `egress-miss` is a transport event. Only semantic task policy advances the semantic attempt.

After the configured number of delivery retries, the task is held with a transport blocker rather than semantically quarantined. Operator/controller remediation may then diagnose Scheduled Runtime transport without misclassifying the Agent's work.

## 13. Wake-up semantics

Result transport and controller wake-up are separate concerns.

A successful relay publication must remain valid even if no immediate controller wake occurs. A future Broker/controller scan can still observe it.

A later optimization may allow the child runtime, **after** a successful final self-publication, to request a best-effort Broker nudge. Failure of that nudge must not affect the already published relay. This optimization is not required for the v3 stabilization proof.

## 14. Stabilization proof required before production use

Before recurring autonomous Broker/Worker mutation service is restored, v3 must demonstrate:

1. fixed slot allocation and durable ticket before arming;
2. one successful v3 relay from a separate Scheduled Runtime;
3. exact UTF-8 raw/payload persistence and hash equality;
4. deliberate transport loss followed by a new `delivery_try` with unchanged `logical_attempt`;
5. rejection of a late relay from an older generation;
6. accepted relay applied by the mechanical actuator;
7. durable terminal state before gateway release;
8. no stranded lease;
9. slot quiescence/reuse behavior;
10. repeatability across multiple deliveries.

Auditor is not used for this stabilization.
