---
name: eval-hillclimb
description: >
  Hill-climb a skill, prompt, or app with evals, keeping only gains beyond noise. Use for "eval
  this skill", "performance hill climb", "make it faster". Not for bugs, until-clean loops, or
  new skills.
---
# Eval Hill-Climb

Keep only gains beyond measured noise against a frozen quality bar. Finish with numbers for every kept/rejected round; report "No real gain" when nothing qualifies.

Read [skill evals](references/skill-evals.md) for prompts/tools or [performance](references/performance.md) for speed, cost, memory and size.

## Scope and consent

Loading this skill authorizes no experiments, paid runs, other targets, or publication. An audit request authorizes findings only. Follow host permission, spending, and publication rules. Check consent and retention before using personal/production data. Redact secrets. Never send private examples or traces to a service the user has not approved.

## Process

1. Freeze target, objective, allowed edits, fixed settings, smallest useful gain and time/money/round budgets. Honor explicitly ongoing optimization; otherwise propose a cap. Whole-app scope uses the performance reference's inventory.
2. Isolate changes and record the baseline revision. Never edit a live shared release in place.
3. Freeze tests, graders and allowed losses. Split held-out data first. Prove the bar can fail.
4. Repeat the baseline under fixed conditions. Record median, spread and sample size. Use the larger of baseline spread and smallest useful gain as the noise threshold.
5. Profile or inspect training failures. Make one hypothesized change; measure baseline and candidate interleaved under identical conditions.
6. Keep only gains beyond noise with no quality/held-out regression. Revert rejected changes file by file; commit each accepted change separately as the next baseline.
7. Log each round outside the repository. After two no-gain rounds, change hypothesis/path. Stop at objective, authorized cap or exhausted paths; pause on unexplained quality failures.
8. Rerun the complete bar and untouched final set once. Use `fresh-eyes` when judgment needs blind grading. Report gains, rejected changes and limits.

## Boundaries

Do not tune on held-out/final data, paste answers or special-case benchmarks. Version grader/test repairs and rerun both baseline and candidate; retain original evidence.

Never remove safety checks, permission checks, error handling, or required tool calls to save time or cost.

Apply [saved artifact acceptance](references/performance.md#saved-artifact-acceptance) before keeping exports or deleting source copies. Passing evals do not authorize deployment. Publish through the host's path and read back the exact result before you claim publication.

## Composes with

Use `loop`'s ledger and autonomous run record; `agent-browser` for visible measurements.
