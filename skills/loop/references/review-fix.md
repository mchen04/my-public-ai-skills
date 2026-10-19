# Review-fix template

Use for a diff you wrote that must finish clean and working. Initialize `--converge 2 --max-cycles 3`, matching code-review's round cap.

Freeze the [generic charter](charter-template.md): CHECK is `code-review` plus every registered behavior flow; BAR is zero gating survivors, all flows passing and project checks no worse than baseline. OWNER is blind hunters/refuters. HOLDOUT is the pre-fix flow inventory and rotated crown-jewel dimension; RESIDUAL lists unreached surfaces.

Before fixes, EXECUTED `scripts/flowctl.py register --inventory <outside-repo> --base <pre-fix-sha> --flow '<user path>'` freezes product flows. Include unexercisable ones as unverified. Demonstrate one known break via `fail-demo` and restore it.

Each cycle: blind review, exercise every flow through `agent-browser`/project E2E, fix surviving findings via `address-review`, rerun the checks that cover the fixes, then record. Reset inventory before the next exercise; keep the fail-demo. Use `flowctl.py check` receipts or `record` with evidence, then `status`.

PASS requires `VERDICT: APPROVE`, inventory `VERDICT: PASS`, recorded fail-demo and baseline-preserving checks. Unverified flows fail. Report unresolved finding, actual flow result and missing coverage; product decisions requiring authority stop the cycle.
