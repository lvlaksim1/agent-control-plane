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

## Deliberately not started yet

- [x] 9. Retry/quarantine orchestration beyond the foundational state transition
- [x] 10. Explicit Gate engine
- [x] 11. Runtime reinstantiation contract/invocation package
- [x] 12. Completion evidence verifier
- [x] 13. Automatic DAG continuation
- [x] 14. First Scheduled Chat dispatcher (runtime proven; transactional gateway added after live safety-layer discovery)
- [x] 15. Sandbox E2E (completion-projection drift found, protocol corrected, gateway-backed E2E passed)
- [x] 16. Real PM/Auditor integration (strict PM attestation → PM-issued Auditor verification; runtime-loss recovery proven)
- [x] 17. Multi-entry human routing: direct Owner↔agent conversations remain first-class; PM→Auditor routing proven without Supervisor proxy
- [x] 18. Five-slot shared dispatcher pool (five hourly offsets active; gateway CAS race admission passed)
- [ ] 19. Fold proven protocol into Context Capsule / Service Agent Base
- [ ] 20. Resume Agent Catalog / Agent Factory scaling

Nothing in the unchecked section is authorized merely by appearing here.
