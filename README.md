# Public AI Skills

This is a manually curated public copy of my internal AI skills for Hermes.
My internal skills evolve as Hermes learns from real work.
I review, generalize, and clean selected changes before manually updating this repository.
The public copy does not sync automatically with the private collection.

These skills support AI and software engineering: debugging, code review, testing, Git workflows, browser verification, and skill improvement.
Personal integrations, private incidents, account settings, and machine-specific automation are excluded.
The public repository starts with separate Git history.

## Catalog

The collection contains 21 skills. Keep the folders together because some helpers import their siblings.

| Skill | Use it to |
|---|---|
| [`address-review`](skills/address-review/SKILL.md) | Fix pull request feedback and verify the changes. |
| [`agent-browser`](skills/agent-browser/SKILL.md) | Exercise web flows and inspect screenshots with a browser CLI. |
| [`believe`](skills/believe/SKILL.md) | Test a blocked claim through distinct, safe routes. |
| [`code-review`](skills/code-review/SKILL.md) | Review a change through independent finding, refutation, and judgment. |
| [`correct`](skills/correct/SKILL.md) | Prevent repeated coding mistakes through structure and checks. |
| [`deslop`](skills/deslop/SKILL.md) | Remove unnecessary clutter from a diff. |
| [`eval-hillclimb`](skills/eval-hillclimb/SKILL.md) | Improve measured quality or performance against a fixed baseline. |
| [`fix-bug`](skills/fix-bug/SKILL.md) | Reproduce a bug, repair its cause, and verify the original failure. |
| [`fix-conflicts`](skills/fix-conflicts/SKILL.md) | Resolve and finish a merge or rebase conflict. |
| [`fresh-eyes`](skills/fresh-eyes/SKILL.md) | Obtain an independent review from a clean context. |
| [`loop`](skills/loop/SKILL.md) | Repeat checks and fixes against a fixed acceptance bar. |
| [`open-pr`](skills/open-pr/SKILL.md) | Prepare a clear pull request from the reviewed diff. |
| [`principles`](skills/principles/SKILL.md) | Apply shared rules for scope, evidence, ownership, and decisions. |
| [`project-verification`](skills/project-verification/SKILL.md) | Create and run a project-specific feature verification recipe. |
| [`prune-tests`](skills/prune-tests/SKILL.md) | Remove useless or duplicate tests while preserving fault detection. |
| [`record-walkthrough`](skills/record-walkthrough/SKILL.md) | Record a captioned video tour with chapters and video checks. |
| [`release`](skills/release/SKILL.md) | Follow a project's existing release and publication process. |
| [`remove-comments`](skills/remove-comments/SKILL.md) | Remove ordinary comments while preserving required directives and behavior. |
| [`safe-push`](skills/safe-push/SKILL.md) | Check outgoing changes and push through the correct GitHub account. |
| [`skill-authoring`](skills/skill-authoring/SKILL.md) | Write focused skill instructions with clear ownership and checks. |
| [`skill-maintenance`](skills/skill-maintenance/SKILL.md) | Audit a skill library and route durable lessons into repairs. |

## Use with Hermes

Clone the complete collection:

```sh
git clone https://github.com/mchen04/my-public-ai-skills.git ~/my-public-ai-skills
cd ~/my-public-ai-skills
bash scripts/check.sh
```

Add this directory to `skills.external_dirs` in your active Hermes profile's `config.yaml`.
The default profile uses `~/.hermes/config.yaml`.
Merge this entry with existing settings:

```yaml
skills:
  external_dirs:
    - ~/my-public-ai-skills/skills
```

Use `hermes skills list` to check discovery, then request a relevant skill in chat.
A same-named local or project skill can shadow this copy.
See the [Hermes skill documentation](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills#external-skill-directories) for configuration and precedence.

Hermes can change writable external skills during use.
Use a separate working copy if you want local learning without changing your clean public checkout.
Review local edits before pulling updates.
When the checkout is clean, `git pull --ff-only` downloads manually published public updates.

Other agents can use the standard `SKILL.md` folders through their own skill installation system.
The package does not replace global agent instructions or install hooks.
These instructions do not grant account access, spending authority, or publication permission.

## Dependencies and layout

Use Python 3.10 or later, Git, Bash, and a macOS or Linux environment for the helper checks.
Python helpers use the standard library.
Install workflow tools only when needed:

| Tool | Used for |
|---|---|
| GitHub CLI (`gh`) | Pull requests, account-aware pushes, reviews, and release workflows. |
| Logged-in `claude` or `codex` CLI | Fresh reviews and authorized model evaluations. |
| [`agent-browser`](https://github.com/vercel-labs/agent-browser) | Browser verification and walkthrough recording. |
| `ffmpeg`, `ffprobe`, libass, libx264, and fonts | Walkthrough rendering and video tests. |
| Optional `node` and `npm` | JavaScript syntax checks and fallback CLI discovery. |
| Optional `fc-list` from fontconfig | Font discovery during walkthrough preflight. |
| A project's own build and test tools | Verification inside that project. |

Fresh review and evaluation settings use the installed CLI's default model.
Optional role settings live in `skills/fresh-eyes/assets/roles.json`.
Some folders include `agents/openai.yaml` for Codex interface and invocation settings.
Account mappings stay in the operator's local configuration, outside this repository.

```text
skills/       Skill instructions, references, helper scripts, and templates
evals/        Offline helper tests and synthetic routing cases
scripts/      Public-package checks and routing evaluation tools
.github/      Automated checks with read-only repository permissions
```

## Checks and evidence limits

```sh
bash scripts/check.sh
```

The gate checks skill shape, public file contents, local links, catalog coverage, Python and shell syntax, and helper behavior.
Its selftests plant unsafe inputs and confirm that the checks reject them.
Tests use temporary files, fake CLIs, synthetic credential files, and isolated local services.
Reviewers use read-only tools; evaluation workers default to Codex with a workspace-write sandbox.
Operator permission settings remain active. Claude requires a CLI supporting `--safe-mode`, verified with version 2.1.303.
Claude write workers require explicit `--allow-unsandboxed-claude` approval and retain host file access.
Use a disposable environment for untrusted artifacts. Runtime configuration can still influence a fresh conversation.
Video rendering tests skip when `ffmpeg` or `ffprobe` is unavailable; CI installs them.

The gate does not prove every workflow against real accounts, production applications, or every supported agent.
Live model routing is a separate authorized check:

```sh
python3 scripts/eval-triggers-model.py --target codex:default --limit 20 --seed 0
```

## Updates and reuse

I manually select engineering lessons from the internal collection, remove private context, and verify this public copy.
Each public update receives automated checks and an independent review before it is merged.
There is no automatic export job or private-repository history in this package.
See [MAINTENANCE.md](MAINTENANCE.md) for the publication process and [AGENTS.md](AGENTS.md) for contributor rules.

The collection uses the [MIT License](LICENSE).
Retain the notices in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) when redistributing adapted material.
