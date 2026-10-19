---
name: loop
description: >
  Repeat check, fix, recheck until clean, or red-team an artifact and track each finding to done.
  Use for "until clean", "review loop", "attack this", "IDOR", "fuzz", or "launch-ready".
---
# Loop

Repeat check/fix/verify until the frozen bar passes N consecutive cycles (default 1; failure resets the streak), or a named stop. Close every finding as fixed+verified, refuted with evidence or externally blocked.

Load one template: [code](references/code.md), [review-fix](references/review-fix.md), [security](references/security.md), [red-team](references/red-team.md), or [generic charter](references/charter-template.md). Do not combine templates. Use a direct sibling for one-pass work.

## Frozen contract

Freeze ORACLE (real signal), CHECK (command/dispatch), BAR (criteria), OWNER (independent verifier), FAIL-DEMO (known-bad input), HOLDOUT (unseen probe), RESIDUAL (unproven scope). Prove red before cycle 1. Restore fixtures individually, never with checkout/reset/stash.

**CHECK may dispatch a sibling skill.** Bind exactly one grader and name it: `code-review` for a graded diff, `agent-browser` for user-visible behavior, `prune-tests` for suite quality.

Opinion graders use `fresh-eyes`, `--max-cycles 8` at init and increased N. The review-fix template has its own three-cycle cap. Executable checks keep the unbounded default. Fixers never vote.

## Workflow

1. Record project-check baseline and dirty paths. Never commit, stash, reset, or absorb unrelated work.
2. Resolve base/branch and initialize the ledger outside the repository:

   ```bash
   python3 <loop-dir>/scripts/loopctl.py init --log <scratch/log.md> --loop '<name>' --base <base> --converge <N> --test '<cmd-or-auto>'
   ```

3. For autonomous/selected workflows, freeze steps with [run-record](references/run-record.md).
4. CHECK and require the exact last line `VERDICT: PASS`/`VERDICT: FAIL` or `VERDICT: APPROVE`/`VERDICT: BLOCK`. Missing/ambiguous tokens are indeterminate and never advance the streak.
5. FIX every in-scope failure; VERIFY project checks against baseline. Repair harness/environment failures in their owner, without changing the artifact to satisfy a broken observer.
6. RECORD with `loopctl.py record`, then `status`. Use a findings count or stable labels. For commands, `loopctl.py check --log <log> -- <command>` produces the receipt passed to record.

`loopctl.py`, `flowctl.py`, `runctl.py` and `ledgerio.py` are EXECUTED. Helpers own ledger invariants. Only `loopctl.py bar --reason <why> --authorized-by <human>` changes the frozen bar.
`runctl.py` uses the sibling `safe-push` credential scanner for worker records and environment checks.

## Stops

Read [stuck signals](references/stuck-signals.md) when findings recur or progress stalls. Finish/revert the current change before cap/cost/interruption exit. Continue while cycles remain; stop for real input/authority boundaries. Before reporting done, run `runctl.py steps gate` when a record exists. Report exit reason, streak, fixes, blockers and observed checks within 12 lines.

## Composes with

Use `address-review`/`fix-bug` for fixes. The code template calls `deslop`.

Use the [evidence scale](../fresh-eyes/references/evidence-scale.md) when labeling worklog claims.
