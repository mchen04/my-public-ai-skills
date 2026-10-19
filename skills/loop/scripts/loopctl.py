#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ledgerio  # noqa: E402

PASS_VERDICTS = {"APPROVE", "PASS", "CLEAN"}
FAIL_VERDICTS = {"BLOCK", "FAIL", "RED"}
TEST_STATES = {"pass", "fail", "baseline-red", "skipped", "unknown"}
TABLE_HEADER = "| # | verdict | findings | commits | loc_delta | tests | notes | evidence | revision |"
NOT_HUMAN = {"", "self", "me", "author", "agent", "loop", "fixer", "grader"}
MIN_REASON = 8


@dataclass
class Row:
    cycle: int
    verdict: str
    findings: str
    commits: str
    loc_delta: int
    tests: str
    notes: str
    evidence: str = "-"
    revision: str = "-"


def git_output(args: list[str], default: str) -> str:
    try:
        out = subprocess.check_output(["git", *args], text=True, stderr=subprocess.DEVNULL)
    except Exception:
        return default
    return out.strip() or default


def clean_cell(value: object) -> str:
    text = str(value).replace("\n", " ").replace("\r", " ").strip()
    text = re.sub(r"\s+", " ", text)
    text = text.replace("|", r"\|")
    return text or "-"


def split_row(line: str) -> list[str]:
    sentinel = "\0PIPE\0"
    line = line.strip().replace(r"\|", sentinel)
    cells = [part.strip().replace(sentinel, "|") for part in line.strip("|").split("|")]
    return cells


def parse_rows(log_path: Path) -> list[Row]:
    if not log_path.exists():
        return []

    rows: list[Row] = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = split_row(line)
        if len(cells) < 7 or not cells[0].isdigit():
            continue
        try:
            loc_delta = int(cells[4])
        except ValueError:
            loc_delta = 0
        rows.append(
            Row(
                cycle=int(cells[0]),
                verdict=cells[1].upper(),
                findings=cells[2],
                commits=cells[3],
                loc_delta=loc_delta,
                tests=cells[5],
                notes=cells[6],
                evidence=cells[7] if len(cells) > 7 else "-",
                revision=cells[8] if len(cells) > 8 else "-",
            )
        )
    return rows


def finding_count(findings: str) -> int:
    cell = findings.strip()
    if cell.lower() in {"", "-", "0", "none", "clean"}:
        return 0
    tokens = [t.strip() for t in re.split(r"[,;+]", cell) if t.strip()]
    if tokens and all(re.fullmatch(r"\d+", t) for t in tokens):
        return sum(int(t) for t in tokens)
    return len(tokens)


def is_pass(row: Row) -> bool:
    return row.verdict in PASS_VERDICTS


def is_fail(row: Row) -> bool:
    return row.verdict in FAIL_VERDICTS


def consecutive_passes(rows: Iterable[Row]) -> int:
    streak = 0
    for row in reversed(list(rows)):
        if is_pass(row):
            streak += 1
        else:
            break
    return streak


def analyze(rows: list[Row], converge: int, max_cycles: int | None, baseline_diff: int | None, current_diff: int | None) -> dict:
    streak = consecutive_passes(rows)
    reasons: list[str] = []

    if streak >= converge:
        reasons.append("converged")
    if max_cycles is not None and len(rows) >= max_cycles:
        reasons.append("max-cycles")

    if len(rows) >= 2:
        last_two = rows[-2:]
        if all(is_fail(row) for row in last_two):
            same_findings = (
                last_two[0].findings == last_two[1].findings
                and last_two[0].notes == last_two[1].notes
            )
            nonzero = finding_count(last_two[0].findings) > 0
            if same_findings and nonzero:
                reasons.append("identical-findings-2x")
            if all("revert" in row.notes.lower() for row in last_two):
                reasons.append("two-reverts")

    if len(rows) >= 3:
        last_three = rows[-3:]
        counts = [finding_count(row.findings) for row in last_three]
        if all(is_fail(row) for row in last_three) and len(set(counts)) == 1 and counts[0] > 0:
            reasons.append("findings-flat-3x")

    if len(rows) >= 6:
        last_six = rows[-6:]
        if all(is_fail(row) for row in last_six):
            counts = [finding_count(row.findings) for row in last_six]
            deltas = [b - a for a, b in zip(counts, counts[1:])]
            direction_changes = sum(
                1 for a, b in zip(deltas, deltas[1:])
                if (a > 0) != (b > 0) and a != 0 and b != 0
            )
            no_progress = min(counts[3:]) >= min(counts[:3])
            if direction_changes >= 2 and no_progress:
                reasons.append("findings-churning-6x")

    if baseline_diff is not None and current_diff is not None and baseline_diff > 0:
        if current_diff > int(baseline_diff * 1.5):
            reasons.append("diff-grew-50-percent")

    return {
        "cycles": len(rows),
        "consecutive_passes": streak,
        "converge": converge,
        "stop": bool(reasons),
        "reasons": reasons,
        "last_verdict": rows[-1].verdict if rows else None,
        "open_findings": finding_count(rows[-1].findings) if rows else 0,
    }


