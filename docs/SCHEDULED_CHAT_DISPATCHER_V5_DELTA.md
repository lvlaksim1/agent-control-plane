# Dispatcher v5 delta — fixed Agent identity per runtime

This delta supersedes older dispatcher text wherever it permits one live Owner-facing runtime to switch from one persistent agent_id to another.

## Mandatory runtime boundary

New inter-agent work follows:

caller runtime -> durable GitHub task -> Wake Broker -> Execution Worker -> separate target runtime.

The caller runtime never becomes the target Agent. The target runtime never becomes the caller Agent after completion.

## Interactive delegation

Use responsibility semantics v3 with continuation_policy=manual_pull.

The child executes separately and stores its result in GitHub. No automatic caller continuation is created. The Owner later asks the original caller Agent to inspect the durable result.

## Autonomous delegation

Use responsibility semantics v3 with continuation_policy=automatic_new_runtime.

After verified child completion, persist a pending caller continuation. Broker/Worker later reinstantiates the caller in a new runtime and the caller acknowledges that continuation before consequential work.

## Live carrier

A live carrier may protect work performed by the same persistent Agent already bound to an Owner-facing runtime. It must never authorize an agent_id switch.

## User-visible messages

Wake Broker, Execution Worker, and reinstantiated Agents follow runtime/user-message-policy.json whenever they emit user-visible text.
