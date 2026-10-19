# Autonomous run record

EXECUTED `scripts/runctl.py` keeps sidecar state outside repositories. Use `--help` for commands. Start with `init --repo . --run <id>`, then freeze selected workflow steps before edits with `steps freeze --repo . --run <id> --skill <folder>`. Required steps need evidence-backed done or reason/consequence-backed skipped status; run `steps gate` and `validate` before reporting completion.

Record decisions and superseding decisions, not overwritten history. `check --repo . --run <id> -- <command>` produces revision-bound receipts; cite `run:receipts/<id>.json`. `scripts/ledgerio.py` owns locks, atomic writes and receipt validation. A receipt binds recorded output to a revision and detects accidental edits.
It is not an authenticated execution attestation; someone with write access can forge it.
It does not establish whether the observer is relevant.

Never write a secret or private content into the record. It stays local; only `export --into <dir> --i-own-this-repo` puts it in a repository. If a first commit changes project identity, link the new project-key directory to the existing sidecar and validate; do not start a duplicate record.
