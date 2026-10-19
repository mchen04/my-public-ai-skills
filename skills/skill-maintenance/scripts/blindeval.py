#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import copy
import contextlib
import io
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "fresh-eyes" / "scripts"))
sys.path.insert(0, str(HERE.parents[1] / "loop" / "scripts"))
try:
    import freshctx
except ImportError:  # pragma: no cover
    freshctx = None
try:
    import runctl
except ImportError as error:
    print(f"blindeval: install the sibling loop and safe-push skills: {error}", file=sys.stderr)
    raise SystemExit(2)


BANNED = (
    "eval", "evaluat", "rubric", "grader", "judge", "experiment", "benchmark", "candidate",
    "arena", "fixture", "being tested", "hidden answer", "expected answer",
)
MIN_LEAK_LINE = 8
MAX_LINT_BYTES = 1_000_000
CHECK_RE = re.compile(
    r"^(final|command|reads|writes)\s+(~|!~)\s+(.+)$|^file\s+(exists|missing)\s+(.+)$|^file\s+~\s+(\S+)\s+(.+)$|^tree\s+clean\s+(.+)$"
)


class Leak(Exception):
    pass


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def section(text: str, title: str) -> str:
    match = re.search(rf"^##\s+{re.escape(title)}\s*$(.*?)(?=^##\s|\Z)", text, re.S | re.M)
    return match.group(1).strip() if match else ""


def load_fixture(fixture: Path) -> dict:
    task = read(fixture / "task.md").strip()
    if not task:
        raise SystemExit(f"{fixture}: task.md is missing or empty")
    rubric = read(fixture / "rubric.md")
    checks = [line.strip() for line in section(rubric, "Checks").splitlines() if line.strip() and not line.strip().startswith("#")]
    checks = [c[2:] if c.startswith("- ") else c for c in checks]
    bar = section(rubric, "Bar")
    min_checks = int(m.group(1)) if (m := re.search(r"min-checks:\s*(\d+)", bar)) else len(checks)
    min_score = float(m.group(1)) if (m := re.search(r"min-score:\s*(\d+(?:\.\d+)?)", bar)) else None
    judge = section(rubric, "Judge")
    if judge and not checks and min_score is None:
        raise SystemExit(f"{fixture}: a judge-only rubric needs `min-score: N` under ## Bar, or the evaluator's score would gate nothing")
    for check in checks:
        if not CHECK_RE.match(check):
            raise SystemExit(f"{fixture}: unreadable check line {check!r}")
    return {
        "name": fixture.name,
        "task": task,
        "expected": read(fixture / "expected.md"),
        "checks": checks,
        "judge": judge,
        "min_checks": min_checks,
        "min_score": min_score,
        "setup": fixture / "setup",
        "setup_script": fixture / "setup.sh",
    }


def leak_probes(expected: str) -> list[str]:
    probes = []
    for line in expected.splitlines():
        line = line.strip().lstrip("-* ").strip()
        if line.startswith("#") or len(line) < MIN_LEAK_LINE:
            continue
        probes.append(line)
    return probes


def assert_blind(text: str, forbidden: list[str], probes: list[str], where: str, vocabulary: bool = True) -> None:
    low = text.lower()
    if vocabulary:
        for word in BANNED:
            if re.search(rf"(?<![a-z]){re.escape(word)}", low):
                raise Leak(f"{where} contains evaluation vocabulary {word!r}")
    for token in forbidden:
        if token and re.search(rf"(?<![a-z0-9]){re.escape(token.lower())}(?![a-z0-9])", low):
            raise Leak(f"{where} contains the forbidden token {token!r}")
    for probe in probes:
        if probe.lower() in low:
            raise Leak(f"{where} contains a line of the hidden expected answer: {probe[:60]!r}")


def assert_unmapped(text: str, ids: list[str], labels: list[str], paths: list[str], where: str) -> None:
    low = text.lower()
    for path in paths:
        if path and path.lower() in low:
            raise Leak(f"{where} contains a candidate path {path!r}")
    for wid in ids:
        for label in labels:
            pattern = rf"{re.escape(wid)}\s*[:=(\-–—]\s*{re.escape(label.lower())}(?![a-z0-9])|(?<![a-z0-9]){re.escape(label.lower())}\s*[:=(\-–—]\s*{re.escape(wid)}"
            if re.search(pattern, low):
                raise Leak(f"{where} maps {wid} to the label {label!r}")


def lint_fixture(fx: dict, labels: list[str]) -> list[str]:
    problems = []
    probes = leak_probes(fx["expected"])
    try:
        assert_blind(fx["task"], [fx["name"]], probes, "task.md")
    except Leak as leak:
        problems.append(str(leak))
    if fx["setup"].is_dir():
        for path in sorted(fx["setup"].rglob("*")):
            rel = str(path.relative_to(fx["setup"]))
            if path.is_symlink():
                problems.append(f"setup path {rel} is a symlink; a fixture ships regular files only, never a pointer to a host file")
                continue
            try:
                assert_blind(rel, [fx["name"], *labels], [], f"setup path {rel}")
            except Leak as leak:
                problems.append(str(leak))
            if path.is_file() and path.stat().st_size > MAX_LINT_BYTES:
                problems.append(f"setup file {rel} is larger than the {MAX_LINT_BYTES} bytes lint can read; a fixture ships small material")
                continue
            if path.is_file():
                try:
                    content = path.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    continue
                try:
                    assert_blind(content, [], probes, f"setup file {rel}")
                except Leak as leak:
                    problems.append(str(leak))
    if fx["setup_script"].is_file():
        script = read(fx["setup_script"])
        try:
            assert_blind(script, [fx["name"], *labels], probes, "setup.sh")
        except Leak as leak:
            problems.append(str(leak))
        if re.search(r"expected\.md|rubric\.md|\.\./|expec\*|rubr\*|\$0|dirname", script) or str(fx["setup_script"].parent) in script:
            problems.append("setup.sh reaches for the fixture's hidden files, its own location, or its parent directory")
    if not fx["checks"] and not fx["judge"]:
        problems.append("rubric.md has neither `## Checks` nor `## Judge`; nothing would be graded")
    return problems


def hidden_id() -> str:
    return "w-" + secrets.token_hex(2)


def rubric_digest(fx: dict) -> str:
    import hashlib
    return hashlib.sha256((fx["task"] + "\n".join(fx["checks"]) + fx["judge"] + fx["expected"]).encode()).hexdigest()[:16]


def worker_prompt(task: str, skill_name: str | None, skill_text: str | None) -> str:
    parts = []
    if skill_name and skill_text:
        parts.append(
            f"Instructions loaded for this task, from .skills/{skill_name}/SKILL.md (relative paths in"
            f" them resolve against that folder). Follow them.\n\n{skill_text.strip()}\n"
        )
    parts.append(task.strip())
    parts.append("\nWork in the current directory. Return a concise final answer.")
    return "\n".join(parts)


