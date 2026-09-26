# Mailbox-pool result transport

This transport is used when a Scheduled Runtime can reason and write a separate disabled Scheduled Task mailbox but cannot be trusted to perform consequential GitHub writes.

The mailbox is transport only. Canonical task authority and lifecycle remain in GitHub.

## Exact acceptance bindings

Every accepted `ACP_MAILBOX_RELAY_V1` is bound simultaneously to:

- immutable ACP task/request: `task_id`, `request_digest`, `request_blob_sha`;
- current transport attempt: `logical_attempt`;
- current ACP fence: `execution_id`, `execution_generation`;
- semantic/mechanical author: `author_id`;
- Scheduled Runtime producer: `producer_task_id`;
- physical mailbox admission: `mailbox_task_id`, `mailbox_id`, `mailbox_generation`, `admission_nonce`;
- relay identity/integrity: `relay_id`, `relay_nonce`, exact UTF-8 `payload_sha256`.

A mailbox exposed to a lost or suspect producer is quarantined forever for that pool epoch. A retry advances `logical_attempt` and receives a different physical mailbox.

## Completion order

1. Validate the relay against current task, request, execution and mailbox admission.
2. Persist the exact raw authored relay to GitHub without semantic reinterpretation.
3. Re-read it and verify exact bytes/digest.
4. Persist the evidence-backed ACP `result.json`.
5. Persist and re-read terminal `state=completed` with `claim=null`.
6. Only then release the gateway fence.

A late relay from an older logical attempt is evidence of stale execution, never a candidate to replace the accepted result.
