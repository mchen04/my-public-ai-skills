#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter, OrderedDict
from pathlib import Path

DESCRIPTION = """Deterministic review inputs and the candidate ledger.

  scope   resolve the review range and print the surface a reviewer must cover
  risk    rank changed files by risk class and propose review dimensions
  ci      report the merge gate: which legs are green, pending, failing, or skipped
  ledger  init / round / record / judge / ci / status / verdict for the candidate ledger
"""

RISK_PATTERNS: "OrderedDict[str, tuple[str, str]]" = OrderedDict(
    [
        ("migration", (r"(^|/)(migrations?|db/migrations?)/|\.sql$", "schema/data migration")),
        ("authz", (r"auth|permission|role|rbac|policy|middleware|session|token|scope", "authn/authz boundary")),
        ("money", (r"invoice|payment|payout|billing|ledger|currency|price|tax|amount", "money arithmetic")),
        ("tenancy", (r"tenant|workspace|org(anization)?|account_id", "tenant isolation")),
        ("concurrency", (r"lock|lease|queue|worker|scheduler|cron|job|transaction|atomic", "concurrency/lifecycle")),
        ("external_io", (r"webhook|http|fetch|client|integration|slack|gmail|okta|s3|upload", "external I/O + SSRF")),
        ("secrets", (r"secret|credential|\.env|key|crypt", "secret handling")),
        ("api_surface", (r"(^|/)(api|routes?|server/api|endpoints?)/", "API surface/contract")),
        ("ci", (r"(^|/)\.github/workflows/|Dockerfile|compose\.ya?ml|fly\.toml", "deploy/CI gate")),
        ("ui", (r"\.(vue|tsx|jsx|svelte)$|(^|/)(components?|pages?|app)/", "user-visible behavior")),
        ("tests", (r"(^|/)(tests?|__tests__|spec)/|\.(test|spec)\.[a-z]+$", "test quality")),
    ]
)

SEVERITIES = ("blocker", "material", "minor", "nit", "none")
GATING = ("blocker", "material")
STATES = ("survived", "refuted", "unverified", "fixed")
CI_STATES = ("green", "red", "pending", "none")
ROUND_CAP = 3
MIN_JUDGE_SCORE = 4
CITATION = re.compile(r"[\w./@-]*[A-Za-z][\w./@-]*:\d+")


class RangeError(Exception):
    pass


class LedgerError(Exception):
    pass


def run(cmd: list[str], cwd: str | None = None) -> str:
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def rev_exists(ref: str) -> bool:
    return bool(run(["git", "rev-parse", "--verify", f"{ref}^{{commit}}"]))


def default_base_candidates() -> tuple[str, ...]:
    remote_head = run(["git", "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD"])
    preferred = (remote_head.removeprefix("refs/remotes/"),) if remote_head else ()
    return (*preferred, "origin/main", "origin/master")


def resolve_range(base: str | None, head: str | None) -> tuple[str, str, str]:
    if head and not rev_exists(head):
        raise RangeError(f"--head {head!r} is not a commit in this repository")
    head = head or run(["git", "rev-parse", "HEAD"])
    if not head:
        raise RangeError("cannot resolve HEAD (empty repository or detached with no commits)")
    if base:
        if not rev_exists(base):
            raise RangeError(f"--base {base!r} is not a commit in this repository")
        return base, head, "explicit"
    for candidate in default_base_candidates():
        if rev_exists(candidate):
            merge_base = run(["git", "merge-base", candidate, head])
            if merge_base:
                return merge_base, head, f"merge-base with {candidate}"
    fallback = run(["git", "rev-parse", "HEAD~1"])
    if not fallback:
        raise RangeError("no upstream branch found and HEAD has no parent; pass --base explicitly")
    return fallback, head, "GUESSED HEAD~1 (no upstream found) — pass --base if this is wrong"


def parse_numstat(out: str) -> list[tuple[int, int, str]]:
    rows: list[tuple[int, int, str]] = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        added = 0 if parts[0] == "-" else int(parts[0])
        removed = 0 if parts[1] == "-" else int(parts[1])
        rows.append((added, removed, parts[2]))
    return rows


