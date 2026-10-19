---
name: fresh-eyes
description: >
  Dispatch a blind reviewer from fresh context so the author never grades their own work. Use for
  "fresh eyes", "second opinion", "unbiased review", or a fresh pre-merge check. Not a scored panel.
---
# Fresh Eyes

Use an executable check before model judgment. Small, low-risk judgment needs no dispatch; substantial subjective work gets one fresh reviewer. High-impact model-only judgment gets two independent lenses. Finish with evidence and a legal last-line verdict.

## Rules

Give reviewers only the charter, artifact and scope. Exclude author identity, prior verdicts, fix rationale, review records and commit narratives. The one exception: hunters may receive open/refuted findings ledgers; refuters and judges remain blind. Paste required standards in full; a subagent may not have the named skill.

## Dispatch

EXECUTED `scripts/freshctx.py` owns ephemeral CLI dispatch:

```bash
python3 <skill-dir>/scripts/freshctx.py detect
python3 <skill-dir>/scripts/freshctx.py dispatch --family other --charter <file> --artifact <file> --repo <checkout> --out <scratch>
```

When review is authorized and several independent reviewers apply, dispatch them at once, each with its own `--out`; they share no state. `--family other` selects cross-family judgment, falling back to same-family fresh context when unavailable/unknown. Label the actual route. Use `--role review` to resolve `assets/roles.json`; EXECUTED `scripts/roles.py <role>` prints settings. Explicit fields override role defaults; explicit family wins over `other`. Never invent model IDs or retry an account-rejected model unchanged.

The dispatcher starts a new conversation and preserves operator permission rules.
Claude uses `--safe-mode` to disable custom steering and hooks; the CLI must support that flag.
Codex keeps its configuration and execution policies while using an explicit sandbox.
A fresh conversation is not a clean profile; use an operator-approved profile when strict context isolation is required.
Claude write workers require explicit `--allow-unsandboxed-claude` approval and retain host file access.
Use disposable environments for untrusted tasks. Never discard permission rules to make a review cleaner. For runtime subagents, reproduce that boundary and ask for every finding, severity, location and preferred fix. End exactly `VERDICT: APPROVE` or `VERDICT: BLOCK`, or `SCORE: <n>` when requested. Apply [loop's grammar](../loop/SKILL.md#workflow); retry indeterminate judgment at most twice.

Keep the score threshold hidden from judges. Require executable or cited evidence for claims. For large artifacts, pass a small revision/hash/path manifest and require the complete artifact to be read; argument-limit failure is indeterminate.

## Composes with

Prompt reviews without `--repo` start in an empty temporary directory.
`--repo` sets the working directory; it does not restrict absolute file reads.
Use a disposable environment when inputs require filesystem isolation.

[Evidence scale](references/evidence-scale.md) owns claim labels. Return verdict, findings and evidence to the requesting workflow.
