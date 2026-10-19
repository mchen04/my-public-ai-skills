#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import random
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "fresh-eyes" / "scripts"))
import freshctx  # noqa: E402

DEFAULT_SKILLS = ROOT / "skills"
DEFAULT_CASES = ROOT / "evals" / "trigger-cases.tsv"
DEFAULT_TARGET = "claude:default"
TIMEOUT_S = 120


@dataclass(frozen=True)
class Target:
    runner: str
    model: str

    @classmethod
    def parse(cls, value: str) -> "Target":
        runner, separator, model = value.partition(":")
        if not separator or runner not in {"claude", "codex"} or not model:
            raise argparse.ArgumentTypeError(
                "target must be claude:MODEL or codex:MODEL"
            )
        return cls(runner, model)

    def __str__(self) -> str:
        return f"{self.runner}:{self.model}"


def load_descriptions(skill_dirs: list[Path], catalog_files: list[Path]) -> dict[str, str]:
    descriptions = {}
    for skills_dir in skill_dirs:
        for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
            parts = skill_md.read_text().split("---", 2)
            if len(parts) < 3:
                continue
            match = re.search(r"^description:\s*(.*)", parts[1], re.M | re.S)
            description = re.sub(
                r"\n\s+", " ", match.group(1) if match else ""
            ).strip().lstrip(">").strip()
            descriptions[skill_md.parent.name] = description
    for catalog_file in catalog_files:
        for line_number, line in enumerate(catalog_file.read_text().splitlines(), start=1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "\t" not in line:
                raise ValueError(f"{catalog_file}:{line_number}: expected name<TAB>description")
            name, description = line.split("\t", 1)
            descriptions[name.strip()] = description.strip()
    return descriptions


def load_cases(cases_path: Path) -> list[tuple[str, str]]:
    cases = []
    for line in cases_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "\t" not in line:
            continue
        expected, utterance = line.split("\t", 1)
        cases.append((expected.strip(), utterance.strip()))
    return cases


def build_prompt(catalog: str, utterance: str) -> str:
    return f"""You choose the primary skill for a user request from an evaluation catalog. A skill \
must be selected when its description matches the user's main goal, even if you could answer the \
request directly. Answer NONE only when no catalog description fits. Other skills could compose \
later, but return only the first primary route.

CATALOG
{catalog}

USER REQUEST
{utterance}

Return exactly one catalog skill name or NONE. Return no explanation."""


def command_for(target: Target, prompt: str, output_path: Path | None, effort: str | None = None) -> list[str]:
    if target.runner == "claude":
        return freshctx.claude_command(prompt, target.model, effort=effort, output="text")
    return freshctx.codex_command(prompt, target.model, effort=effort, output_path=output_path)


def normalize_answer(output: str) -> str | None:
    match = re.search(
        r"\b(?:none|[a-z0-9]+(?:[-:][a-z0-9]+)*)\b",
        output.lower(),
    )
    return match.group(0) if match else None


def query_model(target: Target, prompt: str, effort: str | None = None) -> tuple[str | None, str | None]:
    output_path: Path | None = None
    with tempfile.TemporaryDirectory(prefix="skill-route-eval-") as temp_dir:
        if target.runner == "codex":
            output_path = Path(temp_dir) / "last-message.txt"
        try:
            command = freshctx.resolve_command(command_for(target, prompt, output_path, effort))
        except FileNotFoundError as error:
            return None, str(error)
        result = freshctx.execute(command, None, TIMEOUT_S)

        if result["exit"] != 0:
            detail = (result["stderr"] or result["stdout"]).strip()[:300]
            return None, f"exit {result['exit']}: {detail}"

        output = result["stdout"]
        if output_path is not None and output_path.exists():
            output = output_path.read_text()
        answer = normalize_answer(output)
        if answer is None:
            return None, f"unparseable output: {output.strip()[:200]!r}"
        return answer, None


def classify(expected: str, got: str) -> tuple[str, bool]:
    allowed = {skill.strip().lower() for skill in expected.split("|")}
    if got in allowed:
        return "ok", True
    if allowed == {"none"}:
        return f"OVER-TRIGGER -> {got}", False
    if got == "none":
        return f"UNDER-TRIGGER (expected {expected})", False
    return f"MIS-ROUTE {expected} -> {got}", False


def evaluate_target(
    target: Target,
    cases: list[tuple[str, str]],
    catalog: str,
    jobs: int,
    trials: int,
    min_pass_rate: float,
    effort: str | None = None,
) -> tuple[int, int]:
    prompts = [(expected, utterance, build_prompt(catalog, utterance)) for expected, utterance in cases]
    results: list[list[tuple[str | None, str | None]]] = [
        [(None, "not run")] * trials for _ in prompts
    ]

    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as executor:
        futures = {
            executor.submit(query_model, target, prompt, effort): (index, trial)
            for index, (_, _, prompt) in enumerate(prompts)
            for trial in range(trials)
        }
        for future in concurrent.futures.as_completed(futures):
            index, trial = futures[future]
            results[index][trial] = future.result()

    correct = 0
    failures = 0
    print(f"\n[{target}]")
    for (expected, utterance, _), trial_results in zip(prompts, results):
        passed_trials = 0
        trial_notes = []
        for answer, error in trial_results:
            if error is not None or answer is None:
                trial_notes.append(f"MODEL-ERROR: {error}")
                continue
            verdict, passed = classify(expected, answer)
            passed_trials += int(passed)
            if not passed:
                trial_notes.append(verdict)
        pass_rate = passed_trials / trials
        if pass_rate >= min_pass_rate and not any(
            note.startswith("MODEL-ERROR") for note in trial_notes
        ):
            correct += 1
        else:
            failures += 1
            detail = "; ".join(trial_notes) or "below pass-rate threshold"
            print(
                f"  [{passed_trials}/{trials} pass; need {min_pass_rate:.0%}] "
                f"{utterance[:70]} :: {detail}"
            )

    print(f"  result: {correct}/{len(cases)} correct, {failures} fail")
    return correct, failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--target",
        action="append",
        type=Target.parse,
        help="RUNNER:MODEL; repeat for a model matrix (default: claude:default)",
    )
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--effort", choices=sorted(freshctx.CLAUDE_EFFORTS | freshctx.CODEX_EFFORTS),
                        help="override every target's requested effort; must be valid for all target runners")
    parser.add_argument("--all", action="store_true", help="run every case")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument("--min-pass-rate", type=float, default=1.0)
    parser.add_argument(
        "--skills-dir",
        type=Path,
        action="append",
        help="skill catalog root; repeat to include private or plugin catalogs",
    )
    parser.add_argument(
        "--catalog-file",
        type=Path,
        action="append",
        default=[],
        help="extra name<TAB>description catalog; repeatable",
    )
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    args = parser.parse_args()

    if args.jobs < 1:
        parser.error("--jobs must be at least 1")
    if args.trials < 1:
        parser.error("--trials must be at least 1")
    if not 0 < args.min_pass_rate <= 1:
        parser.error("--min-pass-rate must be in (0, 1]")
    targets = args.target or [Target.parse(DEFAULT_TARGET)]
    for target in targets:
        try:
            command_for(target, "", None, args.effort)
        except ValueError as error:
            parser.error(f"{target}: {error}")
    skill_dirs = args.skills_dir or [DEFAULT_SKILLS]
    try:
        descriptions = load_descriptions(skill_dirs, args.catalog_file)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    if not descriptions:
        parser.error("no skills found in the evaluation catalogs")
    catalog = "\n".join(
        f"- {name}: {description}" for name, description in sorted(descriptions.items())
    )
    cases = load_cases(args.cases)
    if not args.all:
        random.Random(args.seed).shuffle(cases)
        cases = cases[: args.limit]

    print(
        f"model trigger eval: {len(cases)} case(s), "
        f"{len(targets)} target(s), trials={args.trials}, jobs={args.jobs}"
    )
    total_failures = 0
    for target in targets:
        _, failures = evaluate_target(
            target,
            cases,
            catalog,
            args.jobs,
            args.trials,
            args.min_pass_rate,
            args.effort,
        )
        total_failures += failures
    return 1 if total_failures else 0


if __name__ == "__main__":
    sys.exit(main())
