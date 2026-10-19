#!/usr/bin/env bash
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SWEEP="$ROOT/skills/fix-conflicts/scripts/sweep-markers.sh"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
cd "$T" && git init -q repo && cd repo
g() { git -c user.name=t -c user.email=t@t "$@"; }
printf 'value = 1\n' > app.txt
g add -A && g commit -qm base && git branch -q side
printf 'value = 2\n' > app.txt && g commit -qam ours
git checkout -q side && printf 'value = 3\n' > app.txt && g commit -qam theirs
git checkout -q - 2>/dev/null || git checkout -q master 2>/dev/null || git checkout -q main
g merge -q side >/dev/null 2>&1
conflicted=$(git diff --name-only --diff-filter=U)
[ "$conflicted" = "app.txt" ] || { echo "fix-conflicts-sweep FAIL: setup produced no conflict"; exit 1; }
g add app.txt && g commit -qm "merge with markers left in"
bash "$SWEEP" $conflicted >/dev/null && { echo "fix-conflicts-sweep FAIL: committed markers passed"; exit 1; }
bash "$SWEEP" >/dev/null 2>&1; [ $? -eq 2 ] || { echo "fix-conflicts-sweep FAIL: no files must be a usage error"; exit 1; }
printf 'value = 3\n' > app.txt && g commit -qam "resolve properly"
bash "$SWEEP" app.txt >/dev/null || { echo "fix-conflicts-sweep FAIL: a clean resolution failed"; exit 1; }
echo "fix_conflicts_sweep_ok (committed markers caught, clean resolution passes)"