def untracked_files() -> list[tuple[int, int, str]]:
    listing = run(["git", "ls-files", "--others", "--exclude-standard"])
    rows: list[tuple[int, int, str]] = []
    for path in listing.splitlines():
        try:
            with open(path, "rb") as handle:
                added = handle.read().count(b"\n")
        except OSError:
            added = 0
        rows.append((added, 0, path))
    return rows


def changed_files(base: str, head: str, worktree: bool = False) -> list[tuple[int, int, str]]:
    if not worktree:
        return parse_numstat(run(["git", "diff", "--numstat", f"{base}...{head}"]))
    merge_base = run(["git", "merge-base", base, "HEAD"]) or base
    rows = {path: (add, rem) for add, rem, path in parse_numstat(
        run(["git", "diff", "--numstat", merge_base])
    )}
    for add, rem, path in untracked_files():
        rows.setdefault(path, (add, rem))
    return [(add, rem, path) for path, (add, rem) in sorted(rows.items())]


def classify(path: str) -> list[str]:
    return [name for name, (pattern, _) in RISK_PATTERNS.items() if re.search(pattern, path, re.I)]


def cmd_scope(args: argparse.Namespace) -> int:
    base, head, how = resolve_range(args.base, args.head)
    rows = changed_files(base, head, args.worktree)
    if not rows:
        scope_note = "working tree" if args.worktree else head
        print(f"No changes between {base} and {scope_note}.")
        return 1
    added = sum(r[0] for r in rows)
    removed = sum(r[1] for r in rows)
    commits = run(["git", "rev-list", "--count", f"{base}..{head}"]) or "?"
    print(f"range     {base}...{'working tree' if args.worktree else head}")
    print(f"base from {how}")
    print(f"surface   {len(rows)} files, +{added}/-{removed}, {commits} commits")
    classes = Counter()
    for _, _, path in rows:
        for name in classify(path):
            classes[name] += 1
    if classes:
        summary = ", ".join(f"{name} {count}" for name, count in classes.most_common())
        print(f"risk      {summary}")
    print()
    print("commits:")
    log = run(["git", "log", "--oneline", "--no-decorate", f"{base}..{head}"])
    for line in log.splitlines()[: args.max_commits]:
        print(f"  {line}")
    return 0


def risk_weight(names: list[str]) -> int:
    order = list(RISK_PATTERNS)
    return sum(len(order) - order.index(name) for name in names)


def cmd_risk(args: argparse.Namespace) -> int:
    base, head, how = resolve_range(args.base, args.head)
    if how.startswith("GUESSED"):
        print(f"warning: {how}")
    rows = changed_files(base, head, args.worktree)
    if not rows:
        print("No changes to rank.")
        return 1
    scored = [(risk_weight(classify(path)), add + rem, path, classify(path)) for add, rem, path in rows]
    scored.sort(key=lambda row: (row[0], row[1]), reverse=True)

    print("Highest-risk files (review these by execution, not by reading):")
    for _, churn, path, names in scored[: args.top]:
        tags = ",".join(names) or "-"
        print(f"  {churn:>6}  {path}  [{tags}]")

    present = [n for n in RISK_PATTERNS if any(n in s[3] for s in scored)]
    print()
    if not present:
        print("Proposed dimensions (0): no risk class matched; pick them from the diff by hand.")
        return 0
    chosen, deferred = present[: args.dimensions], present[args.dimensions :]
    print(f"Proposed dimensions ({len(chosen)}):")
    for name in chosen:
        print(f"  - {name}: {RISK_PATTERNS[name][1]}")
    if deferred:
        print(f"Not proposed (fold in only if the diff justifies it): {', '.join(deferred)}")
    return 0


