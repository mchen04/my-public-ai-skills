# Library audit

Gather usage only from transcripts the user authorizes you to read. Check capture coverage before inferring non-use; zero means not observed, not unused. Spot-check current commands, catalog cost, duplicated ownership and recent source churn. Usage frequency is not outcome quality.

Use EXECUTED `scripts/skillcheck.py` for each source skill folder. Check installed copies through the target runtime's discovery tools. Separate source validity, observed behavior and installed state.

Fix demonstrated drift in its owner. Add wrong/missed trigger utterances before tuning descriptions under [authoring](../../skill-authoring/SKILL.md). Evaluate disputed behavior through [blindeval](behavior-evaluation.md), not word counts. Record symptom, change, evidence and uncertainty outside the product.

Never delete a skill without explicit user approval; everything else in `skills/` is fair game. Transcripts are read-only evidence: never edit or delete them. Push only on request, through `safe-push`.
