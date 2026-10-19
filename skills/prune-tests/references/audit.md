# Test audit criteria and proof

## Contents

- What a good test looks like
- Deletion candidates
- Probe when you are not sure
- Keep these, even when they look bad
- Prove the suite did not get weaker
- Report

## What a good test looks like

A useful test asserts behavior that survives a behavior-preserving refactor, can fail on a
realistic fault, and mocks only true externals. Failing one of these is a deletion candidate under
the criteria below. Naming and failure-message problems call for a rename or split. Nondeterminism
is a test bug to repair or delete; never leave it flaky.

## Deletion candidates

Apply the preservation rules below first. Read each test, confirm the description fits, and delete
eligible tests:

- **No assertion at all**, or one that cannot be false (`assert True`, `assert x == x`), or every
  assertion sitting behind a condition that is never reached.
- **Asserts the shape of the code**: call counts and call order on the unit under test, or mocks of
  the very thing being tested. These fail on every refactor and pass on every real bug.
- **Tests the framework** — exercises the language, standard library, ORM, or a third-party package
  rather than your code.
- **Snapshots nobody reads**, regenerated wholesale whenever they break.
- **Commented-out, skipped, or permanently-xfailed** tests with no linked issue.

## Probe when you are not sure

Probe a suspected duplicate or unfailable test before deciding. Break the behavior it claims to
protect: invert a condition, drop a guard, or return a wrong constant. Run only that test.

| Result | Meaning |
|---|---|
| goes red | it detects this fault; keep it |
| stays green | it misses this fault; apply the deletion and preservation rules |

One surviving mutation does not prove that a test can never fail. Delete only after proving it
dead under the criteria above or redundant with surviving coverage.

Tests may load code through `dist/`, a linked package, or a compiled bundle. For these tests,
rebuild after mutation and again after restoration: an unchanged build cannot prove the mutation
result, and a stale build hides the restoration. Probe only in a tree no other process edits, so
restoration cannot damage other work.

Restore the mutation before any other action, and use `git diff` to confirm earlier edits
survive. Several tests can fail one mutation while protecting different inputs. Remove one only
when the surviving suite still detects its failure cases.

## Keep these, even when they look bad

- **Slow** is not useless — move or mark it, do not delete it.
- **Ugly** is not useless — bad naming and messy setup are refactor targets.
- **A test you do not understand** protects something. Read the commit that added it first.
- **The only test for a boundary** — a weak test on an uncovered edge beats nothing. Improve it.
- **Regression tests tied to a bug or incident.** Their value is historical, not structural.
- **Failing tests.** A red test is a finding, never a deletion candidate. Report it and leave it.

## Prove the suite did not get weaker

Use the same command and flags before and after pruning. Record test count, runtime, coverage,
and tests that already fail. No previously passing test may fail afterward, and asserted behavior
must stay covered. Line coverage may drop only by lines that deleted assertion-free tests
alone ran, since those tests checked nothing. Attribute every drop, and say when coverage is
unavailable. Run each probe mutation again against the pruned suite. If the baseline detects a
mutation and the pruned suite misses it, restore the deleted test.

## Report

Report files, named cases, parameterized executions, and removed assertion executions separately;
deduplicating an assertion may add a named test without deleting cases. Give before/after
pass/fail/skip counts, runtime, and coverage; match retained cases by stable ID so aggregate totals
cannot hide regressions. Give one line of reasons per deleted group. Name tests kept because you cannot prove them dead, and report uncertain cases to
the user instead of deleting them.
