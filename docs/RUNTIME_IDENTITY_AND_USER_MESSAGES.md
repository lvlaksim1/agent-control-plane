# Runtime identity and user-visible messages

An Owner-facing runtime keeps one persistent `agent_id` for its lifetime. A request that targets another persistent Agent crosses a mandatory runtime boundary.

## Interactive delegation

The caller writes the child task to GitHub and remains itself. The target is reinstantiated by the scheduler in a separate runtime.

Keep authority/responsibility semantics version 2. Add immutable execution-policy constraints:
- `runtime:separate-target`;
- `continuation:manual-pull`.

After the child finishes, its result stays durable in GitHub. No automatic caller runtime is created. When the Owner later asks the caller to check progress or results, the caller reads that exact durable state/result.

## Autonomous delegation

Use `runtime:separate-target` plus `continuation:automatic-new-runtime`. Before the caller execution ends, it precreates a caller-continuation task that depends on the exact child and carries `runtime:caller-continuation`.

The child still runs separately. After its verified completion, the dependent continuation becomes READY and a later Worker runtime reinstantiates the caller. The completed child is not executed again.

## User-visible source header

Every ecosystem entity that emits user-visible text starts with:

`DD.MM.YYYY · HH:MM MSK · <source_id>`

Persistent Agents use their exact `agent_id`. Infrastructure uses a stable `component_id`, such as `wake-broker` or `execution-worker`. Timezone is always `Europe/Moscow`.

A missing or mismatched header is a protocol violation and continuity warning, but the header is not proof of identity. Authoritative identity still comes from repository reinstantiation.