def cmd_ci(args: argparse.Namespace) -> int:
    target = args.pr or ""
    raw = run(["gh", "pr", "checks", target, "--json", "name,bucket,state"] if target
              else ["gh", "pr", "checks", "--json", "name,bucket,state"])
    if not raw:
        print("No CI data (no PR, no gh auth, or no checks configured).")
        return 1
    try:
        checks = json.loads(raw)
    except json.JSONDecodeError:
        print("Could not parse gh output.")
        return 1
    buckets = Counter(c.get("bucket", "unknown") for c in checks)
    print("merge gate: " + ", ".join(f"{k} {v}" for k, v in buckets.most_common()))
    for check in checks:
        if check.get("bucket") not in ("pass", "skipping"):
            print(f"  {check.get('bucket', '?'):<9} {check.get('name', '?')}")
    if buckets.get("pending"):
        print()
        print("Pending legs exist — a single green leg is not the gate. Name what is still pending.")
    if buckets.get("skipping"):
        print()
        print("Skipped legs: confirm path filters did not skip the suite that covers this change.")
    return 0


def read_ledger(path: Path) -> list[dict]:
    if not path.exists():
        raise LedgerError(f"missing ledger {path}; run `ledger init` first")
    events = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            raise LedgerError(f"{path}:{number} is not a ledger line; start over with `ledger init --fresh`") from None
    if not events or events[0].get("type") != "round":
        raise LedgerError(f"{path} has no opening round; start over with `ledger init --fresh`")
    return events


def append_event(path: Path, event: dict) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")


def current_round(events: list[dict]) -> dict:
    return [e for e in events if e["type"] == "round"][-1]


def candidate_rows(events: list[dict]) -> list[dict]:
    return [e for e in events if e["type"] == "candidate"]


def latest_rows(events: list[dict]) -> "OrderedDict[str, dict]":
    latest: "OrderedDict[str, dict]" = OrderedDict()
    for row in candidate_rows(events):
        latest[row["id"]] = row
    return latest


def file_key(file: str) -> str:
    return re.sub(r":\d+(-\d+)?(,\d+(-\d+)?)*$", "", file.strip()).removeprefix("./")


def mechanism_key(mechanism: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", mechanism.lower()))


def resolve_head(head: str | None) -> str:
    resolved = head or run(["git", "rev-parse", "HEAD"])
    if not resolved:
        raise LedgerError("pass --head: no git HEAD here to default to")
    return resolved


def independent(row: dict) -> bool:
    return bool(row.get("refuter")) and row.get("refuter") != row.get("hunter")


def open_ids(events: list[dict]) -> list[str]:
    return [cid for cid, row in latest_rows(events).items() if row["state"] in ("survived", "unverified")]


def ledger_init(path: Path, args: argparse.Namespace) -> int:
    if path.exists() and path.read_text(encoding="utf-8").strip() and not args.fresh:
        try:
            last = current_round(read_ledger(path))
            where = f"round {last['round']} at head {last['head']}"
        except LedgerError:
            where = "an unreadable ledger"
        raise LedgerError(f"{path} already holds {where}; start the next round with `ledger round`, "
                          "or pass --fresh to discard it for an unrelated review")
    head = resolve_head(args.head)
    cap = args.round_cap if args.round_cap is not None else ROUND_CAP
    if cap < 1:
        raise LedgerError("--round-cap must be positive")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"type": "round", "round": 1, "head": head, "round_cap": cap, "zero_open": args.zero_open}, sort_keys=True) + "\n", encoding="utf-8")
    print(f"initialized {path}: round 1 of {cap} at head {head}")
    return 0


def ledger_round(path: Path, events: list[dict], args: argparse.Namespace) -> int:
    last = current_round(events)
    head = resolve_head(args.head)
    cap = args.round_cap if args.round_cap is not None else last.get("round_cap", ROUND_CAP)
    if cap < 1:
        raise LedgerError("--round-cap must be positive")
    if last["round"] >= cap:
        raise LedgerError(f"{cap}-round cap reached: report the open findings with `ledger verdict` and stop")
    number = last["round"] + 1
    append_event(path, {"type": "round", "round": number, "head": head, "round_cap": cap, "zero_open": args.zero_open or last.get("zero_open", False)})
    still_open = open_ids(events)
    print(f"round {number} of {cap} at head {head}")
    print("open from earlier rounds (stay open until a fix is grounded): " + (", ".join(still_open) or "none"))
    return 0


