# Local GitHub account mapping

Keep this file at `~/.config/git-push-accounts.json`, outside Git repositories.
The agent reads it when choosing an account and pull request base.
The wrapper receives the selected account through `--user`; it does not parse this file.

```json
{
  "owners": {
    "example-team": {"account": "example-dev", "base": "main"}
  },
  "repos": {
    "example-team/widget": {"account": "example-release", "base": "integration"}
  }
}
```

All names above are synthetic. Replace them with your own logged-in GitHub accounts.
An exact repository entry takes precedence over its owner entry.
The optional `base` selects a pull request target; it does not grant push access.
Without a pinned base, use the requested base or the repository's default branch.
Check access through GitHub before pushing. A mapping is not evidence of permission.