def judge_prompt(fx: dict, recordings: dict[str, dict]) -> str:
    parts = [
        "You are grading recordings of independent attempts at one task. Score each recording",
        "on the rubric below, 0-10, strictly from what the recording shows. You do not know who",
        "or what produced each recording, and you must not guess.",
        "",
        "TASK GIVEN TO EVERY ATTEMPT",
        fx["task"].strip(),
        "",
        "RUBRIC",
        fx["judge"].strip(),
        "",
        "WHAT A GOOD ANSWER CONTAINS",
        fx["expected"].strip() or "(not supplied)",
        "",
    ]
    setup = fx.get("setup")
    if isinstance(setup, Path) and setup.is_dir():
        parts.append("INPUT FILES SUPPLIED WITH THE TASK (bounded snapshots):")
        parts.append(json.dumps(sanitize(collect_file_evidence(["file exists **/*"], setup), setup), ensure_ascii=False))
    for wid in sorted(recordings):
        rec = recordings[wid]
        parts.append(f"RECORDING {wid}")
        parts.append("commands run:")
        command_calls = [call for call in rec.get("tool_calls", []) if call.get("tool") == "Bash"]
        for index, command in enumerate(rec.get("commands", [])[:40]):
            call = command_calls[index] if index < len(command_calls) else {}
            exit_code = call.get("exit_code") if call.get("input", {}).get("command") == command else None
            shown = command if len(command) <= 4000 else command[:4000] + " [TRUNCATED]"
            parts.append(f"  $ {shown}\n    exit: {exit_code if exit_code is not None else 'not recorded'}")
        if len(rec.get("commands", [])) > 40:
            parts.append("  [additional commands omitted; execution evidence is incomplete]")
        parts.append("files written: " + ", ".join(str(w)[:120] for w in rec.get("writes", [])[:20]))
        parts.append("mechanical checks observed by the harness (not worker claims):")
        parts.extend(f"  {'PASS' if ok else 'FAIL'}: {check}" for ok, check in rec.get("checks", []))
        parts.append("Observed output files (bounded snapshots):")
        parts.append(json.dumps(rec.get("file_evidence", {}), ensure_ascii=False))
        parts.append("final answer:")
        parts.append((rec.get("final") or "(none)")[:6000])
        parts.append("")
    parts.append("Explain any deductions with a concrete recording detail and the rubric requirement it violates. "
                 "Do not deduct for stylistic preferences outside the rubric. "
                 "Then return one line per recording, exactly `SCORE <id>: <n>`, and nothing else after them.")
    return "\n".join(parts)


def parse_scores(text: str) -> dict[str, float]:
    scores = {}
    for match in re.finditer(r"SCORE\s+(w-[0-9a-f]{4})\s*:\s*(\d+(?:\.\d+)?)", text):
        scores[match.group(1)] = float(match.group(2))
    return scores


def run_check(check: str, rec: dict, workdir: Path) -> tuple[bool, str]:
    m = CHECK_RE.match(check)
    assert m
    if m.group(1):
        field, op, pattern = m.group(1), m.group(2), m.group(3)
        haystacks = {
            "final": [rec.get("final") or ""],
            "command": rec.get("commands", []),
            "reads": rec.get("reads", []),
            "writes": [str(w) for w in rec.get("writes", [])],
        }[field]
        hit = any(re.search(pattern, h, re.I | re.S) for h in haystacks)
        return (hit if op == "~" else not hit), check
    if m.group(4):
        matches = list(workdir.glob(m.group(5)))
        return (bool(matches) if m.group(4) == "exists" else not matches), check
    if m.group(6):
        body = read(workdir / m.group(6))
        return bool(re.search(m.group(7), body, re.I | re.S)), check
    target = workdir / m.group(8)
    try:
        out = subprocess.run(["git", "-C", str(target), "status", "--porcelain"], capture_output=True, text=True, timeout=30)
        clean = out.returncode == 0 and not out.stdout.strip()
        detail = "" if clean else f" (changed: {out.stdout.strip()[:200] or out.stderr.strip()[:200]})"
    except (OSError, subprocess.SubprocessError) as error:
        clean, detail = False, f" ({error})"
    return clean, check + detail


def fake_run(script: str, prompt: str, cwd: Path, env: dict) -> dict:
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, prefix="prompt-") as fh:
        fh.write(prompt)
        prompt_path = fh.name
    try:
        out = subprocess.run([script, str(cwd)], capture_output=True, text=True, timeout=120, env={**env, "BLINDEVAL_PROMPT_FILE": prompt_path}, cwd=str(cwd))
    finally:
        os.unlink(prompt_path)
    if out.returncode != 0:
        return {"final": "", "commands": [], "reads": [], "writes": [], "exit": out.returncode, "error": out.stderr[-300:]}
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError:
        return {"final": out.stdout, "commands": [], "reads": [], "writes": [], "exit": 0, "error": ""}


def sanitize(rec: dict, workdir: Path) -> dict:
    def clean(value):
        if isinstance(value, str):
            return runctl.redact(value).replace(str(workdir.resolve()), "<work>").replace(str(workdir), "<work>")
        if isinstance(value, list):
            return [clean(v) for v in value]
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items()}
        return value
    return clean(rec)


def collect_file_evidence(checks: list[str], workdir: Path, writes: list[str] | None = None) -> dict[str, str]:
    evidence = {}
    budget = 32000
    paths = []
    for check in checks:
        match = CHECK_RE.match(check)
        pattern = match.group(5) or match.group(6)
        if pattern:
            paths.extend(sorted(workdir.glob(pattern)))
    for written in writes or []:
        if isinstance(written, str):
            relative = re.sub(r"^(?:/private)?<work>/", "", written)
            paths.append(workdir / relative)
    for path in paths:
        if path.is_symlink() or not path.is_file():
            continue
        try:
            relative = str(path.resolve().relative_to(workdir.resolve()))
            if relative.startswith(".skills/"):
                continue
            if relative in evidence:
                continue
            if budget <= 0:
                evidence["[omitted]"] = "file evidence budget exhausted"
                return evidence
            with path.open(encoding="utf-8") as source:
                body = source.read(min(8000, budget) + 1)
            limit = min(8000, budget)
            evidence[relative] = body[:limit] + ("\n[truncated]" if len(body) > limit else "")
            budget -= min(len(body), limit)
        except (OSError, UnicodeError, ValueError):
            continue
    return evidence


def run_worker(runner: str, family: str, prompt: str, cwd: Path, env: dict, effort: str, timeout: int, model: str = "default",
               allow_unsandboxed_claude: bool = False) -> dict:
    if runner.startswith("fake:"):
        return fake_run(runner[5:], prompt, cwd, env)
    if freshctx is None:
        raise SystemExit("freshctx.py (the fresh-eyes skill) must be installed beside skill-maintenance")
    return freshctx.run_worker(family, prompt, cwd, "work", model, effort, timeout, env, allow_unsandboxed_claude)