def frozen_bar(text: str) -> dict:
    head = re.search(r"^base: .*?\|\s*converge:\s*(\d+)(.*)$", text, re.M)
    if not head:
        raise ValueError("the ledger header names no frozen converge value; start a new ledger with `init`")
    cap = re.search(r"max-cycles:\s*(\d+|none)", head.group(2))
    bar = {
        "converge": int(head.group(1)),
        "max_cycles": int(cap.group(1)) if cap and cap.group(1) != "none" else None,
        "legacy": cap is None,
        "changes": [],
    }
    for line in re.findall(r"^bar-change: (.*)$", text, re.M):
        change = dict(re.findall(r"(\S+?)=(\S+)", line))
        bar["converge"] = int(change.get("converge", bar["converge"]))
        cycles = change.get("max-cycles")
        if cycles is not None:
            bar["max_cycles"] = None if cycles == "none" else int(cycles)
        bar["changes"].append(line)
    return bar


def load_bar(log_path: Path, converge: int | None, max_cycles: int | None) -> dict:
    bar = frozen_bar(log_path.read_text(encoding="utf-8"))
    wrong = []
    if converge is not None and converge != bar["converge"]:
        wrong.append(f"--converge {converge} (frozen: {bar['converge']})")
    if max_cycles is not None and max_cycles != bar["max_cycles"]:
        wrong.append(f"--max-cycles {max_cycles} (frozen: {bar['max_cycles'] or 'none'})")
    if wrong:
        raise ValueError(
            "refusing a per-call bar that differs from the ledger: " + ", ".join(wrong)
            + ". Pass nothing to use the frozen bar; a real change is `loopctl.py bar` with --reason and --authorized-by."
        )
    return bar


def table_columns(text: str) -> int:
    return 9 if TABLE_HEADER in text else 7


def cmd_init(args: argparse.Namespace) -> int:
    log_path = Path(args.log)
    if log_path.exists() and not args.force:
        print(f"refusing to overwrite existing log: {log_path}", file=sys.stderr)
        return 1
    if args.converge < 1 or (args.max_cycles is not None and args.max_cycles < 1):
        print("--converge and --max-cycles must be at least 1", file=sys.stderr)
        return 2

    branch = args.branch or git_output(["rev-parse", "--abbrev-ref", "HEAD"], "unknown")
    base = args.base or git_output(["merge-base", "HEAD", "origin/main"], "unknown")
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cap = args.max_cycles if args.max_cycles is not None else "none"
    text = "\n".join(
        [
            f"# {args.loop} - {branch} ({date})",
            "",
            f"base: {base} | converge: {args.converge} | max-cycles: {cap} | test: {args.test}",
            f"notes: {clean_cell(args.notes)}",
            "",
            TABLE_HEADER,
            "|---|---|---|---|---|---|---|---|---|",
        ]
    ) + "\n"
    with ledgerio.locked(log_path):
        ledgerio.atomic_write(log_path, text)
    print(json.dumps({"log": str(log_path), "branch": branch, "base": base, "converge": args.converge,
                      "max_cycles": args.max_cycles}, sort_keys=True))
    return 0