def record_problems(args: argparse.Namespace) -> list[str]:
    problems = [f"--{name} is required to record" for name in ("dimension", "file", "mechanism", "severity", "state", "hunter")
                if not getattr(args, name)]
    if problems:
        return problems
    if args.severity not in SEVERITIES:
        problems.append(f"--severity must be one of {', '.join(SEVERITIES)}")
    if args.state not in STATES:
        problems.append(f"--state must be one of {', '.join(STATES)}")
    if args.refuter and args.refuter == args.hunter:
        problems.append("--refuter must be a different agent from --hunter: nobody refutes their own candidate")
    if args.state in ("refuted", "fixed") and not args.refuter:
        problems.append(f"a {args.state} row needs --refuter: the independent agent that "
                        + ("killed it" if args.state == "refuted" else "grounded the fix"))
    if args.state == "refuted" and args.severity == "none":
        problems.append("a refuted row keeps the severity the candidate claimed; --severity none is not allowed")
    evidence = args.evidence or ""
    if args.state == "refuted" and args.severity in GATING and not CITATION.search(evidence):
        problems.append(f"refuting a {args.severity} candidate needs grounded --evidence citing the file:line that kills it")
    if args.state == "fixed" and not CITATION.search(evidence):
        problems.append("a fixed row needs grounded --evidence citing the file:line of the fix at the new head")
    return problems


def ledger_record(path: Path, events: list[dict], args: argparse.Namespace) -> int:
    problems = record_problems(args)
    if problems:
        raise LedgerError("\n".join(problems))
    rows = candidate_rows(events)
    latest = latest_rows(events)
    key = (file_key(args.file), mechanism_key(args.mechanism))
    if args.id:
        if args.id not in latest:
            raise LedgerError(f"--id {args.id} is not in this ledger; omit --id to open a new candidate")
        cid = args.id
    else:
        cid = next((row["id"] for row in reversed(rows)
                    if (file_key(row["file"]), mechanism_key(row["mechanism"])) == key), None)
    prior = latest.get(cid) if cid else None
    if prior is None and args.state == "fixed":
        raise LedgerError("nothing open matches this file and mechanism; pass --id of the finding the fix closes")
    evidence = (args.evidence or "").strip()
    if prior and prior["state"] == "refuted" and args.state != "refuted":
        earlier = {row.get("evidence", "") for row in rows if row["id"] == cid}
        if not evidence or evidence in earlier:
            raise LedgerError(f"{cid} was refuted in round {prior['round']}; it returns only with new --evidence")
    if prior and (prior["state"], prior["severity"], prior.get("evidence", "")) == (args.state, args.severity, evidence):
        print(f"{cid} unchanged since round {prior['round']}; not recorded again")
        return 0
    cid = cid or f"C{len(latest) + 1}"
    row = {"type": "candidate", "id": cid, "round": current_round(events)["round"], "dimension": args.dimension,
           "file": args.file, "mechanism": args.mechanism, "severity": args.severity, "state": args.state,
           "hunter": args.hunter, "refuter": args.refuter or "", "evidence": evidence}
    append_event(path, row)
    print(f"recorded {cid} (round {row['round']}, {args.severity}, {args.state})")
    return 0


def ledger_judge(path: Path, events: list[dict], args: argparse.Namespace) -> int:
    if not args.by:
        raise LedgerError("--by is required: the agent that ran the missed-defect pass")
    number = current_round(events)["round"]
    review_agents = {name for row in candidate_rows(events) if row["round"] == number and row["dimension"] != "judge"
                     for name in (row["hunter"], row.get("refuter"))}
    if args.by in review_agents:
        raise LedgerError(f"{args.by} hunted or refuted in round {number}; the judge pass needs an agent that did neither")
    if args.score is not None and not 1 <= args.score <= 5:
        raise LedgerError("--score is the lowest rubric score, 1 to 5")
    append_event(path, {"type": "judge", "round": number, "by": args.by, "found": args.found, "score": args.score})
    print(f"judge pass recorded for round {number} ({args.found} missed defect(s) raised)")
    return 0