def run_judge(runner: str, family: str, prompt: str, timeout: int, model: str = "default", effort: str | None = None) -> str:
    if runner.startswith("fake:"):
        out = subprocess.run([runner[5:]], input=prompt, capture_output=True, text=True, timeout=120)
        return out.stdout
    if freshctx is None:
        raise SystemExit("freshctx.py (the fresh-eyes skill) must be installed beside skill-maintenance")
    effort = effort if effort is not None else freshctx.default_effort(family, model, "medium")
    with tempfile.TemporaryDirectory(prefix="judge-") as tmp:
        last = Path(tmp) / "last.txt"
        cwd = Path(tmp) / "empty"
        cwd.mkdir()
        if family == "claude":
            command = freshctx.claude_command(prompt, model, effort, "text", None)
        else:
            command = freshctx.codex_command(prompt, model, effort, last, "read-only", cwd)
        result = freshctx.execute(freshctx.resolve_command(command), cwd, timeout)
        if result["exit"] != 0:
            return f"(evaluator failed: {result['stderr'][-300:]})"
        return freshctx.final_text(family, result, last)


def parse_candidates(items: list[str]) -> list[tuple[str, Path | None]]:
    out = []
    for item in items:
        label, sep, path = item.partition("=")
        if not sep or not label:
            raise SystemExit(f"--candidate needs LABEL=PATH or LABEL=none, got {item!r}")
        out.append((label, None if path == "none" else Path(path).resolve()))
    labels = [label for label, _ in out]
    if len(labels) != len(set(labels)):
        raise SystemExit("candidate labels must be unique")
    return out


def declared_name(skill: Path) -> str:
    match = re.search(r"^name:\s*([a-z0-9][a-z0-9-]*)\s*$", read(skill / "SKILL.md"), re.M)
    if not match:
        raise SystemExit(f"{skill}: SKILL.md declares no name; candidates are copied under their declared name")
    return match.group(1)


def prepare_workdir(parent: Path, fx: dict, skill: Path | None, extra_skills: list[Path]) -> Path:
    workdir = Path(tempfile.mkdtemp(prefix="work-", dir=str(Path(tempfile.mkdtemp(prefix="w", dir=str(parent))))))
    if fx["setup"].is_dir():
        shutil.copytree(fx["setup"], workdir, dirs_exist_ok=True)
    for folder in ([skill] if skill else []) + extra_skills:
        shutil.copytree(folder, workdir / ".skills" / declared_name(folder), dirs_exist_ok=True)
    if fx["setup_script"].is_file():
        staged = workdir / ".setup.sh"
        shutil.copyfile(fx["setup_script"], staged)
        subprocess.run(["bash", str(staged)], cwd=str(workdir), check=True, capture_output=True, timeout=120, env=runctl.minimal_env())
        staged.unlink()
    return workdir


def evaluate(args: argparse.Namespace) -> int:
    fx = load_fixture(Path(args.fixture).resolve())
    candidates = parse_candidates(args.candidate)
    labels = [label for label, _ in candidates]
    if not args.must_pass:
        raise SystemExit("--must-pass names the candidate the bar applies to; a run with nothing to enforce cannot PASS")
    declared = {declared_name(skill) for _, skill in candidates if skill}
    if len(declared) > 1:
        raise SystemExit(f"candidates declare different skill names {sorted(declared)}; a worker could tell variants apart by name")
    for label in args.baseline or []:
        if label not in labels:
            raise SystemExit(f"--baseline {label!r} is not a candidate")
    corpus = fx["task"] + "".join(read(skill / "SKILL.md") for _, skill in candidates if skill)
    for label in labels:
        if re.search(rf"(?<![a-z0-9]){re.escape(label.lower())}(?![a-z0-9])", corpus.lower()):
            raise SystemExit(f"label {label!r} occurs in the task or a candidate body; use an opaque label such as v1/v2")
    for label in args.must_pass:
        if label not in labels:
            raise SystemExit(f"--must-pass {label!r} is not a candidate")
    extra = [Path(p).resolve() for p in (args.also_skill or [])]
    problems = lint_fixture(fx, labels)
    if problems:
        print("\n".join(f"blindeval: LEAK: {p}" for p in problems), file=sys.stderr)
        print("VERDICT: FAIL (blinding)")
        return 2
    probes = leak_probes(fx["expected"])
    out_dir = Path(args.out).resolve() if args.out else Path(tempfile.mkdtemp(prefix="blindeval-"))
    if out_dir.exists() and any(out_dir.iterdir()):
        raise SystemExit("--out must be empty; preserve prior evidence")
    out_dir.mkdir(parents=True, exist_ok=True)
    parent = Path(tempfile.mkdtemp(prefix="run-"))
    try:
        return _evaluate(args, fx, candidates, labels, extra, probes, out_dir, parent)
    finally:
        if not args.keep:
            shutil.rmtree(parent, ignore_errors=True)


