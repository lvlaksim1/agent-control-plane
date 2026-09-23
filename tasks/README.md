# Task storage

Production tasks will use:

tasks/<task_id>/request.json
tasks/<task_id>/state.json
tasks/<task_id>/checkpoints/<sequence>-<checkpoint_id>.json
tasks/<task_id>/result.json

request.json is immutable. state.json stores its canonical SHA-256 digest.

No production tasks are seeded in the foundation commit. Real-agent automatic execution remains disabled until the later integration phase.
\nOptional per-task files after v0.2 foundation:\n\n- `runtime.json` — retry/backoff/failure metadata;\n- `gates/<gate_id>.json` — durable blocking gates;\n- `result.json` — verified completion evidence.\n
Runtime immutability: `state.json.request_blob_sha` stores the exact Git blob SHA of immutable `request.json`. Scheduled Chat compares the current GitHub blob SHA directly; it does not need local hashing.
