# Write-actuator reality check — 2026-09-26

Status: canonical correction to `UNATTENDED_RUNTIME_ARCHITECTURE_B_2026-09-26.md`.

## Correction

Historical Phase B demonstrated the **ordering semantics** required for a correct closeout:

1. target work runs in a later runtime;
2. exact result is persisted;
3. task state becomes terminal;
4. terminal state is re-read;
5. gateway is released only afterwards.

However, Phase B did **not** demonstrate an independent non-Scheduled mechanical write actuator.

The historical `Execution Worker` itself was a ChatGPT Scheduled Runtime. It directly performed the GitHub task/result writes and created the gateway Issue request. Therefore it used the same class of Scheduled Runtime write capability that later isolated probes showed is not dependable.

The public `agent-control-plane-gateway` GitHub Actions workflow is a deterministic actuator for **gateway lease state only**, after it receives an accepted GitHub Issue event. It is not a proven general result writer, and the required Issue creation from Scheduled Runtime is itself not dependable.

## Proven boundary

Proven:
`Scheduled target Agent Runtime -> separate disabled Scheduled Task mailbox`.

Not proven:
`accepted mailbox -> autonomous canonical GitHub result/state persistence`.

No current production primitive has been demonstrated for that second edge under the active constraints:
- no Work;
- no OpenAI API;
- no dependence on generic Scheduled Runtime GitHub writes;
- no old recurring Broker/Worker;
- no unproven Preview egress.

## Consequence for Variant B

Variant B may retain:
- minimal unattended launcher;
- separate target Agent Runtime;
- physical mailbox rotation/quarantine;
- exact mailbox validation;
- relay-v2 short-fence ordering as the desired closeout semantics.

But Variant B is **not end-to-end autonomous** until a genuinely independent invocation/write primitive exists for the mailbox -> GitHub boundary.

Do not describe the old Phase B Worker as a proven external write actuator.