def _evaluate(args, fx, candidates, labels, extra, probes, out_dir, parent) -> int:
    ids: dict[str, str] = {}
    recordings: dict[str, dict] = {}
    workdirs: dict[str, Path] = {}
    prompts_to_write: dict[str, str] = {}
    order = list(candidates)
    secrets.SystemRandom().shuffle(order)
    if args.reuse:
        needs_workspace = [c for c in fx["checks"] if c.split()[0] in {"file", "tree"}]
        if needs_workspace:
            raise SystemExit(f"reuse: {len(needs_workspace)} check(s) need the worker's workspace, which is gone; run the workers again")
        texts = {label: (read(skill / "SKILL.md") if skill else None) for label, skill in candidates}
        for prompt_path in sorted(Path(args.reuse).glob("w-*.prompt.txt")):
            wid = prompt_path.name.split(".")[0]
            prompt = read(prompt_path)
            matched = [label for label, text in texts.items() if text and text.strip() in prompt]
            if not matched:
                matched = [label for label, text in texts.items() if text is None and "Instructions loaded for this task" not in prompt]
            if len(matched) != 1:
                raise SystemExit(f"reuse: cannot attribute {wid} to exactly one candidate (matched {matched})")
            ids[wid] = matched[0]
            rec = json.loads(read(Path(args.reuse) / f"{wid}.json"))
            if rec.get("rubric_digest") != rubric_digest(fx):
                raise SystemExit(f"reuse: {wid} was recorded against a different rubric or task; run the workers again")
            stored = {c[1]: bool(c[0]) for c in rec.get("checks", [])}
            for check in fx["checks"]:
                if check.split()[0] in {"final", "command", "reads", "writes"}:
                    fresh, _ = run_check(check, rec, Path(args.reuse))
                    if stored.get(check) is not None and fresh != stored.get(check):
                        raise SystemExit(f"reuse: {wid} stored a different result for {check!r} than its own recording supports")
                    stored[check] = fresh
            rec["checks"] = [(stored.get(c, False), c) for c in fx["checks"]]
            rec["checks_passed"] = sum(1 for ok, _ in rec["checks"] if ok)
            recordings[wid] = rec
        missing = [label for label, _ in candidates if label not in ids.values()]
        order = [(label, skill) for label, skill in order if label in missing]
    for label, skill in order:
        wid = hidden_id()
        while wid in ids:
            wid = hidden_id()
        ids[wid] = label
        try:
            workdir = prepare_workdir(parent, fx, skill, extra)
        except (OSError, subprocess.SubprocessError) as error:
            recordings[wid] = {"exit": None, "error": f"workspace setup failed: {error}",
                               "checks": [(False, c) for c in fx["checks"]], "checks_passed": 0,
                               "rubric_digest": rubric_digest(fx)}
            continue
        skill_text = read(skill / "SKILL.md") if skill else None
        prompt = worker_prompt(fx["task"], declared_name(skill) if skill else None, skill_text)
        assert_blind(prompt, [fx["name"], *ids, *labels], probes, f"worker prompt for {wid}", vocabulary=False)
        extra_env = {}
        for item in args.env or []:
            key, _, value = item.partition("=")
            extra_env[key] = value.replace("{workdir}", str(workdir))
        try:
            env = runctl.minimal_env(extra_env)
        except ValueError as error:
            raise SystemExit(f"--env: {error}; credential-bearing environment variables are refused")
        env["AI_SKILLS_STATE"] = str(workdir / "state")
        env["TMPDIR"] = str(workdir.parent / "tmp")
        Path(env["TMPDIR"]).mkdir(exist_ok=True)
        started = time.monotonic()
        try:
            rec = run_worker(args.runner, args.family, prompt, workdir, env, args.effort, args.timeout, args.model,
                             args.allow_unsandboxed_claude)
        except (OSError, subprocess.SubprocessError, SystemExit) as error:
            rec = {"exit": None, "error": f"worker dispatch failed: {error}"}
        rec = sanitize(rec, workdir)
        rec["elapsed_seconds"] = round(time.monotonic() - started, 3)
        rec["file_evidence"] = sanitize(collect_file_evidence(fx["checks"], workdir, rec.get("writes")), workdir)
        rec["checks"] = [run_check(c, rec, workdir) for c in fx["checks"]]
        rec["checks_passed"] = sum(1 for ok, _ in rec["checks"] if ok)
        rec["rubric_digest"] = rubric_digest(fx)
        recordings[wid] = rec
        workdirs[wid] = workdir
        prompts_to_write[wid] = prompt

    for wid, rec in recordings.items():
        (out_dir / f"{wid}.json").write_text(json.dumps(rec, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    scores: dict[str, float] = {}
    judge_text = ""
    judge_error = ""
    if fx["judge"]:
        prompt = judge_prompt(fx, recordings)
        assert_blind(prompt, [fx["name"]], [], "evaluator prompt", vocabulary=False)
        assert_unmapped(prompt, list(ids), labels, [str(p) for _, p in candidates if p], "evaluator prompt")
        (out_dir / "judge.prompt.txt").write_text(prompt, encoding="utf-8")
        try:
            judge_text = run_judge(args.judge_runner or args.runner, args.judge_family or args.family, prompt, args.timeout, args.judge_model, args.judge_effort)
        except (OSError, subprocess.SubprocessError, SystemExit) as error:
            judge_text = f"evaluator dispatch failed: {error}"
        judge_text = runctl.redact(judge_text)
        (out_dir / "judge.txt").write_text(judge_text, encoding="utf-8")
        scores = parse_scores(judge_text)
        missing = sorted(set(recordings) - set(scores))
        if missing:
            judge_error = f"the evaluator returned no score for {missing}: {judge_text.strip()[-200:]!r}"

    for wid, prompt in prompts_to_write.items():
        (out_dir / f"{wid}.prompt.txt").write_text(prompt, encoding="utf-8")
    report = {"fixture": fx["name"], "results": {}, "out": str(out_dir),
              "worker": {"family": args.family, "model": args.model, "effort": args.effort},
              "judge": {"family": args.judge_family or args.family,
                        "model": args.judge_model, "effort": args.judge_effort}}
    for wid, label in ids.items():
        rec = recordings[wid]
        report["results"][label] = {
            "id": wid,
            "checks": f"{rec['checks_passed']}/{len(fx['checks'])}",
            "failed_checks": [c for ok, c in rec["checks"] if not ok],
            "score": scores.get(wid),
            "error": rec.get("error", ""),
            "exit": rec.get("exit"),
            "elapsed_seconds": rec.get("elapsed_seconds"),
            "tokens": None,
            "final": (rec.get("final") or "")[:400],
        }
    failures = []
    if judge_error:
        failures.append(judge_error)
    baselines = set(args.baseline or [])
    for label in args.must_pass or []:
        result = report["results"].get(label)
        if result is None:
            failures.append(f"{label} was not a candidate")
            continue
        rec = recordings[result["id"]]
        if type(rec.get("exit")) is not int or rec["exit"] != 0:
            failures.append(f"{label}: worker exit is not a verified zero: {rec.get('exit')!r}")
        if rec.get("error"):
            failures.append(f"{label}: worker error: {rec['error']}")
        if fx["judge"] and result["score"] is None:
            failures.append(f"{label}: no evaluator score")
        if fx["judge"] and fx["min_score"] is not None and result["score"] is not None and result["score"] < fx["min_score"]:
            failures.append(f"{label}: scored {result['score']}, bar is {fx['min_score']}")
        if rec["checks_passed"] < fx["min_checks"]:
            failures.append(f"{label}: {rec['checks_passed']} checks passed, bar is {fx['min_checks']}: {result['failed_checks']}")
        for base in baselines:
            if base not in report["results"]:
                failures.append(f"baseline {base} has no recording")
                continue
            base_rec = recordings[report["results"][base]["id"]]
            if type(base_rec.get("exit")) is not int or base_rec["exit"] != 0:
                failures.append(f"baseline {base}: worker exit is not a verified zero: {base_rec.get('exit')!r}")
            if base_rec.get("error"):
                failures.append(f"baseline {base}: worker error: {base_rec['error']}")
            passed = {c for ok, c in rec["checks"] if ok}
            lost = [c for ok, c in base_rec["checks"] if ok and c not in passed]
            if lost:
                failures.append(f"{label} lost checks passed by {base}: {lost}")
            if fx["judge"]:
                if result["score"] is None or report["results"][base]["score"] is None:
                    failures.append(f"cannot compare {label} with {base}: an evaluator score is missing")
                elif result["score"] < report["results"][base]["score"]:
                    failures.append(f"{label} scored below {base} ({result['score']} < {report['results'][base]['score']})")
    report["failures"] = failures
    report["passed"] = not failures
    (out_dir / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if failures:
        print("\n".join(f"blindeval: {f}" for f in failures), file=sys.stderr)
        print("VERDICT: FAIL")
        return 1
    print("VERDICT: PASS")
    return 0


def evaluate_runs(args: argparse.Namespace) -> int:
    fixtures = args.fixture
    if args.repeat < 1:
        raise SystemExit("--repeat must be positive")
    if len(set(fixtures)) != len(fixtures):
        raise SystemExit("duplicate --fixture; use --repeat for repeated attempts")
    candidates = parse_candidates(args.candidate)
    calls = args.repeat * sum(len(candidates) + bool(load_fixture(Path(f))["judge"]) for f in fixtures)
    multiple = len(fixtures) * args.repeat > 1
    if multiple and args.reuse:
        raise SystemExit("--reuse supports one fixture and one repeat only")
    if multiple and args.max_calls is None:
        raise SystemExit("multi-run comparisons require --max-calls (workers plus judges)")
    if args.max_calls is not None and (args.max_calls < 1 or calls > args.max_calls):
        raise SystemExit(f"comparison needs {calls} calls, exceeding --max-calls {args.max_calls}")
    if not multiple:
        args.fixture = fixtures[0]
        return evaluate(args)
    for fixture in fixtures:
        problems = lint_fixture(load_fixture(Path(fixture).resolve()), [label for label, _ in candidates])
        if problems:
            raise SystemExit("; ".join(problems))
    out = Path(args.out).resolve() if args.out else Path(tempfile.mkdtemp(prefix="blindeval-"))
    if out.exists() and any(out.iterdir()):
        raise SystemExit("multi-run --out must be empty; preserve prior evidence")
    out.mkdir(parents=True, exist_ok=True)
    cells = [(index, fixture, repeat) for index, fixture in enumerate(fixtures, 1)
             for repeat in range(1, args.repeat + 1)]
    secrets.SystemRandom().shuffle(cells)
    summary = {"planned_calls": calls, "max_calls": args.max_calls, "runs": [],
               "limits": "Wall time includes dispatch. Tokens unavailable. Repeats are not population estimates."}
    failed = False
    for index, fixture, repeat in cells:
        cell = copy.copy(args)
        cell.fixture = fixture
        cell.out = str(out / f"case-{index}-run-{repeat}")
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
            try:
                code = evaluate(cell)
            except (SystemExit, OSError, subprocess.SubprocessError) as error:
                print(str(error))
                code = 2
        log = out / f"case-{index}-run-{repeat}.log"
        log.write_text(captured.getvalue(), encoding="utf-8")
        report_path = Path(cell.out) / "report.json"
        report = json.loads(report_path.read_text()) if report_path.is_file() else {}
        summary["runs"].append({"fixture": fixture, "repeat": repeat, "exit": code,
                                "results": report.get("results", {}), "log": log.name})
        failed = failed or code != 0
        summary["passed"] = not failed and len(summary["runs"]) == len(cells)
        (out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
        print(f"case {index}, repeat {repeat}: {'FAIL' if code else 'PASS'}", flush=True)
    print(f"Report: {out / 'summary.json'}")
    print("VERDICT: FAIL" if failed else "VERDICT: PASS")
    return 1 if failed else 0


def cmd_lint(args: argparse.Namespace) -> int:
    fx = load_fixture(Path(args.fixture).resolve())
    problems = lint_fixture(fx, args.label or [])
    if problems:
        print("\n".join(f"blindeval: LEAK: {p}" for p in problems), file=sys.stderr)
        return 2
    print(f"blind_ok ({fx['name']}: {len(fx['checks'])} checks, judge={'yes' if fx['judge'] else 'no'}, {len(leak_probes(fx['expected']))} leak probes)")
    return 0


def cmd_selftest(_args: argparse.Namespace) -> int:
    def expect_leak(fn, what: str) -> None:
        try:
            fn()
        except Leak:
            return
        raise SystemExit(f"selftest: {what} was not caught")

    with tempfile.TemporaryDirectory(prefix="blindeval-selftest-") as tmp:
        fixture = Path(tmp) / "alpha"
        (fixture / "setup").mkdir(parents=True)
        (fixture / "task.md").write_text("Add a greeting command to the notes tool and show it working.\n", encoding="utf-8")
        (fixture / "expected.md").write_text("- prints 'hello from notes' when run with greet\n", encoding="utf-8")
        (fixture / "rubric.md").write_text("## Checks\n- final ~ hello\n- command ~ greet\n\n## Judge\nDid it run the command?\n\n## Bar\nmin-checks: 2\n", encoding="utf-8")
        (fixture / "setup" / "notes.py").write_text("print('notes')\n", encoding="utf-8")
        fx = load_fixture(fixture)
        if lint_fixture(fx, ["old", "new"]):
            raise SystemExit("selftest: a clean fixture must lint clean")

        (fixture / "task.md").write_text("Add a greeting command that prints 'hello from notes' when run with greet.\n", encoding="utf-8")
        if not any("hidden expected answer" in p for p in lint_fixture(load_fixture(fixture), [])):
            raise SystemExit("selftest: an expected-answer leak in task.md must fail lint")
        (fixture / "task.md").write_text("This is an evaluation of your skills. Add a greeting command.\n", encoding="utf-8")
        if not any("vocabulary" in p for p in lint_fixture(load_fixture(fixture), [])):
            raise SystemExit("selftest: evaluation vocabulary in task.md must fail lint")
        (fixture / "task.md").write_text("Work on the alpha project: add a greeting command.\n", encoding="utf-8")
        if not any("forbidden token" in p for p in lint_fixture(load_fixture(fixture), [])):
            raise SystemExit("selftest: the fixture name in task.md must fail lint")
        (fixture / "task.md").write_text("Add a greeting command to the notes tool.\n", encoding="utf-8")
        (fixture / "setup" / "candidate-new.txt").write_text("x\n", encoding="utf-8")
        if not any("setup path" in p for p in lint_fixture(load_fixture(fixture), ["new"])):
            raise SystemExit("selftest: a label in a setup path must fail lint")
        (fixture / "setup" / "candidate-new.txt").unlink()
        (fixture / "setup.sh").write_text("#!/usr/bin/env bash\ncp ../expected.md .\n", encoding="utf-8")
        if not any("hidden files" in p for p in lint_fixture(load_fixture(fixture), [])):
            raise SystemExit("selftest: setup.sh reaching for expected.md must fail lint")
        (fixture / "setup.sh").write_text('#!/usr/bin/env bash\ncp "$(dirname "$0")"/expec*.md leaked.md\n', encoding="utf-8")
        if not any("hidden files" in p for p in lint_fixture(load_fixture(fixture), [])):
            raise SystemExit("selftest: setup.sh locating itself must fail lint")
        (fixture / "setup.sh").write_text('#!/usr/bin/env bash\ncp "$(dirname "$0")"/expec*.md leaked.md 2>/dev/null || true\n', encoding="utf-8")
        probe_work = prepare_workdir(Path(tmp), load_fixture(fixture), None, [])
        if (probe_work / "leaked.md").exists() or (probe_work / ".setup.sh").exists():
            raise SystemExit("selftest: the staged setup script must not reach the fixture's hidden files")
        (fixture / "setup.sh").unlink()
        (fixture / "setup" / "NOTES.md").write_text("This project is a benchmark for agents.\n", encoding="utf-8")
        if not any("vocabulary" in p for p in lint_fixture(load_fixture(fixture), [])):
            raise SystemExit("selftest: evaluation vocabulary inside a setup file must fail lint")
        (fixture / "setup" / "NOTES.md").unlink()
        os.symlink(Path.home() / ".profile", fixture / "setup" / "id")
        if not any("symlink" in p for p in lint_fixture(load_fixture(fixture), [])):
            raise SystemExit("selftest: a symlink under setup must fail lint")
        (fixture / "setup" / "id").unlink()
        (fixture / "setup" / "dump.log").write_bytes(b"x" * (MAX_LINT_BYTES + 1))
        if not any("larger than" in p for p in lint_fixture(load_fixture(fixture), [])):
            raise SystemExit("selftest: a setup file too large to lint must fail lint")
        (fixture / "setup" / "dump.log").unlink()
        (fixture / "setup" / "Makefile").write_text("check:\n\t# scored against a rubric\n\ttrue\n", encoding="utf-8")
        if not any("Makefile" in p for p in lint_fixture(load_fixture(fixture), [])):
            raise SystemExit("selftest: a setup file without a known suffix must still be linted")
        (fixture / "setup" / "Makefile").unlink()
        (fixture / "rubric.md").write_text("## Judge\nDid it run the command?\n", encoding="utf-8")
        try:
            load_fixture(fixture)
            raise SystemExit("selftest: a judge-only rubric without min-score must be refused")
        except SystemExit as stop:
            if "min-score" not in str(stop):
                raise
        (fixture / "rubric.md").write_text("## Checks\n- final ~ hello\n- command ~ greet\n\n## Judge\nDid it run the command?\n\n## Bar\nmin-checks: 2\n", encoding="utf-8")

        fx = load_fixture(fixture)
        probes = leak_probes(fx["expected"])
        good = worker_prompt(fx["task"], "notes-skill", "# Notes skill\nDo the work well.\n")
        assert_blind(good, ["alpha", "w-1234"], probes, "worker prompt", vocabulary=False)
        expect_leak(lambda: assert_blind(good + "\n(you are w-1234)", ["alpha", "w-1234"], probes, "worker prompt", vocabulary=False), "a hidden id in the worker prompt")
        expect_leak(lambda: assert_blind(good + "\nprints 'hello from notes' when run with greet", [], probes, "worker prompt", vocabulary=False), "the expected answer in the worker prompt")
        recs = {"w-aaaa": {"final": "done", "commands": ["python3 notes.py greet"], "writes": []}, "w-bbbb": {"final": "done", "commands": [], "writes": []}}
        jp = judge_prompt(fx, recs)
        assert_blind(jp, ["alpha"], [], "evaluator prompt", vocabulary=False)
        assert_unmapped(jp + "\nfinal answer: I added a new command", ["w-aaaa", "w-bbbb"], ["v1", "v2"], ["/skills/notes-new"], "evaluator prompt")
        expect_leak(lambda: assert_unmapped(jp.replace("RECORDING w-aaaa", "RECORDING w-aaaa (v2)"), ["w-aaaa", "w-bbbb"], ["v1", "v2"], [], "evaluator prompt"), "an id-to-label mapping in the evaluator prompt")
        if "final answer:\ndone" not in jp:
            raise SystemExit("selftest: the final answer must follow its heading")
        versioned = jp.replace("final answer:\ndone", "final answer:\nbumped to v1.4.3, done", 1)
        if versioned == jp:
            raise SystemExit("selftest: the versioned answer probe did not change the prompt")
        assert_unmapped(versioned, ["w-aaaa", "w-bbbb"], ["v1", "v2"], [], "evaluator prompt")
        expect_leak(lambda: assert_unmapped(jp + "\nv2: w-bbbb", ["w-aaaa", "w-bbbb"], ["v1", "v2"], [], "evaluator prompt"), "a label-to-id mapping in the evaluator prompt")
        expect_leak(lambda: assert_unmapped(jp + "\n/skills/notes-new/SKILL.md", ["w-aaaa"], ["new"], ["/skills/notes-new"], "evaluator prompt"), "a candidate path in the evaluator prompt")
        if parse_scores("SCORE w-aaaa: 7\nSCORE w-bbbb: 3") != {"w-aaaa": 7.0, "w-bbbb": 3.0}:
            raise SystemExit("selftest: score parsing broke")

        work = Path(tmp) / "work"
        work.mkdir()
        (work / "out.txt").write_text("hello\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(work / "repo")], check=True)
        rec = {"final": "hello there", "commands": ["python3 notes.py greet"], "reads": ["README.md"], "writes": ["out.txt"]}
        for check, want in (
            ("final ~ hello", True), ("final !~ hello", False), ("command ~ greet", True), ("command !~ greet", False),
            ("reads ~ README", True), ("writes !~ notes.py", True), ("writes !~ out", False),
            ("file exists out.txt", True), ("file missing out.txt", False), ("file exists nope-*.txt", False),
            ("file ~ out.txt hel+o", True), ("tree clean repo", True),
        ):
            ok, _ = run_check(check, rec, work)
            if ok != want:
                raise SystemExit(f"selftest: check {check!r} returned {ok}, want {want}")
        (work / "repo" / "dirty.txt").write_text("x\n", encoding="utf-8")
        if run_check("tree clean repo", rec, work)[0]:
            raise SystemExit("selftest: tree clean must fail on an untracked file")

        fake = Path(tmp) / "fake-worker.sh"
        fake.write_text(
            "#!/usr/bin/env bash\n"
            "if [ -d .skills/good ]; then printf '%s' '{\"final\":\"hello from notes\",\"commands\":[\"python3 notes.py greet\"],\"reads\":[],\"writes\":[],\"exit\":0,\"error\":\"\"}';\n"
            "else printf '%s' '{\"final\":\"I could not\",\"commands\":[],\"reads\":[],\"writes\":[],\"exit\":0,\"error\":\"\"}'; fi\n",
            encoding="utf-8",
        )
        fake.chmod(0o755)
        judge = Path(tmp) / "fake-judge.sh"
        judge.write_text("#!/usr/bin/env bash\ngrep -o 'RECORDING w-[0-9a-f]*' | sed 's/RECORDING /SCORE /; s/$/: 5/'\n", encoding="utf-8")
        judge.chmod(0o755)
        good_skill = Path(tmp) / "skills" / "good"
        good_skill.mkdir(parents=True)
        (good_skill / "SKILL.md").write_text("---\nname: good\ndescription: Use for greetings.\n---\nGreet.\n", encoding="utf-8")
        argv = ["run", "--fixture", str(fixture), "--candidate", f"v2={good_skill}", "--candidate", "v1=none",
                "--runner", f"fake:{fake}", "--judge-runner", f"fake:{judge}", "--family", "claude",
                "--must-pass", "v2", "--baseline", "v1", "--out", str(Path(tmp) / "out")]
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            try:
                main(argv[:-6] + ["--out", str(Path(tmp) / "out0")])
                refused = False
            except SystemExit as stop:
                refused = "names the candidate" in str(stop)
        if not refused:
            raise SystemExit("selftest: a run without --must-pass must be refused")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            for bad_argv, expect in ((["run", "--fixture", str(fixture), "--candidate", f"greet={good_skill}", "--runner", f"fake:{fake}", "--must-pass", "greet", "--out", str(Path(tmp) / "outl")], "opaque label"),
                                     (["run", "--fixture", str(fixture), "--candidate", f"v2={good_skill}", "--runner", f"fake:{fake}", "--must-pass", "v2", "--baseline", "v9", "--out", str(Path(tmp) / "outl")], "not a candidate")):
                try:
                    main(bad_argv)
                    raise SystemExit("SELFTEST-VACUOUS")
                except SystemExit as stop:
                    if expect not in str(stop):
                        raise SystemExit(f"selftest: expected a refusal mentioning {expect!r}, got {stop}")
        leaky_worker = Path(tmp) / "leaky-worker.sh"
        key = "AKIA" + "QQQQQQQQQQQQQQQQ"
        leaky_worker.write_text("#!/usr/bin/env bash\nprintf '%s' '{\"final\":\"hello from notes, key " + key + "\",\"commands\":[\"python3 notes.py greet\"],\"reads\":[],\"writes\":[],\"exit\":0,\"error\":\"\"}'\n", encoding="utf-8")
        leaky_worker.chmod(0o755)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            main(["run", "--fixture", str(fixture), "--candidate", f"v2={good_skill}", "--runner", f"fake:{leaky_worker}",
                  "--judge-runner", f"fake:{judge}", "--family", "claude", "--must-pass", "v2", "--out", str(Path(tmp) / "outk")])
        persisted = "".join(p.read_text(encoding="utf-8") for p in (Path(tmp) / "outk").glob("*"))
        if key in persisted or "[REDACTED]" not in persisted:
            raise SystemExit("selftest: a credential in a worker answer must be redacted before it is persisted or judged")
        mute_judge = Path(tmp) / "mute-judge.sh"
        mute_judge.write_text("#!/usr/bin/env bash\necho 'I could not decide'\n", encoding="utf-8")
        mute_judge.chmod(0o755)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = main(["run", "--fixture", str(fixture), "--candidate", f"v2={good_skill}", "--runner", f"fake:{fake}",
                         "--judge-runner", f"fake:{mute_judge}", "--family", "claude", "--must-pass", "v2", "--out", str(Path(tmp) / "outm")])
        if code != 1:
            raise SystemExit("selftest: a missing evaluator score must fail the run")
        variant = Path(tmp) / "skills" / "good-variant-b"
        shutil.copytree(good_skill, variant)
        work = prepare_workdir(Path(tmp), fx, variant, [])
        if not (work / ".skills" / "good").is_dir() or (work / ".skills" / "good-variant-b").exists():
            raise SystemExit("selftest: a candidate must be copied under its declared skill name, not its directory name")
        other = Path(tmp) / "skills" / "good-renamed"
        shutil.copytree(good_skill, other)
        (other / "SKILL.md").write_text((other / "SKILL.md").read_text(encoding="utf-8").replace("name: good", "name: good-renamed"), encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            try:
                main(["run", "--fixture", str(fixture), "--candidate", f"v3={good_skill}", "--candidate", f"v4={other}", "--runner", f"fake:{fake}", "--judge-runner", f"fake:{judge}", "--must-pass", "v3", "--out", str(Path(tmp) / "outn")])
                raise SystemExit("selftest: candidates with different declared names must be refused")
            except SystemExit as stop:
                if "different skill names" not in str(stop):
                    raise
        reuse_dir = Path(tmp) / "outq"
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            if main([*argv[:-2], "--out", str(reuse_dir)]) != 0:
                raise SystemExit("selftest: the recording run for reuse must pass")
        target = next(p for p in sorted(reuse_dir.glob("w-*.json")) if "I could not" in p.read_text(encoding="utf-8"))
        forged = json.loads(target.read_text(encoding="utf-8"))
        forged["checks"] = [[True, c] for _, c in forged["checks"]]
        forged["checks_passed"] = len(forged["checks"])
        target.write_text(json.dumps(forged), encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            try:
                main(["run", "--fixture", str(fixture), "--candidate", f"v2={good_skill}", "--candidate", "v1=none", "--runner", f"fake:{fake}", "--judge-runner", f"fake:{judge}", "--must-pass", "v2", "--baseline", "v1", "--reuse", str(reuse_dir), "--out", str(Path(tmp) / "outr")])
                forged_ok = True
            except SystemExit as stop:
                forged_ok = "different result" not in str(stop)
        if forged_ok:
            raise SystemExit("selftest: a forged recording must be refused on reuse")
        (fixture / "rubric.md").write_text("## Checks\n- final ~ hello\n- file exists out.txt\n\n## Bar\nmin-checks: 1\n", encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            try:
                main(["run", "--fixture", str(fixture), "--candidate", f"v2={good_skill}", "--runner", f"fake:{fake}", "--must-pass", "v2", "--reuse", str(reuse_dir), "--out", str(Path(tmp) / "outw")])
                raise SystemExit("SELFTEST-VACUOUS")
            except SystemExit as stop:
                if "workspace" not in str(stop):
                    raise SystemExit("selftest: reuse with a workspace check must be refused")
        (fixture / "rubric.md").write_text("## Checks\n- final ~ hello\n- command ~ greet\n\n## Judge\nDid it run the command?\n\n## Bar\nmin-checks: 2\n", encoding="utf-8")
        (fixture / "rubric.md").write_text("## Checks\n- final ~ hello\n\n## Judge\nDid it run the command?\n\n## Bar\nmin-checks: 1\nmin-score: 8\n", encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = main(["run", "--fixture", str(fixture), "--candidate", f"v2={good_skill}", "--runner", f"fake:{fake}", "--judge-runner", f"fake:{judge}", "--family", "claude", "--must-pass", "v2", "--out", str(Path(tmp) / "outs")])
        if code != 1:
            raise SystemExit("selftest: a score below min-score must fail the run")
        (fixture / "rubric.md").write_text("## Checks\n- final ~ hello\n- command ~ greet\n\n## Judge\nDid it run the command?\n\n## Bar\nmin-checks: 2\n", encoding="utf-8")
        spy_out = Path(tmp) / "outspy"
        spy = Path(tmp) / "spy-worker.sh"
        spy.write_text("#!/usr/bin/env bash\nls " + str(spy_out) + "/w-*.json >/dev/null 2>&1 && seen=1 || seen=0\nprintf '%s' \"{\\\"final\\\":\\\"hello from notes seen=$seen\\\",\\\"commands\\\":[\\\"python3 notes.py greet\\\"],\\\"reads\\\":[],\\\"writes\\\":[],\\\"exit\\\":0,\\\"error\\\":\\\"\\\"}\"\n", encoding="utf-8")
        spy.chmod(0o755)
        spy_in = Path(tmp) / "spy-in"
        spy_in.mkdir()
        base_rec = json.loads(next(p for p in sorted(reuse_dir.glob("w-*.json")) if "I could not" in p.read_text(encoding="utf-8")).read_text(encoding="utf-8"))
        base_rec["checks"] = [[False, c] for c in fx["checks"]]
        base_rec["checks_passed"] = 0
        (spy_in / "w-c0de.json").write_text(json.dumps(base_rec), encoding="utf-8")
        (spy_in / "w-c0de.prompt.txt").write_text(worker_prompt(fx["task"], None, None), encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            main(["run", "--fixture", str(fixture), "--candidate", f"v2={good_skill}", "--candidate", "v1=none", "--runner", f"fake:{spy}", "--judge-runner", f"fake:{judge}", "--must-pass", "v2", "--reuse", str(spy_in), "--out", str(spy_out)])
        fresh = next(p for p in spy_out.glob("w-*.json") if "seen=" in p.read_text(encoding="utf-8"))
        if "seen=1" in fresh.read_text(encoding="utf-8"):
            raise SystemExit("selftest: a reused recording must not be on disk while a fresh worker runs")
        bad_fixture = Path(tmp) / "beta"
        shutil.copytree(fixture, bad_fixture)
        (bad_fixture / "setup.sh").write_text("#!/usr/bin/env bash\nexit 3\n", encoding="utf-8")
        before = set(Path(tempfile.gettempdir()).glob("run-*"))
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            try:
                main(["run", "--fixture", str(bad_fixture), "--candidate", f"v2={good_skill}", "--runner", f"fake:{fake}", "--judge-runner", f"fake:{judge}", "--must-pass", "v2", "--out", str(Path(tmp) / "outb")])
            except (SystemExit, subprocess.CalledProcessError):
                pass
        if set(Path(tempfile.gettempdir()).glob("run-*")) - before:
            raise SystemExit("selftest: a failed run must not leave worker directories behind")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            code = main(argv)
        if code != 0 or "VERDICT: PASS" not in buf.getvalue():
            raise SystemExit(f"selftest: a passing candidate must pass the pipeline; exit {code}\n{buf.getvalue()}")
        report = json.loads(buf.getvalue().split("\nVERDICT")[0])
        if report["results"]["v2"]["checks"] != "2/2" or report["results"]["v1"]["checks"] != "0/2":
            raise SystemExit(f"selftest: mapping revealed the wrong results: {report['results']}")
        recorded = {p.name: p.read_bytes() for p in (Path(tmp) / "out").iterdir()}
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            try:
                main(argv)
                raise SystemExit("selftest: existing evidence must not be overwritten")
            except SystemExit as stop:
                if "--out must be empty" not in str(stop):
                    raise
        if recorded != {p.name: p.read_bytes() for p in (Path(tmp) / "out").iterdir()}:
            raise SystemExit("selftest: refusing a reused output directory changed existing evidence")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            code = main([*argv[:-2], "--must-pass", "v1", "--out", str(Path(tmp) / "out2")])
        if code != 1:
            raise SystemExit("selftest: a candidate below the bar must fail the pipeline")
        (fixture / "task.md").write_text("This is an evaluation. Add a greeting command.\n", encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = main(argv)
        if code != 2:
            raise SystemExit("selftest: a leaking fixture must be refused with exit 2")

    print("blindeval_selftest_ok (answer, vocabulary, label, id, path, and credential leaks all turn the gate red; nothing to enforce is not a pass)")
    return 0


def main(argv: list[str] | None = None) -> int:
    if argv is None and len(sys.argv) > 1 and sys.argv[1] == "run" and "--argv-file" not in sys.argv:
        with tempfile.NamedTemporaryFile("w", prefix="args-", suffix=".json", delete=False) as fh:
            json.dump(sys.argv[1:], fh)
            os.chmod(fh.name, 0o600)
        os.execv(sys.executable, [sys.executable, sys.argv[0], "run", "--argv-file", fh.name])
    if argv is None and "--argv-file" in sys.argv:
        path = sys.argv[sys.argv.index("--argv-file") + 1]
        argv = json.loads(Path(path).read_text(encoding="utf-8"))
        os.unlink(path)
    parser = argparse.ArgumentParser(description="Blinded behavior evaluation of a skill change.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    lint = sub.add_parser("lint", help="check a fixture for leakage without running anything")
    lint.add_argument("--fixture", required=True)
    lint.add_argument("--label", action="append", help="candidate labels that must not appear; repeatable")
    lint.set_defaults(func=cmd_lint)
    run = sub.add_parser("run", help="run every candidate blind, grade, then reveal")
    run.add_argument("--fixture", required=True, action="append", help="fixture directory; repeat for several tasks")
    run.add_argument("--repeat", type=int, default=1, help="fresh attempts per fixture")
    run.add_argument("--max-calls", type=int, help="maximum worker plus judge calls; required for multi-run")
    run.add_argument("--candidate", action="append", required=True, help="LABEL=<skill-dir> or LABEL=none; repeatable")
    run.add_argument("--also-skill", action="append", help="sibling skill folder every worker also gets; repeatable")
    run.add_argument("--family", default="codex", choices=("claude", "codex"))
    run.add_argument("--allow-unsandboxed-claude", action="store_true",
                     help="explicitly allow Claude write workers with host file access; permission rules remain active")
    run.add_argument("--judge-family", choices=("claude", "codex"))
    run.add_argument("--runner", default="model", help="model | fake:<script>")
    run.add_argument("--judge-runner", help="model | fake:<script> (default: same as --runner)")
    run.add_argument("--effort")
    run.add_argument("--model", default="default", help="explicit worker model; default preserves the CLI default")
    run.add_argument("--judge-model", default="default")
    run.add_argument("--judge-effort")
    run.add_argument("--timeout", type=int, default=900)
    run.add_argument("--env", action="append", help="KEY=VALUE for workers; {workdir} expands")
    run.add_argument("--must-pass", action="append", help="label that must meet the bar; repeatable")
    run.add_argument("--baseline", action="append", help="label a must-pass candidate may not regress against")
    run.add_argument("--out", help="directory for recordings and prompts")
    run.add_argument("--keep", action="store_true", help="keep the worker directories")
    run.add_argument("--reuse", help="judge the recordings in this directory instead of running workers")
    run.set_defaults(func=evaluate_runs)
    sub.add_parser("selftest", help="prove every leak turns the gate red").set_defaults(func=cmd_selftest)
    args = parser.parse_args(argv)
    if args.cmd == "run":
        if args.runner == "model" and args.family == "claude" and not args.allow_unsandboxed_claude:
            parser.error("Claude write workers require --allow-unsandboxed-claude; the default Codex worker uses workspace-write")
        if args.effort is None:
            args.effort = freshctx.default_effort(args.family, args.model) if freshctx else "low"
        if args.judge_effort is None:
            args.judge_effort = (freshctx.default_effort(args.judge_family or args.family, args.judge_model, "medium")
                                 if freshctx else "medium")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
