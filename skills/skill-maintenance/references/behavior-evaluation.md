# Bounded skill comparison

Use EXECUTED `scripts/blindeval.py --help`; `fresh-eyes` and `loop` must be installed beside it. The [eval method](../../eval-hillclimb/references/skill-evals.md) owns cases, leakage, comparisons and acceptance. Run only authorized model calls.

Fixtures contain task.md/setup and hidden expected.md/rubric.md. Rubric sections: Checks, Judge, Bar. Lint before calls; lexical leakage checks prove no real secrecy.

Compare whole skill folders and `none`; --also-skill stays loaded in every condition. Read actual artifacts/actions, not final claims. Resolve worker/judge settings through roles.py, never invented IDs.

`run` takes --fixture, named --candidate values, --baseline, --must-pass, model/effort, --repeat, --max-calls and empty --out. The call cap covers planned dispatches, not tokens/money/provider startup retries. --reuse judges one attempt only. Inspect every summary cell; errors/missing grades are failures, not agreement. Token usage remains unknown; do not estimate it from elapsed time.

The default worker is Codex with a workspace-write sandbox.
Operator configuration and execution rules remain active.
Claude uses `--safe-mode`, which disables custom steering while preserving permissions.
Claude write workers require explicit `--allow-unsandboxed-claude` approval because they retain host file access.
The flag does not disable operator deny rules. Use a disposable environment for untrusted tasks.
Initialization errors remain failures; the helper never switches authentication profiles automatically.