def cmd_bar(args: argparse.Namespace) -> int:
    log_path = Path(args.log)
    if not log_path.exists():
        print(f"log does not exist: {log_path}", file=sys.stderr)
        return 1
    if len((args.reason or "").strip()) < MIN_REASON:
        print("bar: --reason must say why the bar changes", file=sys.stderr)
        return 2
    who = (args.authorized_by or "").strip()
    if who.lower() in NOT_HUMAN:
        print("bar: --authorized-by must name the human who approved the change; the loop may not change its own bar", file=sys.stderr)
        return 2
    if args.converge is None and args.max_cycles is None:
        print("bar: pass --converge and/or --max-cycles", file=sys.stderr)
        return 2
    with ledgerio.locked(log_path):
        text = log_path.read_text(encoding="utf-8")
        try:
            old = frozen_bar(text)
        except ValueError as error:
            print(f"bar: {error}", file=sys.stderr)
            return 2
        parts = [datetime.now(timezone.utc).isoformat(timespec="seconds"), f"after-cycle={len(parse_rows(log_path))}"]
        if args.converge is not None:
            if args.converge < 1:
                print("bar: --converge must be at least 1", file=sys.stderr)
                return 2
            parts.append(f"converge={args.converge}")
        if args.max_cycles is not None:
            parts.append(f"max-cycles={'none' if args.max_cycles == 0 else args.max_cycles}")
        parts += [f"by={clean_cell(who).replace(' ', '_')}", f"reason={clean_cell(args.reason).replace(' ', '_')}"]
        line = "bar-change: " + " ".join(parts)
        lines = text.splitlines()
        at = next((i for i, l in enumerate(lines) if l.startswith("| #")), len(lines))
        while at > 0 and not lines[at - 1].strip():
            at -= 1
        lines.insert(at, line)
        ledgerio.atomic_write(log_path, "\n".join(lines) + "\n")
        new = frozen_bar("\n".join(lines))
    loosened = new["converge"] < old["converge"]
    print(json.dumps({"converge": new["converge"], "max_cycles": new["max_cycles"], "previous": {
        "converge": old["converge"], "max_cycles": old["max_cycles"]}, "loosens_converge": loosened,
        "logged": line}, sort_keys=True))
    return 0


def receipts_dir(log_path: Path) -> Path:
    return log_path.with_name(log_path.name + ".receipts")


def cmd_check(args: argparse.Namespace) -> int:
    log_path = Path(args.log)
    argv = args.argv[1:] if args.argv[:1] == ["--"] else args.argv
    try:
        path, receipt = ledgerio.run_check(argv, repo=Path(args.repo), out_dir=receipts_dir(log_path),
                                           observer="loopctl", passing=PASS_VERDICTS, failing=FAIL_VERDICTS,
                                           timeout=args.timeout)
    except ValueError as error:
        print(f"check: {error}", file=sys.stderr)
        return 2
    print(json.dumps({"receipt": str(path), "observed": receipt["observed"], "exit": receipt["exit"],
                      "verdict_token": receipt["verdict_token"], "revision": receipt["revision"]["id"],
                      "stable": receipt["stable"]}, sort_keys=True))
    return 0


