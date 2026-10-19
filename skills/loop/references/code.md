# Structural quality

Freeze scope/base, project check, browser flows and aggressiveness. CHECK is blind structural review plus deslop, regression checks and affected flows. Require two consecutive approvals under the root opinion cap. FAIL-DEMO seeds a duplicate helper/type-silencing cast; HOLDOUT rotates lenses. Security/performance/domain correctness remain residual unless separately checked.

Ask for every cited finding: blocker, debt or simplification. Conservative blocks blocker only; standard adds structural debt; aggressive blocks every defensible finding. Reporting is never severity-filtered. Emit `VERDICT: BLOCK` for any blocking finding, otherwise `VERDICT: APPROVE`.

Prioritize duplicated ownership, unnecessary layers, mixed responsibilities, tangled control flow and suppression. Keep artifacts outside the diff; give reviewers no fixer rationale. Fix blockers, carry others to the report, then drive named flows.
