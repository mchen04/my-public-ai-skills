#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ledgerio  # noqa: E402
from loopctl import FAIL_VERDICTS, PASS_VERDICTS  # noqa: E402

FLOW_STATES = {"pass", "fail", "unverified"}
PASSING = {"pass"}
MAX_FLOWS = 200
MAX_CELL = 200

DEMO_RE = re.compile(r"^fail-demo:\s*(.+)$", re.M)
BASE_RE = re.compile(r"^base:\s*(\S+)", re.M)


def git_output(args: list[str], default: str) -> str:
    try:
        out = subprocess.check_output(["git", *args], text=True, stderr=subprocess.DEVNULL)
    except Exception:
        return default
    return out.strip() or default


def clean_cell(value: str) -> str:
    text = " ".join((value or "").split()).replace("|", "/")
    return text[:MAX_CELL] if text else "-"


def read_rows(path: Path) -> list[tuple[str, str, str, str, str]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 3:
            continue
        flow, state, evidence = cells[:3]
        if not flow or set(flow) <= set("-: "):
            continue
        if (flow, state) == ("flow", "state"):
            continue
        revision = cells[3] if len(cells) > 3 else ""
        basis = cells[4] if len(cells) > 4 else "asserted"
        rows.append((flow, state, evidence, revision, basis))
    return rows


def demo_state(path: Path) -> str:
    match = DEMO_RE.search(path.read_text(encoding="utf-8"))
    return match.group(1).strip() if match else "not-run"


def require_inventory(path: Path) -> Path:
    if not path.is_file():
        print(
            f"no inventory at {path}; run `flowctl.py register` at the pre-fix head first",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return path


def write_inventory(path: Path, header: list[str], rows: list[tuple[str, str, str, str, str]]) -> None:
    body = header + ["", "| flow | state | evidence | revision | basis |", "|---|---|---|---|---|"]
    body += [f"| {f} | {s} | {e} | {r or '-'} | {b} |" for f, s, e, r, b in rows]
    ledgerio.atomic_write(path, "\n".join(body) + "\n")


def current_revision(args: argparse.Namespace) -> dict | None:
    return ledgerio.worktree_revision(Path(getattr(args, "repo", ".") or "."))


def evidence_basis(evidence: str, state: str, repo: Path) -> tuple[str, list[str]]:
    path = Path(evidence).expanduser() if evidence else None
    if path is None or not ledgerio.looks_like_receipt(path):
        return "asserted", []
    expect = {"pass": "PASS", "fail": "FAIL"}.get(state)
    problems = ledgerio.receipt_problems(path, repo=repo, expect=expect, require_fresh=state == "pass")
    return ledgerio.receipt_tag(path), problems


def header_lines(path: Path) -> list[str]:
    out: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("| flow ") or line.startswith("|---"):
            break
        out.append(line)
    while out and not out[-1].strip():
        out.pop()
    return out


def set_demo(header: list[str], state: str) -> list[str]:
    replaced = False
    out = []
    for line in header:
        if line.startswith("fail-demo:"):
            out.append(f"fail-demo: {state}")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.append(f"fail-demo: {state}")
    return out


def cmd_register(args: argparse.Namespace) -> int:
    path = Path(args.inventory)
    flows = [clean_cell(f) for f in args.flow if f.strip()]
    if not flows:
        print("register needs at least one --flow; an empty inventory cannot gate", file=sys.stderr)
        return 2
    if len(flows) > MAX_FLOWS:
        print(f"{len(flows)} flows exceeds the {MAX_FLOWS} cap; split the inventory", file=sys.stderr)
        return 2
    if len(set(flows)) != len(flows):
        dupes = sorted({f for f in flows if flows.count(f) > 1})
        print(f"duplicate flow names: {dupes}; each flow needs a distinct name", file=sys.stderr)
        return 2
    if path.exists() and not args.force:
        print(
            f"{path} already exists; re-registering mid-wave would let the fix reshape its own bar. "
            "Pass --force only when starting a new wave at a new pre-fix head.",
            file=sys.stderr,
        )
        return 2

    branch = args.branch or git_output(["rev-parse", "--abbrev-ref", "HEAD"], "unknown")
    base = args.base or git_output(["rev-parse", "HEAD"], "unknown")
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    header = [
        f"# Flow inventory - {branch} ({date})",
        "",
        f"base: {base} | flows: {len(flows)}",
        "fail-demo: not-run",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with ledgerio.locked(path):
        write_inventory(path, header, [(f, "unverified", "-", "", "asserted") for f in flows])
    print(json.dumps({"inventory": str(path), "base": base, "flows": len(flows)}, sort_keys=True))
    return 0


def cmd_record(args: argparse.Namespace) -> int:
    path = require_inventory(Path(args.inventory))
    if args.state not in FLOW_STATES:
        print(f"invalid state {args.state!r}; use one of {sorted(FLOW_STATES)}", file=sys.stderr)
        return 2

    flow = clean_cell(args.flow)
    if args.state in PASSING and not args.evidence:
        print(
            f"recording {flow!r} as pass needs --evidence naming the proof "
            "(screenshot path, command, or transcript); a pass with no evidence is a claim",
            file=sys.stderr,
        )
        return 2
    basis, problems = evidence_basis(args.evidence or "", args.state, Path(args.repo))
    if problems:
        print("\n".join(f"record: {p}" for p in problems), file=sys.stderr)
        return 2
    revision = current_revision(args)
    with ledgerio.locked(path):
        rows = read_rows(path)
        names = [f for f, *_ in rows]
        if flow not in names:
            print(
                f"{flow!r} was not registered at the pre-fix head. Registered flows: {names}. "
                "A flow discovered while fixing is one the fix already satisfies — register it in the "
                "next wave, or re-register the inventory at a new pre-fix head with --force.",
                file=sys.stderr,
            )
            return 2
        evidence = clean_cell(args.evidence) if args.evidence else "-"
        stamp = revision["id"] if revision else "none"
        rows = [(flow, args.state, evidence, stamp, basis) if row[0] == flow else row for row in rows]
        write_inventory(path, header_lines(path), rows)
    print(json.dumps({"flow": flow, "state": args.state, "revision": stamp, "basis": basis}, sort_keys=True))
    return 0


def cmd_fail_demo(args: argparse.Namespace) -> int:
    path = require_inventory(Path(args.inventory))
    flow = clean_cell(args.flow)
    if args.observed != "red":
        print(
            f"fail-demo observed {args.observed!r}, not 'red'. The planted break did not turn the "
            "check red, so the check cannot detect that break — repair the check, not the demo.",
            file=sys.stderr,
        )
        return 2
    basis = "asserted"
    if args.evidence:
        receipt = Path(args.evidence).expanduser()
        if not ledgerio.looks_like_receipt(receipt):
            print("fail-demo: --evidence must be a receipt from `flowctl.py check`", file=sys.stderr)
            return 2
        problems = ledgerio.receipt_problems(receipt, repo=Path(args.repo), expect="FAIL")
        if problems:
            print("\n".join(f"fail-demo: {p}" for p in problems), file=sys.stderr)
            return 2
        basis = ledgerio.receipt_tag(receipt)
    with ledgerio.locked(path):
        names = [f for f, *_ in read_rows(path)]
        if flow not in names:
            print(f"{flow!r} is not a registered flow; plant the break in one of {names}", file=sys.stderr)
            return 2
        header = set_demo(header_lines(path), f"{flow} observed red ({basis})")
        write_inventory(path, header, read_rows(path))
    print(json.dumps({"fail_demo": flow, "observed": "red", "basis": basis}, sort_keys=True))
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    argv = args.argv[1:] if args.argv[:1] == ["--"] else args.argv
    out_dir = Path(args.inventory).with_name(Path(args.inventory).name + ".receipts")
    try:
        receipt_path, receipt = ledgerio.run_check(argv, repo=Path(args.repo), out_dir=out_dir, observer="flowctl",
                                                   passing=PASS_VERDICTS, failing=FAIL_VERDICTS, timeout=args.timeout)
    except ValueError as error:
        print(f"check: {error}", file=sys.stderr)
        return 2
    print(json.dumps({"receipt": str(receipt_path), "observed": receipt["observed"], "exit": receipt["exit"],
                      "revision": receipt["revision"]["id"], "stable": receipt["stable"]}, sort_keys=True))
    return 0


def cmd_reset(args: argparse.Namespace) -> int:
    path = require_inventory(Path(args.inventory))
    rows = read_rows(path)
    if not rows:
        print(f"{path} registers no flows; nothing to reset", file=sys.stderr)
        return 2
    with ledgerio.locked(path):
        rows = read_rows(path)
        write_inventory(path, header_lines(path), [(r[0], "unverified", "-", "", "asserted") for r in rows])
    print(json.dumps({"reset": len(rows)}, sort_keys=True))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    path = require_inventory(Path(args.inventory))
    rows = read_rows(path)
    demo = demo_state(path)
    current = current_revision(args)

    passed = [r[0] for r in rows if r[1] in PASSING]
    failed = [r[0] for r in rows if r[1] == "fail"]
    unverified = [r[0] for r in rows if r[1] == "unverified"]
    stale, tampered = [], []
    for flow, state, evidence, revision, basis in rows:
        if state not in PASSING:
            continue
        if current is not None and revision != current["id"]:
            stale.append(flow)
        if basis.startswith("receipt:"):
            problems = ledgerio.receipt_problems(Path(evidence).expanduser(), repo=None, expect="PASS")
            if problems:
                tampered.append(f"{flow}: {problems[0]}")

    blockers: list[str] = []
    if failed:
        blockers.append(f"{len(failed)} flow(s) failed: {failed[:10]}")
    if unverified:
        blockers.append(f"{len(unverified)} flow(s) never exercised: {unverified[:10]}")
    if stale:
        blockers.append(f"{len(stale)} pass(es) observed at another revision than the worktree's {current['id']}: {stale[:10]}")
    blockers += tampered[:10]
    if demo == "not-run":
        blockers.append("no fail-demo: the check has never been shown able to turn red")

    verdict = "PASS" if not blockers else "FAIL"
    base_match = BASE_RE.search(path.read_text(encoding="utf-8"))
    summary = {
        "inventory": str(path),
        "base": base_match.group(1) if base_match else "unknown",
        "flows": len(rows),
        "passed": len(passed),
        "failed": len(failed),
        "unverified": len(unverified),
        "fail_demo": demo,
        "revision": current["id"] if current else None,
        "basis": {"receipt": sum(1 for r in rows if r[1] in PASSING and r[4].startswith("receipt:")),
                  "asserted": sum(1 for r in rows if r[1] in PASSING and not r[4].startswith("receipt:"))},
        "blockers": blockers,
        "verdict": verdict,
    }
    print(json.dumps(summary, sort_keys=True))
    for blocker in blockers:
        print(f"  - {blocker}")
    print(f"VERDICT: {verdict}")
    return 0


def cmd_selftest(_args: argparse.Namespace) -> int:
    import tempfile

    def run(argv: list[str], expect: int) -> None:
        code = main(argv)
        if code != expect:
            raise SystemExit(f"selftest: {argv} exited {code}, want {expect}")

    def verdict_of(inv: Path) -> str:
        import contextlib
        import io

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cmd_status(argparse.Namespace(inventory=str(inv), repo=str(repo)))
        return buf.getvalue().strip().splitlines()[-1]

    with tempfile.TemporaryDirectory() as tmp:
        inv = Path(tmp) / "flows.md"
        repo = Path(tmp) / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        (repo / "app.txt").write_text("v1\n", encoding="utf-8")
        base = ["--inventory", str(inv), "--repo", str(repo)]
        reg = ["--inventory", str(inv)]

        run(["register", *reg, "--flow", "signup", "--flow", "checkout", "--base", "deadbeef"], 0)
        if verdict_of(inv) != "VERDICT: FAIL":
            raise SystemExit("selftest: a freshly registered inventory must not pass")
        names = [r[0] for r in read_rows(inv)]
        if names != ["signup", "checkout"]:
            raise SystemExit(f"selftest: table syntax parsed as flows; got {names}")

        run(["record", *base, "--flow", "invented", "--state", "pass", "--evidence", "x.png"], 2)
        run(["record", *base, "--flow", "signup", "--state", "pass"], 2)

        run(["record", *base, "--flow", "signup", "--state", "pass", "--evidence", "s.png"], 0)
        run(["record", *base, "--flow", "checkout", "--state", "pass", "--evidence", "c.png"], 0)
        if verdict_of(inv) != "VERDICT: FAIL":
            raise SystemExit("selftest: all flows green with no fail-demo must still FAIL")

        run(["fail-demo", *base, "--flow", "signup", "--observed", "green"], 2)
        run(["fail-demo", *base, "--flow", "signup", "--observed", "red"], 0)
        if verdict_of(inv) != "VERDICT: PASS":
            raise SystemExit("selftest: fully exercised inventory with a red demo must PASS")

        run(["record", *base, "--flow", "checkout", "--state", "fail"], 0)
        if verdict_of(inv) != "VERDICT: FAIL":
            raise SystemExit("selftest: a failing flow must turn the gate red")

        run(["record", *base, "--flow", "checkout", "--state", "unverified"], 0)
        if verdict_of(inv) != "VERDICT: FAIL":
            raise SystemExit("selftest: an unverified flow must never read as passing")

        run(["record", *base, "--flow", "checkout", "--state", "pass", "--evidence", "c2.png"], 0)
        if verdict_of(inv) != "VERDICT: PASS":
            raise SystemExit("selftest: re-recording both flows should pass again")
        run(["reset", *reg], 0)
        if demo_state(inv) == "not-run":
            raise SystemExit("selftest: reset must not discard the fail-demo")
        if [r[1] for r in read_rows(inv)] != ["unverified", "unverified"]:
            raise SystemExit("selftest: reset must return every flow to unverified")
        if verdict_of(inv) != "VERDICT: FAIL":
            raise SystemExit("selftest: a reset inventory must not still read as passing")

        run(["record", *base, "--flow", "signup", "--state", "pass", "--evidence", "s3.png"], 0)
        run(["record", *base, "--flow", "checkout", "--state", "pass", "--evidence", "c3.png"], 0)
        if verdict_of(inv) != "VERDICT: PASS":
            raise SystemExit("selftest: two fresh passes should pass")
        (repo / "app.txt").write_text("v2\n", encoding="utf-8")
        if verdict_of(inv) != "VERDICT: FAIL":
            raise SystemExit("selftest: a pass from before the worktree changed must not count")

        import contextlib
        import io

        def check(code: str) -> dict:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                run(["check", *base, "--", sys.executable, "-c", code], 0)
            return json.loads(buf.getvalue())

        green, red = check("print('ok')"), check("import sys; sys.exit(1)")
        run(["record", *base, "--flow", "signup", "--state", "pass", "--evidence", red["receipt"]], 2)
        run(["fail-demo", *base, "--flow", "signup", "--observed", "red", "--evidence", green["receipt"]], 2)
        run(["fail-demo", *base, "--flow", "signup", "--observed", "red", "--evidence", red["receipt"]], 0)
        run(["record", *base, "--flow", "signup", "--state", "pass", "--evidence", green["receipt"]], 0)
        run(["record", *base, "--flow", "checkout", "--state", "pass", "--evidence", "c4.png"], 0)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cmd_status(argparse.Namespace(inventory=str(inv), repo=str(repo)))
        summary = json.loads(buf.getvalue().splitlines()[0])
        if summary["verdict"] != "PASS" or summary["basis"] != {"receipt": 1, "asserted": 1}:
            raise SystemExit(f"selftest: status must separate receipts from assertions: {summary}")
        forged = Path(green["receipt"]).with_name("forged.json")
        forged.write_text(Path(green["receipt"]).read_text(encoding="utf-8"), encoding="utf-8")
        run(["record", *base, "--flow", "signup", "--state", "pass", "--evidence", str(forged)], 2)
        Path(green["receipt"]).with_suffix(".stdout").write_text("edited\n", encoding="utf-8")
        if verdict_of(inv) != "VERDICT: FAIL":
            raise SystemExit("selftest: a tampered receipt must turn the gate red")

    print("flowctl_selftest_ok (gate proven able to turn red; unverified, stale, and tampered never pass)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Workflow inventory for the review-fix loop.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    reg = sub.add_parser("register", help="seal the flow list at the pre-fix head")
    reg.add_argument("--inventory", required=True)
    reg.add_argument("--flow", action="append", default=[], required=True)
    reg.add_argument("--base")
    reg.add_argument("--branch")
    reg.add_argument("--force", action="store_true")
    reg.set_defaults(func=cmd_register)

    rec = sub.add_parser("record", help="record one flow's observed state")
    rec.add_argument("--inventory", required=True)
    rec.add_argument("--flow", required=True)
    rec.add_argument("--state", required=True, choices=sorted(FLOW_STATES))
    rec.add_argument("--evidence", help="proof path; a `check` receipt is verified and counted as machine-observed")
    rec.add_argument("--repo", default=".")
    rec.set_defaults(func=cmd_record)

    demo = sub.add_parser("fail-demo", help="record that a planted break turned the check red")
    demo.add_argument("--inventory", required=True)
    demo.add_argument("--flow", required=True)
    demo.add_argument("--observed", required=True, choices=["red", "green"])
    demo.add_argument("--evidence", help="a `check` receipt of the planted break; it must have observed FAIL")
    demo.add_argument("--repo", default=".")
    demo.set_defaults(func=cmd_fail_demo)

    chk = sub.add_parser("check", help="run a flow's check and write a receipt")
    chk.add_argument("--inventory", required=True)
    chk.add_argument("--repo", default=".")
    chk.add_argument("--timeout", type=float, default=3600)
    chk.add_argument("argv", nargs=argparse.REMAINDER)
    chk.set_defaults(func=cmd_check)

    rst = sub.add_parser("reset", help="clear observations before the next cycle")
    rst.add_argument("--inventory", required=True)
    rst.set_defaults(func=cmd_reset)

    st = sub.add_parser("status", help="print the per-flow table and the VERDICT token")
    st.add_argument("--inventory", required=True)
    st.add_argument("--repo", default=".")
    st.set_defaults(func=cmd_status)

    sub.add_parser("selftest", help="prove the gate can turn red").set_defaults(func=cmd_selftest)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
