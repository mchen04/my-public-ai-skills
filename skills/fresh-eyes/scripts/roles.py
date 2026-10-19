#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROLES_FILE = Path(__file__).resolve().parents[1] / "assets" / "roles.json"
FIELDS = ("family", "model", "effort")


def load(path: Path = ROLES_FILE) -> dict[str, dict]:
    roles = json.loads(path.read_text(encoding="utf-8"))["roles"]
    for name, spec in roles.items():
        missing = [key for key in FIELDS if not spec.get(key)]
        if missing:
            raise ValueError(f"{path}: role {name!r} lacks {', '.join(missing)}")
    return roles


def role(name: str, path: Path = ROLES_FILE) -> dict:
    roles = load(path)
    if name not in roles:
        raise KeyError(f"unknown role {name!r}; known: {', '.join(sorted(roles))}")
    return roles[name]


def main(argv: list[str]) -> int:
    try:
        data = role(argv[0]) if argv else load()
    except (KeyError, ValueError) as error:
        print(error, file=sys.stderr)
        return 2
    print(json.dumps(data, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
