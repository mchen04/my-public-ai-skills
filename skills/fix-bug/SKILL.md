---
name: fix-bug
description: >
  Reproduce broken behavior, fix its root cause, then verify the repro and regressions. Use for
  "fix this bug", "debug and fix", or "reproduce then fix". Not for coverage on working code.
---
# Fix Bug

Done means the original reproduction now passes, relevant regressions and required checks pass,
and the fix is committed with a regression test where one fits.

## Process

1. Reproduce the reported failure before editing. Record inputs, state, and environment. Use the
   smallest failing test or script; for a visible UI bug, prefer a browser end-to-end check.
   Without a local repro, diagnose from logs, traces, and code, and ask only for conditions that
   block progress.
2. Apply [fix-root-causes](../principles/references/fix-root-causes.md) to repair the first wrong
   decision. When evidence refutes a hypothesis, revert every change that it motivated. Code that
   "might help" is a hypothesis, not a fix, and it does not ship.
3. Rerun the original reproduction, relevant regressions, and repository-required checks under
   [prove-it-works](../principles/references/prove-it-works.md). Chain
   commands fail-fast so a later command cannot mask a failure. For a UI bug, verify the real
   app. Separate existing failures from regressions introduced here.
4. Keep a durable regression test when practical. For an external flake or a one-off environment
   issue, record the evidence and the test limitation instead of adding a brittle test.
5. Commit the fix and regression coverage locally. Report the cause, the change, the observed
   checks, and any remaining uncertainty. Continue publication when authorized; otherwise leave
   pushing to `safe-push`.

Keep unrelated bugs and other sessions' work outside the change. A fix you could not run against
the repro stays `claimed` on the `fresh-eyes` evidence scale.

## Composes with

- `agent-browser` — reproduce and verify visible UI behavior.
- `safe-push` — publishes authorized fixes; `open-pr` opens an authorized PR.
