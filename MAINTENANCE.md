# Maintaining the public copy

The internal Hermes collection evolves independently. Public updates are manual.

1. Select a reusable engineering lesson or helper.
2. Adapt it in a review branch of this repository.
3. Replace private examples with synthetic cases and remove machine or account assumptions.
4. Keep existing permission and credential boundaries.
5. Update the skill catalog, routing cases, dependency notes, and third-party notices when needed.
6. Run `bash scripts/check.sh` and the affected behavior checks.
7. Run an authorized model routing evaluation when a routing description changes.
8. Review every outgoing commit, not only the latest file versions.
9. Obtain a fresh independent review of the complete public bundle before pushing new content.
10. Resolve material findings, repeat affected checks, and review the revised content.
11. Push the checked branch, open a pull request, wait for required checks, and squash-merge when authorized.
12. Read the published files back from GitHub and confirm the repository remains public.

Never merge, fetch into this repository, or copy `.git` from the private source.
Do not commit exports, logs, reviewer transcripts, screenshots, personal settings, or real incident fixtures.
A deletion in the latest commit does not remove earlier copies from public Git history.

Run the bundled credential scanner before committing and before pushing:

```sh
python3 skills/safe-push/scripts/redact-secrets.py check-working-tree
python3 skills/safe-push/scripts/redact-secrets.py check-range origin/main..HEAD
```

The second command scans each outgoing commit on an existing public base.
For a new repository, scan the whole proposed history with `check-range HEAD` before its first push.
Synthetic test findings need a documented review under the [scanner rules](skills/safe-push/references/secrets.md).
Automated scans do not replace human review of private context or publishing rights.
