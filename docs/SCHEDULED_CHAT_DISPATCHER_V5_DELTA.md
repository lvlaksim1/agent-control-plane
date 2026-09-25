# Dispatcher v5 delta — fixed Agent identity per runtime

This delta supersedes older dispatcher text wherever it permits one live Owner-facing runtime to switch from one persistent `agent_id` to another.

## Mandatory runtime boundary

New inter-agent work follows:

caller runtime -> durable GitHub task -> Wake Broker -> Execution Worker -> separate target runtime.

The caller runtime never becomes the target Agent. The target runtime never becomes the caller Agent after completion.

## Compatible request encoding

Keep the proven authority/responsibility contract at `responsibility.semantics_version=2`.

The immutable task `constraints` additionally carry execution policy:

- every delegated target task: `runtime:separate-target`;
- Owner-facing interactive delegation: `continuation:manual-pull`;
- autonomous delegation: `continuation:automatic-new-runtime`.

These execution constraints do not expand authority.

## Interactive delegation

For `continuation:manual-pull`, the child executes separately and stores its result in GitHub. No automatic caller continuation is created. The Owner later asks the original caller Agent to inspect the exact durable result.

## Autonomous delegation

For `continuation:automatic-new-runtime`, the caller precreates a separate caller-continuation task before ending its own execution. That task:

- targets the original caller;
- depends on the exact child task with `depends_on`;
- carries `runtime:caller-continuation`;
- remains blocked until the child reaches verified terminal completion.

When READY, the Execution Worker reinstantiates the caller in a new runtime. The caller reads the exact child result before consequential continuation. The completed child is never re-executed.

## Live carrier

A live carrier may protect work performed by the same persistent Agent already bound to an Owner-facing runtime. It must never authorize an `agent_id` switch.

## User-visible messages

Wake Broker, Execution Worker, and reinstantiated Agents follow `runtime/user-message-policy.json` whenever they emit user-visible text.
