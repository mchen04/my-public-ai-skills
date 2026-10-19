---
name: correct
description: >
  Stop coding agents from repeating a mistake in an app repo by making it impossible: architecture first, then types, then a lint whose error names the fix, then a test, docs last. Use for "agents keep doing X", "coders keep making the same mistake", or "make this mistake impossible". Not for one bug (fix-bug), skill-library lessons (skill-maintenance), or a principle named by the user (principles).
---
# Correct

Change the repo so that the next coder cannot repeat the mistake. You are done when each repeated mistake class has an enforcer that fails on a real past instance and passes on the fixed tree, and the repo's agent instructions list that enforcer.

Assume that every contributor is a coder agent, such as Claude Code, Codex or Hermes. It sees only the files it opened, copies the nearest example, and takes the shortest path that passes. Design the repo so that a change that looks right in one file is right for the whole repo.

## Find the classes

Read the recent commits and reverts, the PR review comments, the agent instruction files, and the comments that explain workarounds. Group the mistakes into classes. A class counts once it has happened twice, or once after an explicit user correction. A rule that the instructions already state and coders still break is a repeat. Enforce it in this change.

## Fix each class at the highest level that works

1. Architecture makes the mistake impossible. Give each piece of state one owner and each task one supported way. Hide internals so that a wrong import fails. Replace hand-synced lists with one source of truth. Delete the old paths and dead code that an agent would copy.
2. Types make the bad state impossible to write.
3. A lint or check catches bad code that still compiles. Its error names the file, function or command to use instead. When the pattern is already common, fail only on changes that add more of it.
4. A test checks the behavior. [prune-tests](../prune-tests/SKILL.md) owns tests that cannot fail.
5. Docs or agent rules come last, and only for judgment calls, because nothing fails when a coder skips them.

Do not stop to ask which level to use. Choose one, and report why each higher level did not work.

## Prove and wire

Fix the most frequent classes now, with one commit per class. Run each new enforcer against a real past instance, such as an old commit or a replayed copy of its diff, and see it fail. Then see it pass on the fixed tree and on the [legitimate inputs](../principles/references/encode-lessons-in-structure.md) that must keep passing. A check that never failed on a real instance does not count. Run it from the command that coders already run before they commit, and run the same command in CI. An exception goes on the offending line, with a reason and an expiry date.

## Keep the rule table

Keep a table in the repo's AGENTS.md that pairs each rule with its enforcer. When an enforcer exists, delete the prose rule and keep only its table row. When the user corrects a coder, fix the mistake and add the row in the same change.

## Report

For each class, give the evidence, the level you chose, why no higher level worked, and the failing and passing runs.

Adapted from the `correct` skill in [pstack](https://github.com/cursor/plugins/tree/main/pstack).
