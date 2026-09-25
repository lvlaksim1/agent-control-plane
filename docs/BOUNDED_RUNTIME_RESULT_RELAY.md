# Bounded Read-Only Runtime Result Relay v2

This protocol exists because a separate Scheduled Chat runtime can reliably read GitHub and, in successful probes, can update its own Scheduled Task metadata, while consequential GitHub writes from that runtime cannot be assumed available.

It is a transport protocol, not a new authority model. Scheduled Task metadata is non-canonical transport only.

## Core rule

A separate target runtime is split from durable mutation:

```text
immutable task/request + authorized attempt
        ↓
fresh read-only target runtime
        ↓
target Agent or infrastructure role authors one terminal relay envelope
        ↓
the runtime stores that envelope only in its own Scheduled Task prompt
        ↓
authorized mechanical actuator retrieves the exact envelope
        ↓
validate task/request/attempt/nonce/author + exact payload hash
        ↓
persist exact raw relay + acceptance receipt + exact payload bytes
        ↓
only now acquire a short gateway fence for mechanical GitHub mutations
        ↓
apply exact authored package → durable result/state → release
```

The read-only reasoning runtime never owns an autonomous gateway lease and never performs GitHub/Drive/Dropbox writes. Runtime loss before relay publication therefore leaves no gateway lease to recover.

## Authority boundary

The relay grants no authority.

For a persistent Agent:
- identity, mandate and authority still come from the Agent home repository plus the immutable task grant;
- the Agent authors the semantic result;
- the actuator MUST NOT reinterpret, improve, complete, rank or otherwise substitute its judgment for the Agent's;
- the actuator validates only syntax, immutable bindings, attempt freshness, payload integrity, current base preconditions and permitted effects, then persists mechanically.

Canonical authority begins only after the validated relay has been durably accepted in GitHub with transport provenance.

## v2 envelope

The Scheduled Task prompt is replaced with:

```text
ACP_RUNTIME_RELAY_V2|<JSON object>
```

Required fields:

- `schema_version=2`
- `relay_id`
- `transport_task_id` — exact Scheduled Task id that carried the envelope
- `task_id`
- `attempt` — positive integer equal to the currently authorized runtime attempt
- `request_digest`
- `request_blob_sha`
- `relay_nonce` — fresh nonce issued only for this attempt
- `author_id`
- `author_kind` — `persistent-agent` or `infrastructure`
- `status` — terminal `complete` or `blocked`
- `terminal=true`
- `payload_kind`
- `payload_encoding=utf-8`
- `payload_text` — the exact authored payload as a string
- `payload_sha256` — SHA-256 of the exact UTF-8 bytes of `payload_text`, encoded as `sha256:<64 lowercase hex>`
- `authored_at_msk` — timezone-aware Moscow timestamp

The complete prompt remains bounded to 12000 characters. Larger work must be split into coherent stages; this relay is not a general file-transfer channel.

`ACP_RUNTIME_RELAY_V1|...` may still be parsed for historical diagnostics, but v1 envelopes MUST NOT be accepted as new canonical results.

## Attempt binding and retry

Before a relay runtime is launched, the controller persists the current authorized attempt together with:
- immutable request digest and request blob SHA;
- exact transport task id;
- fresh relay id;
- fresh relay nonce;
- expected author and allowed payload kind.

The relay is acceptable only while all of those values, including `attempt`, still match the current task state.

If a runtime is lost before publishing a relay:
1. no canonical result exists;
2. no gateway lease is held by that reasoning runtime;
3. retry increments the task attempt;
4. retry uses a new transport task id, relay id and relay nonce.

Any late relay from the lost runtime has the old attempt and/or nonce and is rejected fail-closed. A stale relay can never overwrite a later attempt.

## Exact payload integrity

`payload_text` is the authored content. Its UTF-8 byte sequence is authoritative for mechanical persistence.

Before acceptance, the actuator computes SHA-256 over `payload_text.encode("utf-8")` and requires exact equality with `payload_sha256`. It does not parse and reserialize the payload merely to persist it.