def ledger_ci(path: Path, events: list[dict], args: argparse.Namespace) -> int:
    if args.state not in CI_STATES:
        raise LedgerError(f"ledger ci --state must be one of {', '.join(CI_STATES)}")
    if not (args.evidence or "").strip():
        raise LedgerError("ledger ci needs --evidence: the run, its head, and its pass counts")
    number = current_round(events)["round"]
    append_event(path, {"type": "ci", "round": number, "state": args.state, "evidence": args.evidence.strip()})
    print(f"CI {args.state} recorded for round {number}")
    return 0


def counts_line(latest: "OrderedDict[str, dict]") -> str:
    states = Counter(row["state"] for row in latest.values())
    survived = Counter(row["severity"] for row in latest.values() if row["state"] == "survived")
    parts = [f"{survived[s]} {s}" for s in ("blocker", "material", "minor")]
    parts += [f"{survived[s]} {s}" for s in ("nit", "none") if survived[s]]
    line = (f"{len(latest)} candidates, {states['refuted']} refuted, {states['survived']} survived "
            f"({', '.join(parts)})")
    for extra in ("fixed", "unverified"):
        if states[extra]:
            line += f", {states[extra]} {extra}"
    return line


def verdict_lines(events: list[dict]) -> tuple[list[str], bool]:
    this_round = current_round(events)
    number = this_round["round"]
    latest = latest_rows(events)
    worst: dict[str, int] = {}
    for row in candidate_rows(events):
        rank = SEVERITIES.index(row["severity"])
        worst[row["id"]] = min(worst.get(row["id"], rank), rank)
    gating, unsettled, reasons = [], [], []
    for cid, row in latest.items():
        if (SEVERITIES[worst[cid]] in GATING or this_round.get("zero_open", False)) and not independent(row):
            reasons.append(f"{cid} ({SEVERITIES[worst[cid]]}) has no independent refuter")
        if row["severity"] not in GATING and not this_round.get("zero_open", False):
            continue
        summary = f"{cid} {row['severity']} {row['file']} {row['mechanism']}"
        if row["state"] == "survived" and independent(row):
            gating.append(summary)
        elif row["state"] == "unverified":
            unsettled.append(summary)
    judged = [e for e in events if e["type"] == "judge" and e["round"] == number]
    if not judged:
        reasons.append(f"judge missed-defect pass not recorded for round {number}")
    ci = [e for e in events if e["type"] == "ci" and e["round"] == number]
    if not ci or ci[-1]["state"] != "green":
        reasons.append(f"CI not recorded green for round {number}" + (f" ({ci[-1]['state']})" if ci else ""))
    lines = [f"round {number} of {this_round.get('round_cap', ROUND_CAP)}, head {this_round['head']}", counts_line(latest)]
    lines += [f"gating: {item}" for item in gating] or ["gating: none"]
    lines += [f"unsettled: {item}" for item in unsettled]
    lines += [f"not approvable: {reason}" for reason in reasons]
    approve = not (gating or unsettled or reasons)
    weak = [e["score"] for e in judged if e.get("score") is not None and e["score"] < MIN_JUDGE_SCORE]
    if approve and weak:
        lines.append(f"comment only: judge score {min(weak)} is below {MIN_JUDGE_SCORE}")
    publish = "approve" if approve and not weak else "request changes" if gating else "comment"
    lines += [f"publish: {publish}", f"VERDICT: {'APPROVE' if approve else 'BLOCK'}"]
    return lines, approve


