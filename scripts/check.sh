#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
export PYTHONDONTWRITEBYTECODE=1
PY="${PYTHON:-python3}"
"$PY" scripts/check-public.py --selftest
"$PY" scripts/check-public.py
"$PY" scripts/eval-triggers.py
for skill in skills/*; do
  "$PY" skills/skill-maintenance/scripts/skillcheck.py "$skill"
done
"$PY" - <<'PY'
from pathlib import Path
for folder in ("skills", "scripts", "evals"):
    for path in Path(folder).rglob("*.py"):
        compile(path.read_text(), str(path), "exec")
print("python_syntax_ok")
PY
while IFS= read -r script; do bash -n "$script"; done < <(find skills scripts evals -name '*.sh' -type f)
for helper in loopctl flowctl runctl; do
  "$PY" "skills/loop/scripts/$helper.py" selftest
done
"$PY" skills/skill-maintenance/scripts/blindeval.py selftest
for test in evals/*-test.py; do
  "$PY" "$test"
done
for test in evals/*-test.sh; do
  bash "$test"
done
git diff --check
echo "check_ok"
