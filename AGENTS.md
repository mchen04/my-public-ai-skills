# Maintaining this public collection

This repository is a manually maintained public copy of private engineering skills.
Publish only reusable instructions and portable helpers.
Keep the private source and its Git history outside this repository.

## Scope

- Keep personal workflows, account mappings, host routes, customer details, and internal incidents out.
- Write synthetic examples. Do not copy private prompts or real incident fixtures.
- Preserve third-party attribution and license notices.
- Keep credential, permission, and publication boundaries when adapting skills.
- Preserve the user's existing files and running sessions.
- Keep logs, review transcripts, recordings, and scratch files outside the repository.
- Make changes in a review branch. Publish only when the user authorizes it.

## Checks

Run `bash scripts/check.sh` before every commit.
Prove new checks reject a representative failure before accepting a passing result.
Update the README catalog and trigger cases when changing the skill set.
Run an authorized model routing evaluation when changing routing descriptions.
Before pushing public content, review the complete outgoing history for private material.
Use a fresh independent reviewer before merging a public update.
Resolve every material finding and rerun affected checks before publication.