This allows Markdown, JSON text, Cyrillic, line breaks and other UTF-8 content to survive the relay unchanged.

## Mechanical acceptance and idempotence

A relay can be accepted only when all expected bindings match exactly:
- task id;
- current attempt;
- request digest and request blob SHA;
- relay id;
- relay nonce;
- transport task id;
- expected author;
- allowed payload kind;
- `terminal=true`;
- valid Moscow timestamp;
- size bound;
- exact payload SHA-256.

The mechanical acceptance record is one canonical receipt per `task_id` and contains the immutable relay bindings plus `raw_relay_sha256` and `payload_sha256`.

Rules:
- no existing receipt → `accept-new`;
- the exact same validated relay presented again → `already-accepted`, no-op;
- any different relay after a receipt exists → conflict, fail closed;
- a later attempt after a canonical receipt exists → conflict, because the task already has a canonical accepted result;
- a relay whose attempt does not equal the current authorized attempt → stale, fail closed.

This means repeated delivery cannot duplicate a canonical result, and an old runtime cannot win a race after retry has advanced the attempt.

For `status=blocked`, the payload may describe the blocker, but the actuator MUST NOT fabricate success.

## Canonical relay persistence

For a task `<task_id>`, the v2 transport surfaces are:

```text
tasks/<task_id>/relay/raw.txt
tasks/<task_id>/relay/acceptance.json
tasks/<task_id>/relay/payload.txt
```

The ordering is:
1. validate relay against current task attempt and immutable bindings;
2. persist exact `raw.txt`;
3. persist derived `acceptance.json`;
4. persist exact UTF-8 `payload.txt`;
5. re-read and verify hashes;
6. only then perform any semantic/control-plane mutation required by the authored package.

An exact duplicate is a no-op; it does not rewrite or create a second canonical payload.

## Short fenced persistence

Only after a complete relay has been durably accepted does the actuator acquire an Agent Control Plane gateway fence if subsequent control-plane or target mutations require it.

That fence protects the mechanical persistence phase, not the earlier read-only reasoning phase.

The mechanical phase remains fail-closed:
1. re-read immutable request and current target bases;
2. claim/activate the gateway when required;
3. verify exact fence;
4. apply only exact authored operations whose base preconditions still match;
5. durably persist canonical result and terminal state;
6. re-read them;
7. release the gateway only after durable completion.

If a base commit/blob changed after the Agent authored its package, the actuator stops. It does not rebase or reinterpret the package.

If the actuator/runtime is lost during the short fenced phase, existing gateway recovery rules apply. The accepted raw relay and payload are already durable and may be resumed without re-running the reasoning Agent unless their base preconditions became stale.

## Identity rule

A relay runtime may reinstate at most one persistent Agent. It never becomes the caller or another Agent. Infrastructure probes reinstate no persistent Agent.

The mechanical actuator is transport infrastructure. Acting as actuator does not transfer project responsibility or persistent Agent identity.

## Executable validator

`tools/result_relay.py` is the executable source of the v2 envelope and acceptance rules. It provides:
- UTF-8 SHA-256 calculation;
- v2 encode/parse/validation;
- current-attempt rejection;
- exact payload-hash verification;
- acceptance-candidate construction;
- idempotent `accept-new` / `already-accepted` planning;
- fail-closed conflict detection.

`tests/test_result_relay.py` covers the acceptance invariants, including stale attempt, wrong nonce, wrong request binding, payload corruption, duplicate delivery and conflicting second delivery.

## Current operational status

v2 contract and executable acceptance logic are ready. The transport is still experimental until a full neutral end-to-end proof validates:
1. task/attempt binding;
2. separate runtime relay publication;
3. exact raw/payload durable acceptance;
4. deliberate runtime loss and retry with stale-output rejection;
5. deterministic mechanical completion;
6. terminal state ordering and no stranded lease.

Auditor remains suspended and recurring Broker/Worker remain disabled while this proof is in progress.
