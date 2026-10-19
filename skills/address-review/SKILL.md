---
name: address-review
description: >
  Fix PR review feedback end to end: fix each comment, check, commit, push. Use for "review
  comments", "address feedback", or "fix PR notes". Not for writing a new review.
---
# Address PR Review

Finish each unresolved comment with a checked fix or an evidenced answer. Stop before the push only when the user says "don't push" or "local only".

## Workflow

1. Resolve the PR repository and `headRefName` with `gh pr view`. Use its checkout or an isolated worktree. Record dirty paths and the project's check baseline.
2. Fetch all unresolved `reviewThreads` with GraphQL, including older rounds; paginate. Add requests from review bodies (`gh pr view --json reviews`); skip the author's own comments. Put the user's scope boundary atop the checklist.
3. Reproduce bug claims through [fix-bug](../fix-bug/SKILL.md). Edit naming and style directly. Resolve product choices from the user's direction; ask only when the evidence leaves alternatives.
4. Apply [open-pr's artifact sweep](../open-pr/SKILL.md#process). Keep deliverables and pre-existing files. Run cleanup or independent review only when requested.
5. Rerun the checks that cover the fixes against the baseline, as [prove-it-works](../principles/references/prove-it-works.md) scopes them. Exercise changed UI through `agent-browser` or the project's verification recipe.
6. Commit the addressed feedback and push through `safe-push`. Wait for CI with `gh pr checks --watch`, and classify each failure before any rerun. A flake or infrastructure failure gets one fresh run, and an identical second failure is real. When the failure is in code that the PR's diff (`git diff origin/<base>...HEAD`) never touches, check for a stale base with `git merge-base --is-ancestor origin/<base> HEAD`. If the base is stale, update the branch and rerun the failing test before you change any code. Fix failures in the diff's own code. Reply and resolve thread IDs only when the user requested replies.

## Report

Give one row per comment: disposition and proof. Include holdouts, design questions, removed artifacts and the PR URL. Mark untested fixes unproven.

## Composes with

Use `fix-conflicts` for branch conflicts and `open-pr` when no PR exists.

Use the [evidence scale](../fresh-eyes/references/evidence-scale.md) when labeling worklog claims.
