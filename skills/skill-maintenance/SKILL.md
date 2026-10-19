---
name: skill-maintenance
description: Audit Agent Skill libraries and route session lessons into repairs or checks. Use for misrouting, drift, bloat, or reflection. Not for writing a skill (skill-authoring) or eval optimization.
---
# Skill Maintenance

Audit libraries or route lessons into repairs/checks. Use [audit](references/audit.md) for drift, routing and bloat; [reflect](references/reflect.md) for session lessons. Load [skill-authoring](../skill-authoring/SKILL.md) before writing a repair.

Finish with observed checks, unresolved findings and evidence limits. Do not require model comparisons for every cut. Use [behavior evaluation](references/behavior-evaluation.md) for requested comparisons or disputed decision changes; the caller owns its acceptance bar.

Run source-root `scripts/check.sh`. EXECUTED `scripts/skillcheck.py` validates one skill folder; `scripts/blindeval.py` compares bounded skill variants. [Enforcement](references/enforcement.md) maps checks.

Push only when the user asks.

## Composes with

`fresh-eyes` dispatches blindeval workers/judges.
