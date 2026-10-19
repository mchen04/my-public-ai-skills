# Public checks

[Skill Authoring](../../skill-authoring/SKILL.md) owns writing. [Principles](../../principles/SKILL.md) owns shared decisions.

| Rule | Check | Limit |
|---|---|---|
| Skill names, descriptions, and layout | `skills/skill-maintenance/scripts/skillcheck.py` | Structural validity only. |
| Public files and local links | `scripts/check-public.py` | Detects credentials, personal home paths, unsafe bundles, and broken references. Human review still checks meaning. |
| Trigger coverage | `scripts/eval-triggers.py` | Case coverage only; model routing needs an authorized live run. |
| Workflow evidence | `loopctl.py`, `flowctl.py`, and `runctl.py` selftests | Synthetic evidence and refusal cases. |
| Skill comparison | `blindeval.py selftest` | Harness checks only; real model quality needs real tasks. |
| Helper behavior | `evals/*-test.py` and `evals/*-test.sh` | Offline cases and isolated local services. |

`bash scripts/check.sh` runs all these checks.
Privacy judgment, permission interpretation, editorial quality, and live service behavior require separate evidence.
