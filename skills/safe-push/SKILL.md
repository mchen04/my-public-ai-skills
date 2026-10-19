---
name: safe-push
description: >
  Safely commit and push a branch, handling account switches, rebases, and 403s. Use for "commit and
  push", "push this branch", or existing-PR pushes. Not for opening a PR, merging, or releasing.
---
# Safe Push

Commit/push the authorized branch; leave opening PRs to `open-pr` and merging is the user's call.

## Process

1. Run EXECUTED `scripts/redact-secrets.py check-working-tree` before committing. Exit 2 names candidate file/line/kind. Never print, commit, or paste a secret value yourself. Redact with `redact-secrets.py redact -- <exact-paths>`, check the diff, and rerun the project checks. Keep real credential files such as `.env` out of git and commit a redacted example. Also run the repository's own scanner if it has one. Commit only this task's paths, and leave paths that were already dirty. [Secrets](references/secrets.md) covers synthetic fixtures.
2. Resolve owner/repo from origin. Read `~/.config/git-push-accounts.json`: exact `repos`, then `owners`, optional pinned `base`. The [mapping format](references/accounts.md) has synthetic examples. Without a match, probe `gh api repos/<owner>/<repo> -q .permissions.push` for logged-in accounts and record the working mapping. A private-repository 404 may mean the wrong account. If none can push, report the missing login/invite.
3. Run each remote Git/gh operation through EXECUTED `scripts/with_account.py --user <account> -- <command>`. It switches under a lock shared by wrapper callers and restores the previous account on every exit path. Never leave the active account changed. Inside that wrapper, use only gh credentials:

   ```bash
   git -c credential.helper= -c 'credential.helper=!gh auth git-credential' fetch origin
   ```

   Use the same options for push/pull; keychain helpers may supply a different account.
4. If the remote branch has unseen commits, pull --rebase. Rebase an open PR onto a newer base only for conflicts, required freshness or user direction. Resolve through `fix-conflicts`, then rerun checks.
5. Run `redact-secrets.py check-range 'origin/<ref>..HEAD'`: existing branch unless rewritten, otherwise base. On a finding, do not push: redact and rewrite the local-only commits, because a later redaction commit still leaks the secret. A secret already on the remote must be revoked; tell the user.
6. First push: `git push -u origin <branch>`. Rewritten branch: `--force-with-lease`; never bare --force. Never push directly to a protected or default branch.

## Composes with

Use `fix-conflicts` for conflicts; continue to `open-pr` only when authorized. Report push result, PR and any redaction by path/kind.
