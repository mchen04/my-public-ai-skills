---
name: prune-tests
description: >
  Audit a test suite and delete useless, duplicate, or tautological tests. Use for "drop the tests
  that are not useful", "tests that pass no matter what", or "which can I delete".
---
# Prune tests

Delete tests proven useless or redundant. Finish only when the surviving suite still detects its
protected failures and covers every asserted behavior it covered before. Preserve regression,
boundary, and failing tests.

Read [references/audit.md](references/audit.md) when you judge tests, probe mutations, verify
deletions, or report. It owns the deletion criteria, preservation rules, mutation safeguards, and
before-and-after checks.

## Process

1. Record the baseline with the same command and flags you will use for the final check.
2. Judge each test under `audit.md`, and apply its preservation rules before any deletion.
3. Probe uncertain claims in an isolated tree. Restore each mutation and prove that useful failure
   cases stay detected.
4. Verify the pruned suite and report the measurements and reasons that `audit.md` requires.

Keep the deletions in one commit, separate from behavior changes, so the removal reverts on its own.

## Report

Under [loop's verdict grammar](../loop/SKILL.md#workflow), when it binds this skill as CHECK, the last line is exactly `VERDICT: PASS` or
`VERDICT: FAIL`. Return `FAIL` while a proven-dead tautological or duplicate test that is eligible
for deletion remains, or when a mutation the baseline catches survives the pruned suite. Return
`PASS` when no test is proven dead and eligible, and asserted behavior stays covered.

## Composes with

- `safe-push` — the deletion commit stays local until you ask for a push.
