# Reproduce gating claims

Read project build/CI commands. Run probes only in scratch worktrees, fakes or disposable databases, never the author's tree or real services. Do not build a stack for naming nits.

For migrations, use the project's database major version and verbatim reviewed files. Seed prior state through a reachable user sequence; an impossible hand-inserted row proves no defect. Determine whether startup applies an atomic group and whether failure rolls it all back.

Inspect exact-head CI legs and executed test counts; a green job name is insufficient. Record actual decisive output, runtime/database version and head/base. Classify unexecuted claims honestly under the [evidence scale](../../fresh-eyes/references/evidence-scale.md).
