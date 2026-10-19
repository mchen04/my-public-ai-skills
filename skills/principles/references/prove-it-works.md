# prove-it-works

- Pair each acceptance requirement with an executed check.
- Run a known-bad control before trusting a new gate.
- Read published output back from its real destination.
- While you iterate and in every fix round, rerun only the tests, lint and type checks that cover
  the changed code. [project-verification](../../project-verification/SKILL.md)'s `testselect.py`
  picks them and reports a file it cannot map as unknown, which is never a pass. Run the full
  suite once, before the final commit or merge, or let CI run it. Mark unreached surfaces untested.

Owners: [fresh-eyes evidence scale](../../fresh-eyes/references/evidence-scale.md), [project-verification](../../project-verification/SKILL.md), [release](../../release/SKILL.md).
Enforcement: the loop run record validates evidence labels; destination coverage still needs judgment.
