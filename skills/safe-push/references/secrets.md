# Secret scan edge cases

`redact-secrets.py` (EXECUTED) is a high-confidence gate. It finds credential URLs, literal
secret assignments, provider tokens, JWTs, and private keys.

## What it ignores, and why

It ignores hyphenated UI tokens such as browser autocomplete values, generic literals of one to
three characters, and equal user and password defaults in loopback-only database URLs. Remote
credential URLs and config-file assignments stay strict. A fix for a false positive keeps every
positive detection test.

## Working-tree findings

The scanner does not stage files. Preserve partial staging, and stage only the paths or hunks the
user intended. Commit only after the scan is clean or every remaining candidate is a verified
synthetic fixture.

## Synthetic fixtures

Whole-file scans can flag test credentials that were already there. Check each candidate against
the published base and its use in a local fake or isolated test fixture. A confirmed synthetic
fixture is not a leak: do not rewrite unrelated tests or redact working fixtures. Record these
reviewed false positives separately. The same exception covers a new synthetic fixture created
and used only inside an isolated local or test service.

For outgoing history, review every reported commit, path, and line, and record why the value
cannot authenticate to a real service. A finding stays open until that evidence exists. Never
exempt a value because its path contains `test` or because it is already on the remote.

## Outgoing range

The range scan checks additions in every unpublished commit, so a value that already existed
elsewhere in a touched file is not a new leak. After a rebase onto `origin/<base>`, and for a
first push, the range is `origin/<base>..HEAD`, because base commits are already published. After
a redaction and rewrite, rerun both scans until they are clean or every remaining finding meets
the fixture exception.
