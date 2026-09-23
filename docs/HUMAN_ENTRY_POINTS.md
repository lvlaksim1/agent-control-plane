# Human entry points and inter-agent routing

The Agent Control Plane does **not** make Supervisor a mandatory human gateway.

## Human interaction

The Owner may directly open and work with any persistent agent, including a Project Manager, Auditor, Specialist, Supervisor, or future Agent Factory role.

Direct Owner ↔ Project Manager conversation is the normal path for active project development. It does not consume dispatcher slots and does not require Supervisor participation.

Supervisor is used for portfolio/ecosystem coordination, cross-project dependencies, agent architecture, governance, and work that actually falls within the Supervisor mandate.

## Agent-to-agent routing

Authorized persistent agents may create bounded tasks for other agents through the control plane when their mandate/engagement permits it.

Examples:

- Project Manager → Auditor for independent verification.
- Project Manager → Specialist for narrow expertise.
- Supervisor → Project Manager for explicitly authorized coordination.
- Auditor → Supervisor only for coordination/escalation, not to transfer target ownership.

A task envelope cannot expand either the issuer or target agent mandate.

## Scheduler role

Scheduled Chat slots are autonomous continuation workers, not the human conversation transport.

The Owner's direct chat with an agent is immediate and independent of the five-slot dispatcher pool. Dispatcher latency only applies to autonomous continuation between chats/agents.

## Routing invariant

No routing topology is allowed to turn Supervisor into an obligatory development proxy or centralize project ownership outside each Project Manager.
