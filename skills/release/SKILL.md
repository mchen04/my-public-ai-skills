---
name: release
description: >
  Run the repo release path: version, changelog, checks, tag, and publication. Use for cutting a release or publishing a package. Not for branch pushes alone (safe-push).
---
# Release

Discover its publish path and drive it; never invent one. Finish with published version/artifacts read back from their destination.

## Process

1. Read release scripts, workflows, version files and releasing docs. Ask only when the publish path remains unknown.
2. Apply the existing version scheme everywhere and derive changelog/docs updates from commits since the last tag.
3. Use [open-pr's artifact sweep](../open-pr/SKILL.md#process). Never delete tracked files meant to ship or files you did not create.
4. Run build/tests and [safe-push scans](../safe-push/SKILL.md#process), range <last-tag>..HEAD. Also run the repository scanner and scan built artifacts before upload. Anything that needs an interactive credential (notarization, registry tokens) is a blocker: name the exact command.
5. Show version, destination and tag. Publishing is irreversible, so it needs explicit authorization for this release; an existing authorization for this exact release counts, and a matching plan needs no second ask. --dry-run stops after the plan. Execute only the discovered publish/tag path.
6. Read back registry/release/tag output; match version, names and hashes to built artifacts. Report unconfirmed surfaces explicitly.

## Composes with

Use `safe-push` for branch/tag publication. Report version changes, checks, destination/readback, URL and blockers.
