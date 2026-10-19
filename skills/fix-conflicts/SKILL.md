---
name: fix-conflicts
description: >
  Resolve git merge or rebase conflicts non-interactively, validate, and finish the operation. Use
  for "fix merge conflicts", "resolve conflicts", or "the rebase is conflicted".
---
# Fix Conflicts

Resolve the conflicts, prove the result builds and passes its checks, and finish the merge or
rebase. Done means `git status` shows a clean, non-conflicted tree and no conflict markers remain.

## Workflow

1. **List the conflicts.** `git status` shows whether this is a merge or a rebase and which step.
   `git diff --name-only --diff-filter=U` lists unresolved files; keep that list and add each
   rebase step's files. Delete-vs-edit conflicts ("deleted by us/them") carry no markers, so read
   `git status` for them too.
2. **Read both sides' intent** before choosing: `git log --oneline -3 HEAD -- <file>`, and the
   same for `MERGE_HEAD` or `REBASE_HEAD`. During a rebase, "ours" is the upstream base and
   "theirs" is your commit being replayed.
3. **Resolve with the smallest correct edit.** Keep both sides when they do not overlap (imports,
   adjacent edits). Otherwise keep the variant that builds and keeps public behavior stable. For
   delete-vs-edit, keep the file only if its edits still matter after the other side's
   restructure; trace where the deleted code's job moved.
4. **Semantic conflicts** (both sides changed the same behavior: logic, money or scoring rules, API
   contracts) follow the user's requested behavior and repository evidence. Ask only when two
   incompatible product choices remain; never invent a blend.
5. **Regenerate a conflicted lockfile** with its package manager (`npm install`,
   `cargo update -p <pkg>`), never by hand.
6. **Check.** Run compile, lint, and the relevant tests. If you skip one, say why.
7. **Finish without an editor.** Stage the resolved files, then run `GIT_EDITOR=true git rebase
   --continue` once per conflicted commit, or `git commit --no-edit` for a merge. If `git rerere`
   is on, re-verify the build, because a recorded resolution can be stale.
8. **Sweep for markers** in every listed file: `bash <skill-dir>/scripts/sweep-markers.sh <files>`
   (EXECUTED). It reads both the working tree and the finished commit, and exits 1 on a marker.

Keep the change minimal: no refactors while resolving. Do not push or tag; `safe-push` owns that.

## Report

Give the final state first: completed, or stopped for a user decision. Then list each resolved
file and how (ours, theirs, both, blend), notable choices such as delete-vs-edit, and the check
results.


## Composes with

Return the resolved branch and check results to the workflow that requested conflict resolution.
