# Task storage

Production tasks will use:

tasks/<task_id>/request.json
tasks/<task_id>/state.json
tasks/<task_id>/checkpoints/<sequence>-<checkpoint_id>.json
tasks/<task_id>/result.json

request.json is immutable. state.json stores its canonical SHA-256 digest.

No production tasks are seeded in the foundation commit. Real-agent automatic execution remains disabled until the later integration phase.