def cmd_record(args: argparse.Namespace) -> int:
    log_path = Path(args.log)
    if not log_path.exists():
        print(f"log does not exist: {log_path}", file=sys.stderr)
        return 1
    if args.tests not in TEST_STATES:
        print(f"invalid tests state {args.tests!r}; use one of {sorted(TEST_STATES)}", file=sys.stderr)
        return 1

    with ledgerio.locked(log_path):
        text = log_path.read_text(encoding="utf-8")
        try:
            bar = load_bar(log_path, args.converge, args.max_cycles)
        except ValueError as error:
            print(f"record: {error}", file=sys.stderr)
            return 2
        verdict = (args.verdict or "").upper()
        evidence = "asserted"
        if args.receipt:
            if table_columns(text) == 7:
                print("record: this ledger predates receipts; start a new ledger to bind cycles to receipts", file=sys.stderr)
                return 2
            receipt = ledgerio.load_receipt(Path(args.receipt)) or {}
            observed = receipt.get("observed")
            token = receipt.get("verdict_token") or observed
            verdict = verdict or str(token or "")
            claimed = "PASS" if verdict in PASS_VERDICTS else "FAIL" if verdict in FAIL_VERDICTS else None
            problems = ledgerio.receipt_problems(Path(args.receipt), repo=Path(args.repo),
                                                 require_fresh=claimed == "PASS")
            if observed == "INDETERMINATE":
                problems.append("the receipt is indeterminate; it never moves the streak")
            elif claimed and observed and claimed != observed:
                problems.append(f"--verdict {verdict} contradicts the receipt, which observed {observed}")
            if problems:
                print("\n".join(f"record: {p}" for p in problems), file=sys.stderr)
                return 2
            evidence = ledgerio.receipt_tag(Path(args.receipt))
        if verdict not in PASS_VERDICTS | FAIL_VERDICTS:
            print(f"invalid verdict {args.verdict!r}; use one of {sorted(PASS_VERDICTS | FAIL_VERDICTS)}", file=sys.stderr)
            return 1

        rows = parse_rows(log_path)
        cycle = args.cycle or (rows[-1].cycle + 1 if rows else 1)
        cells = [str(cycle), verdict, clean_cell(args.findings), clean_cell(args.commits),
                 str(args.loc_delta), args.tests, clean_cell(args.notes)]
        if table_columns(text) == 9:
            revision = ledgerio.worktree_revision(Path(args.repo))
            cells += [evidence, revision["id"] if revision else "-"]
        ledgerio.append_line(log_path, "| " + " | ".join(cells) + " |")
        rows = parse_rows(log_path)
    print(json.dumps(analyze(rows, bar["converge"], bar["max_cycles"], None, None), sort_keys=True))
    return 0


def receipt_path_of(log_path: Path, evidence: str) -> Path | None:
    match = re.match(r"receipt:([^#\s]+)#", evidence)
    return receipts_dir(log_path) / match.group(1) if match else None


def cmd_status(args: argparse.Namespace) -> int:
    log_path = Path(args.log)
    if not log_path.exists():
        print(f"log does not exist: {log_path}", file=sys.stderr)
        return 1
    try:
        bar = load_bar(log_path, args.converge, args.max_cycles)
    except ValueError as error:
        print(f"status: {error}", file=sys.stderr)
        return 2
    rows = parse_rows(log_path)
    result = analyze(rows, bar["converge"], bar["max_cycles"], args.baseline_diff_lines, args.current_diff_lines)
    streak = rows[len(rows) - result["consecutive_passes"]:] if result["consecutive_passes"] else []
    problems = []
    for row in streak:
        receipt = receipt_path_of(log_path, row.evidence)
        if receipt is not None:
            problems += [f"cycle {row.cycle}: {p}" for p in ledgerio.receipt_problems(receipt, repo=None)]
    current = ledgerio.worktree_revision(Path(args.repo))
    last = rows[-1] if rows else None
    if last is not None and is_pass(last) and current is not None:
        if last.revision in ("", "-"):
            result["revision_bound"] = False
        elif last.revision != current["id"]:
            problems.append(f"cycle {last.cycle} passed at {last.revision}; the worktree is now {current['id']}")
    if problems and "converged" in result["reasons"]:
        result["reasons"].remove("converged")
        result["stop"] = bool(result["reasons"])
    result.update(
        bar={"converge": bar["converge"], "max_cycles": bar["max_cycles"], "changes": bar["changes"],
             "legacy_header": bar["legacy"]},
        streak_basis={"receipt": sum(1 for r in streak if r.evidence.startswith("receipt:")),
                      "asserted": sum(1 for r in streak if not r.evidence.startswith("receipt:"))},
        evidence_problems=problems,
    )
    print(json.dumps(result, sort_keys=True))
    if args.exit_stop and result["stop"]:
        return 2
    return 0


