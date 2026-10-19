---
name: project-verification
description: >
  Create or maintain a project's own verify recipe and user-facing feature map, then run it to
  prove the app works. Use for "make a verify skill", "feature map", "verify this project".
---
# Project Verification

Keep the project's runnable recipe and feature map at .agents/skills/verify-project/. Finish when check and run pass at the current revision. An unrun recipe is a draft.

EXECUTED `scripts/verifyctl.py --help` owns commands/status codes. Read [recipe](references/recipe.md) for schema and browser setup.

## Workflow

1. Inspect repository start/health/harness commands. `verifyctl.py init --project . --app <name> --surface <http|cli|browser|desktop|library>` discovers candidates; reuse working harnesses.
2. Fill recipe.json/features.md with 3–5 actual user features, stable IDs, implementing source paths and observable expectations. Fix/report failure to start first.
3. Run check, run, then accept passing features. Drive browser steps through `agent-browser` with a run-specific session. Keep instance data/evidence outside the checkout.
4. For small edits use run --changed <base>; run all features for releases, dependency/platform changes or map maintenance. Use check --uncovered <base> to discover unclaimed changes.
5. For the tests, lint and type checks of a change, EXECUTED `scripts/testselect.py --base <base>` lists the covering commands and the rule behind each, for the touched packages only; `--run` runs them and keeps an audit log. Exit 3 means a changed file has no mapping: map it in `tests.json` beside the recipe, or run the full suite. Run `--full` once before merge.

## Triage

- product-regression: report/fix behavior, never rewrite the expectation merely to pass; product decisions appear as spec-changed.
- harness-failure: repair launch/probe/tool and rerun.
- source-changed/missing: inspect moved implementation, repair map, rerun and accept with reason.
- blocked: report exact env:/cmd: precondition; never count as pass.

## Composes with

`agent-browser` owns session hygiene. Install `loop` beside this skill: verifyctl imports ledgerio.py for receipts. Send reproduced regressions to `fix-bug`. Report feature states, retained report path and blockers.
