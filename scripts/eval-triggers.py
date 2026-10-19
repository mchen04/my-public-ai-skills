#!/usr/bin/env python3
from __future__ import annotations
import argparse
from collections import Counter
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def validate(skills: Path, cases: Path, minimum: int = 3) -> tuple[list[str], Counter]:
    names = {p.parent.name for p in skills.glob('*/SKILL.md')}
    counts = Counter()
    errors = []
    seen = set()
    if not names:
        errors.append('skill catalog is empty')
    for number, line in enumerate(cases.read_text().splitlines(), 1):
        if not line.strip() or line.startswith('#'):
            continue
        expected, separator, task = line.partition('\t')
        allowed = expected.split('|')
        if not separator or not task.strip() or any(x not in names | {'none'} for x in allowed):
            errors.append(f'{cases}:{number}: require known skill(s), TAB, and a request')
            continue
        if task in seen:
            errors.append(f'{cases}:{number}: duplicate request')
        seen.add(task)
        counts.update(name for name in allowed if name != 'none')
    errors += [f'{name}: fewer than {minimum} positive cases' for name in sorted(names) if counts[name] < minimum]
    return errors, counts


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate routing cases and catalog coverage. eval-triggers-model.py tests real selection.")
    parser.add_argument('--skills-dir', type=Path, default=ROOT / 'skills')
    parser.add_argument('--cases', type=Path, default=ROOT / 'evals/trigger-cases.tsv')
    parser.add_argument('--min-positive-cases', type=int, default=3)
    args = parser.parse_args()
    errors, counts = validate(args.skills_dir, args.cases, args.min_positive_cases)
    if errors:
        print('\n'.join(errors), file=sys.stderr)
        return 1
    print(f'trigger_cases_ok ({len(counts)} skills covered; model routing requires eval-triggers-model.py)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