def cmd_selftest(_: argparse.Namespace) -> int:
    import contextlib
    import io

    def run(argv: list[str], expect: int) -> dict:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(argv)
        if code != expect:
            raise SystemExit(f"selftest failed: {argv[:1]} exited {code}, want {expect}\n{err.getvalue()}")
        text = out.getvalue().strip()
        return json.loads(text.splitlines()[-1]) if text.startswith("{") else {"stderr": err.getvalue()}

    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        (repo / "app.txt").write_text("v1\n", encoding="utf-8")
        log = str(Path(tmp) / "loop.log.md")
        common = ["--log", log, "--repo", str(repo)]
        run(["init", "--log", log, "--branch", "test-branch", "--base", "origin/main", "--loop", "Loop Selftest",
             "--test", "none", "--converge", "2", "--max-cycles", "9", "--notes", "selftest"], 0)
        run(["record", *common, "--verdict", "BLOCK", "--findings", "2", "--notes", "first fail"], 0)
        status = run(["record", *common, "--verdict", "BLOCK", "--findings", "2", "--notes", "different findings"], 0)
        if "identical-findings-2x" in status["reasons"]:
            print("selftest failed: equal finding counts treated as identical findings", file=sys.stderr)
            return 1
        status = run(["record", *common, "--verdict", "BLOCK", "--findings", "2", "--notes", "different findings"], 0)
        if "identical-findings-2x" not in status["reasons"]:
            print("selftest failed: identical findings not detected", file=sys.stderr)
            return 1

        run(["record", *common, "--verdict", "APPROVE", "--converge", "1"], 2)
        run(["status", *common, "--converge", "1"], 2)
        run(["status", *common, "--max-cycles", "50"], 2)
        if run(["status", *common, "--converge", "2", "--max-cycles", "9"], 0)["converge"] != 2:
            print("selftest failed: the frozen converge value was not used", file=sys.stderr)
            return 1
        run(["bar", "--log", log, "--converge", "1", "--reason", "too strict", "--authorized-by", "self"], 2)
        run(["bar", "--log", log, "--converge", "1", "--reason", "x", "--authorized-by", "operator"], 2)
        change = run(["bar", "--log", log, "--converge", "3", "--reason", "single pass was wrong before",
                      "--authorized-by", "operator"], 0)
        if change["loosens_converge"] or "bar-change:" not in Path(log).read_text(encoding="utf-8"):
            print("selftest failed: a bar change must be logged in the ledger", file=sys.stderr)
            return 1

        green = run(["check", *common, "--", sys.executable, "-c", "print('VERDICT: PASS')"], 0)
        red = run(["check", *common, "--", sys.executable, "-c", "import sys; print('VERDICT: BLOCK'); sys.exit(0)"], 0)
        if green["observed"] != "PASS" or red["observed"] != "FAIL":
            print(f"selftest failed: receipts observed {green['observed']}/{red['observed']}", file=sys.stderr)
            return 1
        run(["record", *common, "--verdict", "APPROVE", "--receipt", red["receipt"]], 2)
        forged = Path(green["receipt"]).with_name("forged.json")
        forged.write_text(Path(green["receipt"]).read_text(encoding="utf-8"), encoding="utf-8")
        run(["record", *common, "--receipt", str(forged)], 2)
        for cycle in range(3):
            run(["record", *common, "--receipt", green["receipt"], "--notes", f"clean {cycle}"], 0)
        status = run(["status", *common], 0)
        if "converged" not in status["reasons"] or status["streak_basis"]["receipt"] != 3:
            print(f"selftest failed: receipt-backed convergence not detected: {status}", file=sys.stderr)
            return 1
        stdout = Path(green["receipt"]).with_suffix(".stdout")
        stdout.write_text("VERDICT: PASS (edited)\n", encoding="utf-8")
        if "converged" in run(["status", *common], 0)["reasons"]:
            print("selftest failed: a tampered receipt still converged", file=sys.stderr)
            return 1
        stdout.write_text("VERDICT: PASS\n", encoding="utf-8")
        (repo / "app.txt").write_text("v2\n", encoding="utf-8")
        status = run(["status", *common], 0)
        if "converged" in status["reasons"] or not status["evidence_problems"]:
            print("selftest failed: a pass recorded before the worktree changed still converged", file=sys.stderr)
            return 1
        run(["record", *common, "--receipt", green["receipt"]], 2)

    for cell, want in (("2", 2), ("2+1", 3), ("S5", 1), ("B1,B2", 2),
                       ("a,b,c", 3), ("a,b", 2), ("a", 1), ("none", 0), ("", 0)):
        if finding_count(cell) != want:
            print(f"selftest failed: finding_count({cell!r}) = {finding_count(cell)}, want {want}",
                  file=sys.stderr)
            return 1

    def synth_rows(counts, verdict="FAIL"):
        return [
            Row(cycle=i + 1, verdict=verdict, findings=str(c), commits="0",
                loc_delta=0, tests="pass", notes="synthetic")
            for i, c in enumerate(counts)
        ]

    churn = analyze(synth_rows([5, 2, 1, 3, 2, 1]), converge=2, max_cycles=None,
                    baseline_diff=None, current_diff=None)
    if "findings-churning-6x" not in churn["reasons"]:
        print("selftest failed: churn oscillation not detected", file=sys.stderr)
        return 1
    improving = analyze(synth_rows([9, 6, 7, 4, 5, 2]), converge=2, max_cycles=None,
                        baseline_diff=None, current_diff=None)
    if "findings-churning-6x" in improving["reasons"]:
        print("selftest failed: churn false-positive on improving trend", file=sys.stderr)
        return 1
    print("loopctl_selftest_ok")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage loop ledgers and stop checks.")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="create a loop log and freeze its bar")
    init.add_argument("--log", required=True)
    init.add_argument("--loop", default="Convergence Loop")
    init.add_argument("--branch")
    init.add_argument("--base")
    init.add_argument("--test", default="auto")
    init.add_argument("--converge", type=int, default=1)
    init.add_argument("--max-cycles", type=int)
    init.add_argument("--notes", default="created by loopctl")
    init.add_argument("--force", action="store_true")
    init.set_defaults(func=cmd_init)

    bar = sub.add_parser("bar", help="change the frozen bar: logged, with a reason and a named human")
    bar.add_argument("--log", required=True)
    bar.add_argument("--converge", type=int)
    bar.add_argument("--max-cycles", type=int, help="0 removes the cap")
    bar.add_argument("--reason", required=True)
    bar.add_argument("--authorized-by", required=True)
    bar.set_defaults(func=cmd_bar)

    check = sub.add_parser("check", help="run the bound check and write a receipt")
    check.add_argument("--log", required=True)
    check.add_argument("--repo", default=".")
    check.add_argument("--timeout", type=float, default=3600)
    check.add_argument("argv", nargs=argparse.REMAINDER)
    check.set_defaults(func=cmd_check)

    record = sub.add_parser("record", help="append one cycle row")
    record.add_argument("--log", required=True)
    record.add_argument("--repo", default=".")
    record.add_argument("--cycle", type=int)
    record.add_argument("--verdict", help="required unless --receipt supplies it")
    record.add_argument("--receipt", help="a receipt from `check`; the verdict must agree with it")
    record.add_argument("--findings", default="0")
    record.add_argument("--commits", default="0")
    record.add_argument("--loc-delta", type=int, default=0)
    record.add_argument("--tests", choices=sorted(TEST_STATES), default="unknown")
    record.add_argument("--notes", default="")
    record.add_argument("--converge", type=int, help="must equal the frozen value when given")
    record.add_argument("--max-cycles", type=int, help="must equal the frozen value when given")
    record.set_defaults(func=cmd_record)

    status = sub.add_parser("status", help="summarize streak and stop signals")
    status.add_argument("--log", required=True)
    status.add_argument("--repo", default=".")
    status.add_argument("--converge", type=int, help="must equal the frozen value when given")
    status.add_argument("--max-cycles", type=int, help="must equal the frozen value when given")
    status.add_argument("--baseline-diff-lines", type=int)
    status.add_argument("--current-diff-lines", type=int)
    status.add_argument("--exit-stop", action="store_true")
    status.set_defaults(func=cmd_status)

    selftest = sub.add_parser("selftest", help="run built-in smoke tests")
    selftest.set_defaults(func=cmd_selftest)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
