---
name: open-pr
description: >
  Open a GitHub PR: inspect the diff, choose its base, and write the title and body. Use for opening a branch for review. Not for branch pushes alone (safe-push) or merging.
---
# Open PR

Open a reviewable PR explaining the problem, resulting behavior and relevant design/validation evidence.

## Process

1. Resolve account/pinned base through [safe-push](../safe-push/SKILL.md). Otherwise use the named base or repository default.
2. Fetch through its wrapper. Inspect both origin/<base>..HEAD and HEAD..origin/<base>. Unexpected outgoing commits suggest the wrong base; check branch ancestry/recent PR bases. Report divergence and existing PR conflicts; do not silently rewrite reviewed history.
3. Read the diff and commit messages. Group changes by reviewer-relevant behavior.
4. Sweep branch artifacts this run created: logs, screenshots, generated reports and scratch files. Leave requested deliverables and pre-existing files. Commit tracked removals.
5. Write the title/body below. Use `safe-push` if remote head differs, then account-wrapped `gh pr create --base <base> --title … --body-file <file>`; use --draft when requested. Never merge. Return the URL.

## Title and body

Conventional title: type(scope): imperative summary, ≤50 characters, no period; ! marks breaking behavior.

```markdown
## Why
Concrete problem and approach.
## What
Resulting behavior.
## How
Decisions and tradeoffs needed for review.
## Testing
Observed checks, edge cases, UI evidence.
## Notes
Applicable issue links, migration, risks and rollback.
```

Drop empty sections. Large inseparable PRs need reading order; avoid file-by-file narration already visible in the diff.

## Composes with

Use `safe-push` for remote writes and `fix-conflicts` for conflicts.
