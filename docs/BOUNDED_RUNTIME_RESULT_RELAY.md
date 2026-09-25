# Bounded Read-Only Runtime Result Relay v1

This protocol exists because a separate Scheduled Chat runtime can reliably read GitHub and can update its own Scheduled Task metadata, while consequential GitHub writes from that runtime cannot be assumed available.

It is a transport protocol, not a new authority model.

## Core rule

A separate target runtime is split from durable mutation:

```
immutable task/request
        ↓
fresh read-only target runtime
        ↓
target Agent or infrastructure role authors one bounded relay envelope
        ↓
the runtime stores that envelope only in its own Scheduled Task prompt
        ↓
authorized mechanical actuator retrieves and validates the exact envelope
        ↓
raw envelope is persisted durably
        ↓
only now acquire a short gateway fence for mechanical GitHub mutations
        ↓
apply exact authored package → durable result/state → release
```

The read-only reasoning runtime never owns an autonomous gateway lease and never performs GitHub/Drive/Dropbox writes. Therefore runtime loss before relay publication leaves no gateway lease to recover.

## Authority boundary

The relay transport does not grant authority.

For a persistent Agent:
- identity, mandate and authority still come from the Agent home repository plus the immutable task grant;
- the Agent authors the semantic decision/package;
- the mechanical actuator MUST NOT reinterpret, improve, complete, rank or otherwise substitute its judgment for the Agent's;
- the actuator may validate syntax, immutable bindings, exact base preconditions and permitted effects, then apply the package mechanically.

Scheduled Task metadata is **non-canonical transport**. Canonical authority begins only after the exact raw relay is durably persisted in GitHub with transport provenance.

## Envelope

The Scheduled Task prompt is replaced with:

```
ACP_RUNTIME_RELAY_V1|<JSON object>
```

Required envelope fields:

- `schema_version=1`
- `relay_id`
- `transport_task_id` — the exact Scheduled Task id that carried the envelope
- `task_id`
- `request_digest`
- `request_blob_sha`
- `relay_nonce` — fresh nonce issued before the runtime starts
- `author_id`
- `author_kind` — `persistent-agent` or `infrastructure`
- `status` — `complete` or `blocked`
- `payload_kind`
- `payload` — JSON object authored by the runtime
- `authored_at_msk` — timezone-aware Moscow timestamp

The transport is intentionally bounded. The full prompt MUST be at most 12000 UTF-8 characters in v1. Larger work is split into coherent stages; the relay is not a file-transfer system.

## Admission and retry

Before launching a relay runtime the controller persists:
- immutable request binding;
- exact transport task id;
- fresh relay id and nonce;
- expected author.

The runtime re-reads those values and fails closed on mismatch.

If a runtime dies before replacing its prompt, no canonical result exists and no gateway resource is held. A retry MUST use a new transport task id, relay id and nonce. Late output from an older runtime is rejected by binding mismatch.

## Mechanical acceptance

The actuator may accept an envelope only when all expected bindings match exactly:
- task id;
- request digest and request blob SHA;
- relay id;
- relay nonce;
- transport task id;
- expected author;
- allowed payload kind;
- valid Moscow timestamp;
- size bound.

The actuator first persists the exact raw envelope unchanged. If validation fails, no semantic/target writes occur.

For `status=blocked`, the actuator may persist the blocker but MUST NOT fabricate a success package.

## Short fenced persistence

Only after a complete relay has been durably received does the actuator acquire an Agent Control Plane gateway fence if control-plane or target mutations require it.

That fence protects the **mechanical persistence phase**, not the earlier read-only reasoning phase.

The mechanical phase remains fail-closed:
1. re-read immutable request and current target bases;
2. claim/activate the gateway when required;
3. verify exact fence;
4. apply only exact authored operations whose base preconditions still match;
5. durably persist result and terminal state;
6. re-read them;
7. release the gateway only after durable completion.

If a base commit/blob changed after the Agent authored its package, the actuator stops. It does not rebase or reinterpret the package.

If the actuator/runtime is lost during this short fenced phase, existing gateway recovery rules apply; the raw relay is already durable and can be resumed without re-running the reasoning Agent unless its base preconditions became stale.

## Identity rule

A relay runtime may reinstate at most one persistent Agent. It never becomes the caller or any other Agent. Infrastructure-only probes reinstate no persistent Agent.

The mechanical actuator is transport infrastructure. Acting as actuator does not transfer project responsibility or persistent Agent identity.

## v1 operational status

The relay is experimental until an end-to-end proof validates:
1. read-only runtime relay publication;
2. exact retrieval and durable raw persistence;
3. post-relay gateway fencing;
4. deterministic mechanical completion;
5. release with no stranded lease;
6. retry rejection of stale relay ids/nonces.

Recurring Broker/Worker remain disabled while this proof is in progress.
