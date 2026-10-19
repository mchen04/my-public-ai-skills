# Missed-failure checks

Give hunters/refuters these checks when applicable:

- Compare recorded resource availability with actual running state before reuse; crashes can separate them.
- Replaced authentication proofs must establish the same identity/authority as the removed step.
- Migration statements share transaction locks; separate long index builds when lock duration matters.
- Check every process/child environment sharing a secret, not just its intended consumer.
- Prove private networks unreachable from inside untrusted job runners.
- Check queued code provenance before minting its credentials; a platform fork setting is insufficient.
- Identify the behavior protected by each removed test and demonstrate retained detection.

The root owns spec-as-claim, trust tracing and severity. Add a trap only after a finished review missed a real defect; keep incident details private and add a synthetic regression when reproducible. At 25 traps, merge/delete before adding.
