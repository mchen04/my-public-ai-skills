# Authoring workflow

## Layout and validation

Keep frontmatter, always-needed decisions and resource links in SKILL.md. Use scripts for executable mechanics, references for conditional detail, assets for templates/data. Link every bundled helper; label it EXECUTED or READ. Scripts run noninteractively, bound output and fail with actionable diagnostics. Match the target repository's conventions for comments and documentation.

Anthropic suggests a SKILL.md under about 500 lines; split by situation well before that. Claude Code keeps roughly the first 5,000 tokens of an invoked skill after compaction, so the top of the file carries what every run needs.

Descriptions are third person, state what the skill does and when to use it, quote the phrases users actually say, and stay within the spec's 1,024 characters. Codex fits its skill list into a small share of context and shortens descriptions first, so the main use case leads.

The public gate checks skill shape and the 1,024-character description limit. Runtime context and learning limits depend on the installed agent version.

Portable keys: name, description, license, metadata, allowed-tools. Put Codex interface/invocation policy in agents/openai.yaml, not portable frontmatter. Add that file only when changing default interface or invocation; `release` is explicit-only. Do not use `disable-model-invocation`: it hides capabilities from Claude and fails Codex validation.

From the source checkout run `python3 scripts/eval-triggers.py` and `bash scripts/check.sh`. Portable single-folder check: [skillcheck.py](../../skill-maintenance/scripts/skillcheck.py). Installed relative paths do not imply the current project is this repository.

For a new/renamed skill, add ≥3 realistic positive trigger cases and sibling negatives. Add missed utterances before changing descriptions; compare model routing on held-out cases when authorized. Deterministic lexical checks do not establish model behavior. Use [behavior evaluation](../../skill-maintenance/references/behavior-evaluation.md) for requested comparisons.

Before writing a new skill, run its three tasks with no skill and record what goes wrong; the skill exists to fix those results. Run the same tasks on Claude and Codex when both will load it.

Number only ordered requirements: loop run records freeze Process/Workflow/How-it-works steps. Mark optional steps explicitly. [Enforcement map](../../skill-maintenance/references/enforcement.md) names structural checks; prove new ones red and green.

## Shared installations

Edit source, not installed copies or immutable releases. Use an authorized proposal path when publication is runtime-managed. Check for destination name collisions, then verify discovery, actual skill_view, source hashes and installed acceptance. Retire authorized interim copies after shared publication. Keep receipts outside disposable workspaces.
