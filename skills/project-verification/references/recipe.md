# Recipe and feature map

Read this when you write or repair `recipe.json` or `features.md`. `verifyctl.py check` validates
required fields, placeholders, map IDs, and drift. User-facing coverage needs a driven run.

## recipe.json

```json
{
  "format": 1,
  "app": "notes",
  "surface": "http",
  "harnesses": [{"kind": "make", "command": ["make", "run"], "source": "Makefile"}],
  "isolation": {"port_env": "PORT", "data_dir_env": "DATA_DIR"},
  "launch": {"command": ["python3", "app.py"],
             "ready": {"command": ["curl", "-sf", "http://127.0.0.1:{port}/health"], "timeout_s": 30}},
  "doctor": {"command": ["curl", "-sf", "http://127.0.0.1:{port}/health"]},
  "teardown": null,
  "features": [
    {"id": "notes.create", "title": "Create a note", "sources": ["app.py", "templates/new.html"],
     "requires": ["cmd:curl"],
     "steps": [{"name": "post", "run": ["curl", "-s", "-d", "title=milk", "http://127.0.0.1:{port}/notes"],
                "expect": {"exit": 0, "stdout_contains": "created milk"}}]}
  ],
  "history": []
}
```

- `launch` is `null` for a CLI or library with no long-lived process; steps then run the tool.
  Otherwise `ready` must pass before any step runs, and `doctor` is a read-only health check.
  Before you probe a candidate CLI, read its startup path and point its application-home setting
  at synthetic state, because even `config get` can run migrations before command dispatch.
  Confirm that production settings are unchanged after the run.
- Placeholders expand in every command: `{port}`, `{data_dir}`, `{evidence}`, `{run_id}`. Each
  feature gets a fresh instance with its own port and data folder outside the project. Set
  `"per_feature": false` under `isolation` only when startup is too slow and features never share
  state.
- `env` (optional) adds fixed variables to every command, such as `PYTHONDONTWRITEBYTECODE=1`
  when a step would otherwise write caches into the project.
- `teardown` is optional: `{"command": [...], "gone": {"command": [...], "timeout_s": 15}}`. The
  runner always stops the process group it started and nothing else, then runs `command` and polls
  `gone` until it exits 0. Use `gone` for tools that finish closing after their close command
  returns, such as a browser session. The report says `cleanup_confirmed`.
- `expect` takes `exit`, `stdout_contains` (text or list), `stdout_regex`, and `stdout_absent`.
  Assert on what the user would observe, never on internal setters or test-only endpoints.
- `sources` are globs relative to the project. `accept` records their digest and the steps'
  digest; any later change shows as drift until a passing run is accepted again.
- `requires` names preconditions: `env:NAME` or `cmd:NAME`. Unmet means `blocked`.
- `accepted` and `history` are written by `accept`; do not edit them by hand.
- The format number is checked. A recipe in another format is refused, not migrated.

## features.md

One section per recipe feature, in this form, with the same IDs:

```markdown
## notes.create — Create a note
What the user does and sees. Every entry point (button, shortcut, CLI command).
Preconditions, and the observable end state that proves it worked.
```

Keep implementation details out of the map; name user paths, stable handles, required state,
and the proof. A path you did not drive is not verified through another one.

## Evidence

Each run writes `report.json`, an instance log, and one receipt per step under
`~/.cache/project-verification/<project>/<run-id>/`. Receipts carry the exit code, output hashes,
and the worktree revision. `accept` refuses an edited, missing, or stale receipt. A step that
changes the worktree fails as a harness problem: keep instance data outside the project.

Set `PROJECT_VERIFICATION_CACHE` to change the cache root for reports, locks, and test-selection logs.
Keep this directory outside the project. Tests use a temporary cache.

## Browser runner setup

On a shared machine, install Playwright engines with `PLAYWRIGHT_SKIP_BROWSER_GC=1` and call the
project's installed CLI, not an `npx` lookup.

Generated JavaScript test suggestions use `npx --no-install` and require installed project dependencies.
Inspect suggestions before running them. Browser recipe commands still use the project's installed CLI directly.