def ledger_status(events: list[dict]) -> int:
    latest = latest_rows(events)
    print("| id | round | severity | state | file | mechanism | hunter | refuter |")
    print("|---|---|---|---|---|---|---|---|")
    for cid, row in latest.items():
        cells = [cid, str(row["round"]), row["severity"], row["state"], row["file"], row["mechanism"],
                 row["hunter"], row.get("refuter") or "-"]
        print("| " + " | ".join(c.replace("|", "\\|").replace("\n", " ") for c in cells) + " |")
    print()
    print(counts_line(latest))
    return 0


def cmd_ledger(args: argparse.Namespace) -> int:
    path = Path(args.log).expanduser()
    if args.action == "init":
        return ledger_init(path, args)
    events = read_ledger(path)
    if args.action == "round":
        return ledger_round(path, events, args)
    if args.action == "record":
        return ledger_record(path, events, args)
    if args.action == "judge":
        return ledger_judge(path, events, args)
    if args.action == "ci":
        return ledger_ci(path, events, args)
    if args.action == "status":
        return ledger_status(events)
    lines, _ = verdict_lines(events)
    print("\n".join(lines))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=DESCRIPTION, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    scope = sub.add_parser("scope", help="resolve range and print the review surface")
    scope.add_argument("--base")
    scope.add_argument("--head")
    scope.add_argument("--max-commits", type=int, default=40)
    scope.add_argument("--worktree", action="store_true", help="include staged, unstaged, and untracked work")
    scope.set_defaults(func=cmd_scope)

    risk = sub.add_parser("risk", help="rank changed files and propose dimensions")
    risk.add_argument("--base")
    risk.add_argument("--head")
    risk.add_argument("--top", type=int, default=25)
    risk.add_argument("--worktree", action="store_true", help="include staged, unstaged, and untracked work")
    risk.add_argument("--dimensions", type=int, default=5, help="cap on proposed dimensions")
    risk.set_defaults(func=cmd_risk)

    ci = sub.add_parser("ci", help="report the merge gate")
    ci.add_argument("--pr", default="")
    ci.set_defaults(func=cmd_ci)

    ledger = sub.add_parser("ledger", help="candidate ledger")
    ledger.add_argument("action", choices=["init", "round", "record", "judge", "ci", "status", "verdict"])
    ledger.add_argument("--log", required=True)
    ledger.add_argument("--round-cap", type=int, help="init/round: explicit operator-authorized cap; retained in subsequent rounds")
    ledger.add_argument("--zero-open", action="store_true", help="init/round: require every candidate to be closed; retained in subsequent rounds")
    ledger.add_argument("--head", help="init/round: the reviewed commit (default: git HEAD)")
    ledger.add_argument("--fresh", action="store_true", help="init: discard an existing ledger")
    ledger.add_argument("--id", help="record: reuse this candidate id")
    ledger.add_argument("--dimension")
    ledger.add_argument("--file", help="record: path:line the candidate is about")
    ledger.add_argument("--mechanism", help="record: one line naming how it fails")
    ledger.add_argument("--severity", help=f"record: one of {', '.join(SEVERITIES)}; refuted rows keep the claimed one")
    ledger.add_argument("--state", help=f"record: one of {', '.join(STATES)}; ci: one of {', '.join(CI_STATES)}")
    ledger.add_argument("--hunter", help="record: the agent that raised the candidate")
    ledger.add_argument("--refuter", help="record: the separate agent that tried to kill it")
    ledger.add_argument("--evidence")
    ledger.add_argument("--by", help="judge: the agent that ran the missed-defect pass")
    ledger.add_argument("--found", type=int, default=0, help="judge: missed defects it raised")
    ledger.add_argument("--score", type=int, help="judge: the lowest rubric score it gave, 1 to 5")
    ledger.set_defaults(func=cmd_ledger)

    args = parser.parse_args()
    if not run(["git", "rev-parse", "--git-dir"]) and args.command in ("scope", "risk"):
        print("not a git repository", file=sys.stderr)
        return 1
    try:
        return args.func(args)
    except RangeError as error:
        print(f"{error}", file=sys.stderr)
        return 2
    except LedgerError as error:
        print(f"{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
