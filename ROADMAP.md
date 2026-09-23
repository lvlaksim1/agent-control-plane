# Roadmap

## Foundation completed in this stage

- [x] 1. Control-plane specification
- [x] 2. Dedicated infrastructure repository
- [x] 3. Agent Registry v1
- [x] 4. Immutable Task Envelope
- [x] 5. Task Graph + deterministic READY resolver
- [x] 6. GitHub-CAS global runtime lease
- [x] 7. Fencing protocol
- [x] 8. Checkpoint/recovery contract
- [x] 9. Retry/quarantine orchestration
- [x] 10. Explicit Gate engine
- [x] 11. Runtime reinstantiation contract/invocation package
- [x] 12. Completion evidence verifier
- [x] 13. Automatic DAG continuation
- [x] 14. First Scheduled Chat dispatcher
- [x] 15. Sandbox E2E
- [x] 16. Real PM/Auditor integration
- [x] 17. Multi-entry human routing
- [x] 18. Five-slot shared dispatcher pool
- [x] 19. Fold proven protocol into Context Capsule / Service Agent Base
- [x] 19.5 Event-driven wake + reusable execution worker + Wake Broker/hourly watchdog
- [ ] 20. Resume Agent Catalog / Agent Factory scaling

Item 19.5 is complete and independently verified. Live validation replaced unsafe Worker self-rearm with a two-slot cross-task Broker relay, task-scoped live carriers, and crash-safe partial live-completion recovery. EW-001..EW-003 and PTC-001..PTC-003 are CLOSED / High confidence. Item 20 remains inactive.
