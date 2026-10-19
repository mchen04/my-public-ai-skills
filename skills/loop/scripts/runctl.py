#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ledgerio  # noqa: E402
from loopctl import FAIL_VERDICTS, PASS_VERDICTS  # noqa: E402

SCANNER_PATH = Path(__file__).resolve().parents[2] / "safe-push" / "scripts" / "redact-secrets.py"
SCANNER_SPEC = importlib.util.spec_from_file_location("runctl_secret_scanner", SCANNER_PATH)
SCANNER = importlib.util.module_from_spec(SCANNER_SPEC)
sys.modules[SCANNER_SPEC.name] = SCANNER
try:
    SCANNER_SPEC.loader.exec_module(SCANNER)
except OSError as error:
    message = "the sibling safe-push skill must include scripts/redact-secrets.py"
    if __name__ == "__main__":
        print(f"runctl: {message}", file=sys.stderr)
        raise SystemExit(2)
    raise ImportError(message) from error

LEVELS = ("claimed", "observed", "failure-proven", "independently-verified")
DECISION_COLUMNS = ("row", "ts", "phase", "decision", "why", "rejected", "evidence", "level", "result", "supersedes")
STEP_STATES = ("pending", "done", "skipped")
STEP_HEADING_RE = re.compile(
    r"(process|workflow|how it works|steps|one cycle|pre-?flight|ship gates|pass conditions)", re.I
)
STEP_ITEM_RE = re.compile(r"^(\d+[a-z]?)\.\s+(.*\S)\s*$")
OPTIONAL_RE = re.compile(r"\(optional\)|^optionally\b|^if you |^when asked", re.I)
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")
URL_RE = re.compile(r"^https?://\S+$")
MIN_REASON = 8
SAFE_ENV_KEYS = (
    "PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "LC_CTYPE", "TERM", "SHELL", "USER", "LOGNAME",
    "AI_SKILLS_STATE", "CODEX_HOME",
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY", "GRPC_PROXY",
    "http_proxy", "https_proxy", "no_proxy", "all_proxy", "grpc_proxy",
    "SSL_CERT_FILE", "SSL_CERT_DIR", "NODE_EXTRA_CA_CERTS", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE",
)
MAX_CELL = 400
MAX_STEPS = 60


def state_root() -> Path:
    explicit = os.environ.get("AI_SKILLS_STATE")
    if explicit:
        return Path(explicit).expanduser()
    xdg = os.environ.get("XDG_STATE_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "state"
    return base / "ai-skills"


def git(repo: Path, *args: str) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def normalize_remote(url: str) -> str:
    text = url.strip()
    if not text:
        return ""
    text = re.sub(r"^[a-z+]+://", "", text)
    text = re.sub(r"^[^@/]+@", "", text)
    text = text.replace(":", "/", 1) if re.match(r"^[^/]+:[^/]", text) else text
    text = re.sub(r"\.git/?$", "", text)
    host, _, path = text.partition("/")
    return f"{host.lower()}/{path.strip('/').lower()}"


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "repo"


def identity(repo: Path) -> dict:
    repo = repo.resolve()
    top = git(repo, "rev-parse", "--show-toplevel")
    if not top:
        ident = f"path:{repo}"
        return {"identity": ident, "key": f"{slug(repo.name)[:40]}-{hashlib.sha1(ident.encode()).hexdigest()[:8]}", "kind": "path", "root": str(repo)}
    remote = normalize_remote(git(top, "remote", "get-url", "origin"))
    root_commit = git(top, "rev-list", "--max-parents=0", "HEAD").splitlines()
    if remote:
        ident, kind = remote, "remote"
    elif root_commit:
        ident, kind = f"root:{root_commit[0]}", "root-commit"
    else:
        ident, kind = f"path:{top}", "path"
    key = f"{slug(ident.split('/', 1)[-1] if kind == 'remote' else Path(top).name)[:40]}-{hashlib.sha1(ident.encode()).hexdigest()[:8]}"
    return {"identity": ident, "key": key, "kind": kind, "root": top}


def default_run_id(repo: Path) -> str:
    branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD") or "run"
    return f"{slug(branch)[:40]}-{datetime.now(timezone.utc).strftime('%Y%m%d')}"


def run_dir(repo: Path, run_id: str | None) -> tuple[Path, dict, str]:
    ident = identity(repo)
    rid = run_id or default_run_id(repo)
    if not RUN_ID_RE.match(rid) or ".." in rid:
        raise SystemExit(f"run id {rid!r} must match {RUN_ID_RE.pattern} and contain no '..'")
    return state_root() / "runs" / ident["key"] / rid, ident, rid


def require_run(repo: Path, run_id: str | None) -> tuple[Path, dict, str]:
    path, ident, rid = run_dir(repo, run_id)
    if not (path / "run.json").is_file():
        raise SystemExit(f"no run record at {path}; run `runctl.py init --repo {repo}` first")
    return path, ident, rid


def clean_cell(value: object) -> str:
    text = " ".join(str(value if value is not None else "").split())
    text = text.replace("\t", " ")
    if text[:1] in {"=", "+", "-", "@"}:
        text = "'" + text
    return text[:MAX_CELL]


def secret_in(text: str) -> bool:
    return bool(SCANNER.findings_for(text, "record.txt")) or bool(PROXY_CREDENTIAL_RE.search(text))


def redact(text: str) -> str:
    text, _ = SCANNER.redact_text(text, "record.txt")
    return PROXY_CREDENTIAL_RE.sub("://[REDACTED]@", text)


PROXY_CREDENTIAL_RE = re.compile(r"://[^/@\s]+:[^/@\s]+@")
PROXY_KEYS = {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "GRPC_PROXY", "http_proxy", "https_proxy", "all_proxy", "grpc_proxy"}


def minimal_env(extra: dict | None = None) -> dict:
    env = {}
    for key in SAFE_ENV_KEYS:
        value = os.environ.get(key)
        if value is None or (key not in PROXY_KEYS and secret_in(value)):
            continue
        env[key] = value
    for key, value in (extra or {}).items():
        if secret_in(str(value)) or PROXY_CREDENTIAL_RE.search(str(value)):
            raise ValueError(f"environment value for {key!r} looks like a credential")
        env[key] = value
    return env


def read_rows(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows = []
    lines = path.read_text(encoding="utf-8").splitlines()
    for line in lines[1:]:
        if not line.strip():
            continue
        cells = line.split("\t")
        cells += [""] * (len(DECISION_COLUMNS) - len(cells))
        rows.append(dict(zip(DECISION_COLUMNS, cells)))
    return rows


def append_row(path: Path, row: dict) -> None:
    ledgerio.append_line(path, "\t".join(clean_cell(row.get(column, "")) for column in DECISION_COLUMNS),
                         header="\t".join(DECISION_COLUMNS) + "\n")


def run_lock(run: Path):
    return ledgerio.locked(run / "run.json")


def write_json(path: Path, data: dict) -> None:
    ledgerio.atomic_write(path, json.dumps(data, indent=2, sort_keys=True) + "\n")


def pointer_file(pointer: str, repo: Path, run: Path) -> Path | None:
    text = pointer.strip()
    if not text or URL_RE.match(text) or SHA_RE.match(text) or text.startswith("commit:"):
        return None
    if text.startswith("run:"):
        return run / text[4:]
    return _resolve_path(text, repo)


def receipt_findings(evidence: str, red: str, repo: Path, run: Path, fresh: bool) -> tuple[str, list[str]]:
    green_path, red_path = pointer_file(evidence, repo, run), pointer_file(red, repo, run)
    green_ok = green_path is not None and ledgerio.looks_like_receipt(green_path)
    red_ok = red_path is not None and ledgerio.looks_like_receipt(red_path)
    problems = []
    if green_ok:
        problems += ledgerio.receipt_problems(green_path, repo=repo, expect="PASS", require_fresh=fresh)
    if red_ok:
        problems += ledgerio.receipt_problems(red_path, repo=repo, expect="FAIL")
    if green_ok and red_ok:
        same = (ledgerio.load_receipt(green_path)["revision"]["content"]
                == ledgerio.load_receipt(red_path)["revision"]["content"])
        if same:
            problems.append("the red and green receipts observed the same revision: that is a flaky check, not a fail-demo")
    return ("receipt" if green_ok else "asserted"), problems


def revision_stamp(repo: Path) -> str:
    revision = ledgerio.worktree_revision(repo)
    return f" ; at: {revision['id']}" if revision else ""


def pointer_problem(pointer: str, repo: Path, run: Path) -> str | None:
    text = pointer.strip()
    if not text:
        return "evidence pointer is empty"
    if URL_RE.match(text):
        return "a URL is a citation, not an observation; observed needs a local pointer (path, file:line, commit, or run:<file>)"
    if text.startswith("run:"):
        target = run / text[4:]
        return None if target.is_file() else f"{text} is not a file under the run record"
    if text.startswith("commit:"):
        sha = text.removeprefix("commit:")
        if not SHA_RE.match(sha):
            return f"{text} is not a valid commit pointer"
        return None if _commit_exists(repo, sha) else f"commit {sha} is not in {repo}"
    if SHA_RE.match(text):
        return None if _commit_exists(repo, text) else f"commit {text} is not in {repo}"
    path_part, _, line_part = text.rpartition(":")
    if line_part.isdigit() and path_part:
        candidate = _resolve_path(path_part, repo)
        if candidate is None:
            return f"{path_part} does not exist"
        try:
            count = sum(1 for _ in candidate.open(encoding="utf-8", errors="replace"))
        except OSError:
            return f"{path_part} is not readable"
        return None if int(line_part) <= count else f"{path_part} has {count} lines, not {line_part}"
    candidate = _resolve_path(text, repo)
    if candidate is None:
        return f"{text} does not exist (path, file:line, commit, URL, or run:<file>)"
    return None if candidate.is_file() else f"{text} is a directory, not an observation"


def _commit_exists(repo: Path, sha: str) -> bool:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "cat-file", "-e", f"{sha}^{{commit}}"], capture_output=True, timeout=30, stdin=subprocess.DEVNULL
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return out.returncode == 0


def _resolve_path(text: str, repo: Path) -> Path | None:
    raw = Path(text).expanduser()
    for candidate in ([raw] if raw.is_absolute() else [repo / raw, Path.cwd() / raw]):
        if candidate.exists():
            return candidate
    return None




def level_problems(level: str, evidence: str, red_evidence: str, verifier: str) -> list[str]:
    problems = []
    if level not in LEVELS:
        return [f"level {level!r} is not one of {list(LEVELS)}"]
    if level != "claimed" and not evidence.strip():
        problems.append(f"{level} needs --evidence pointing at the observation")
    if level != "claimed" and evidence.strip() and URL_RE.match(evidence.strip()):
        problems.append(f"{level} needs a local pointer; a URL alone is a citation")
    if level == "failure-proven":
        if not red_evidence.strip():
            problems.append("failure-proven needs --red-evidence pointing at the run where the check turned red")
        elif red_evidence.strip() == evidence.strip():
            problems.append("failure-proven needs the red run as a second pointer, not the passing one again")
    if level == "independently-verified":
        cleaned = verifier.strip().lower()
        if not cleaned or cleaned in {"self", "me", "author", "same context"}:
            problems.append("independently-verified needs --verifier naming a context that did not do the work (never self)")
        elif verifier_pointer(verifier) is None:
            problems.append("independently-verified needs --verifier to point at the verifier's own record (a run:<file> or path), e.g. 'codex cross-family run:review/dispatch.json'")
    return problems


def verifier_pointer(verifier: str) -> str | None:
    for token in verifier.replace(",", " ").split():
        if token.startswith("run:") or "/" in token:
            return token
    return None


def cmd_identity(args: argparse.Namespace) -> int:
    print(json.dumps(identity(Path(args.repo)), indent=2 if not args.compact else None, sort_keys=True))
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    path, ident, rid = run_dir(repo, args.run)
    path.mkdir(parents=True, exist_ok=True)
    meta_path = path / "run.json"
    with run_lock(path):
        return _init_locked(path, meta_path, repo, ident, rid)


def _init_locked(path: Path, meta_path: Path, repo: Path, ident: dict, rid: str) -> int:
    if meta_path.is_file():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    else:
        meta = {
            "run_id": rid,
            "project": ident,
            "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "branch": git(repo, "rev-parse", "--abbrev-ref", "HEAD") or None,
            "head": git(repo, "rev-parse", "HEAD") or None,
            "workflows": [],
        }
        ledgerio.atomic_write(path / "decisions.tsv", "\t".join(DECISION_COLUMNS) + "\n")
        ledgerio.atomic_write(path / "checklist.md", f"# Run checklist — {rid}\n\n")
        write_json(meta_path, meta)
    print(json.dumps({"run": str(path), "run_id": rid, "project_key": ident["key"], "identity": ident["identity"]}, sort_keys=True))
    return 0


def cmd_decide(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    path, _, _ = require_run(repo, args.run)
    with run_lock(path):
        return _decide_locked(args, repo, path)


def _decide_locked(args: argparse.Namespace, repo: Path, path: Path) -> int:
    problems = level_problems(args.level, args.evidence or "", args.red_evidence or "", args.verifier or "")
    rows = read_rows(path / "decisions.tsv")
    if args.supersedes is not None and not any(r["row"] == str(args.supersedes) for r in rows):
        problems.append(f"--supersedes {args.supersedes} names a row that does not exist")
    for text in (args.decision, args.why, args.evidence or "", args.red_evidence or "", args.verifier or "", args.result or "", *(args.rejected or [])):
        if secret_in(text):
            problems.append("a cell looks like a credential; the trail never carries secrets")
            break
    basis = "asserted"
    if args.level != "claimed":
        basis, found = receipt_findings(args.evidence or "", args.red_evidence or "", repo, path, fresh=True)
        problems += found
    if problems:
        print("\n".join(f"decide: {p}" for p in problems), file=sys.stderr)
        return 2
    evidence = args.evidence or ""
    if args.red_evidence:
        evidence = f"{evidence} ; red: {args.red_evidence}"
    if args.verifier:
        evidence = f"{evidence} ; verifier: {args.verifier}"
    if args.level != "claimed":
        evidence += revision_stamp(repo)
    for pointer in [args.evidence or "", args.red_evidence or "", verifier_pointer(args.verifier or "") or ""]:
        if pointer:
            why = pointer_problem(pointer, repo, path)
            if why:
                print(f"decide: warning: {why} (validate will fail until it resolves)", file=sys.stderr)
    row = {
        "row": str(len(rows) + 1),
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "phase": args.phase,
        "decision": args.decision,
        "why": args.why,
        "rejected": " ; ".join(args.rejected or []),
        "evidence": evidence,
        "level": args.level,
        "result": args.result or "open",
        "supersedes": "" if args.supersedes is None else str(args.supersedes),
    }
    append_row(path / "decisions.tsv", row)
    print(json.dumps({"row": row["row"], "level": args.level, "basis": basis, "trail": str(path / "decisions.tsv")}, sort_keys=True))
    return 0


def cmd_outcome(args: argparse.Namespace) -> int:
    args.phase = "outcome"
    args.decision = f"outcome of #{args.row}"
    args.why = args.result
    args.supersedes = args.row
    args.rejected = []
    return cmd_decide(args)


def parse_steps(skill_md: Path) -> list[tuple[str, str, bool]]:
    steps: list[tuple[str, str, bool]] = []
    in_section = False
    in_code = False
    for line in skill_md.read_text(encoding="utf-8").splitlines():
        if line.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        if line.startswith("#"):
            in_section = bool(STEP_HEADING_RE.search(line))
            continue
        if not in_section:
            continue
        match = STEP_ITEM_RE.match(line)
        if not match:
            continue
        number, text = match.groups()
        text = re.sub(r"\*\*|`", "", text)
        text = re.split(r"(?<=[.:])\s", text, maxsplit=1)[0][:160]
        steps.append((number, text, bool(OPTIONAL_RE.search(text))))
    return steps[:MAX_STEPS]


def skill_version(source: Path) -> str:
    digest = hashlib.sha256(source.read_bytes()).hexdigest()[:12]
    commit = git(source.parent, "log", "-1", "--format=%h", "--", str(source))
    return f"{commit or 'uncommitted'}+{digest}"


def read_checklist(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| ") or line.startswith("| # ") or line.startswith("|---"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 9:
            continue
        rows.append(dict(zip(("n", "workflow", "step", "required", "state", "reason", "consequence", "evidence", "level"), cells)))
    return rows


def write_checklist(path: Path, header: list[str], rows: list[dict]) -> None:
    body = header + ["", "| # | workflow | step | required | state | reason | consequence | evidence | level |", "|---|---|---|---|---|---|---|---|---|"]
    for row in rows:
        body.append("| " + " | ".join(clean_cell(row[k]).replace("|", "/") for k in ("n", "workflow", "step", "required", "state", "reason", "consequence", "evidence", "level")) + " |")
    ledgerio.atomic_write(path, "\n".join(body) + "\n")


def checklist_header(path: Path) -> list[str]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("| # ") or line.startswith("|---") or line.startswith("| "):
            break
        out.append(line)
    while out and not out[-1].strip():
        out.pop()
    return out


def cmd_steps_freeze(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    path, _, _ = require_run(repo, args.run)
    if args.skill:
        skill_dir = Path(args.skill).resolve()
        source = skill_dir / "SKILL.md"
        if not source.is_file():
            print(f"freeze: {skill_dir} has no SKILL.md", file=sys.stderr)
            return 2
        name = skill_dir.name
    elif args.from_file and args.name:
        source = Path(args.from_file).resolve()
        if not source.is_file():
            print(f"freeze: {source} does not exist", file=sys.stderr)
            return 2
        name = slug(args.name)
    else:
        print("freeze: pass --skill <skill-dir>, or --from <markdown> with --name <workflow>", file=sys.stderr)
        return 2
    with run_lock(path):
        return _freeze_locked(args, path, source, name)


def _freeze_locked(args: argparse.Namespace, path: Path, source: Path, name: str) -> int:
    checklist = path / "checklist.md"
    rows = read_checklist(checklist)
    if any(r["workflow"] == name for r in rows) and not args.force:
        print(f"freeze: {name} is already frozen in this run; a re-freeze would let the run rewrite its own bar (use --force --reason at a new head)", file=sys.stderr)
        return 2
    if args.force and len((args.reason or "").strip()) < MIN_REASON:
        print("freeze: --force needs --reason saying why the bar changed; a silent re-freeze is the edit this record exists to expose", file=sys.stderr)
        return 2
    rows = [r for r in rows if r["workflow"] != name]
    parsed = parse_steps(source)
    numbers = [number for number, _, _ in parsed]
    if len(numbers) != len(set(numbers)):
        print("freeze: duplicate workflow step numbers make completion ambiguous", file=sys.stderr)
        return 2
    extra = [(f"x{i + 1}", text, False) for i, text in enumerate(args.step or [])]
    if not parsed and not extra:
        print(f"freeze: {source.name} enumerates no numbered steps under a workflow heading; pass --step for each required step", file=sys.stderr)
        return 2
    version = skill_version(source)
    for number, text, optional in parsed + extra:
        rows.append({"n": number, "workflow": name, "step": text, "required": "no" if optional else "yes", "state": "pending", "reason": "", "consequence": "", "evidence": "", "level": ""})
    header = checklist_header(checklist)
    header = [h for h in header if not h.startswith(f"frozen: {name} ")]
    header.append(f"frozen: {name} version={version} steps={len(parsed) + len(extra)} at={datetime.now(timezone.utc).isoformat(timespec='seconds')}" + (f" re-frozen: {clean_cell(args.reason)}" if args.force else ""))
    write_checklist(checklist, header, rows)
    meta_path = path / "run.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    manifest = [{"n": number, "step": clean_cell(text).replace("|", "/"), "required": "no" if optional else "yes"} for number, text, optional in parsed + extra]
    meta["workflows"] = [w for w in meta.get("workflows", []) if w.get("name") != name] + [{"name": name, "version": version, "source": str(source), "steps": manifest}]
    write_json(meta_path, meta)
    print(json.dumps({"workflow": name, "version": version, "required": sum(1 for _, _, o in parsed + extra if not o), "optional": sum(1 for _, _, o in parsed + extra if o)}, sort_keys=True))
    return 0


def _find_step(rows: list[dict], workflow: str, number: str) -> dict | None:
    return next((r for r in rows if r["workflow"] == workflow and r["n"] == number), None)


def cmd_steps_done(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    path, _, _ = require_run(repo, args.run)
    with run_lock(path):
        return _done_locked(args, repo, path)


def _done_locked(args: argparse.Namespace, repo: Path, path: Path) -> int:
    checklist = path / "checklist.md"
    rows = read_checklist(checklist)
    row = _find_step(rows, args.workflow, args.step)
    if row is None:
        print(f"done: step {args.step} of {args.workflow} is not frozen in this run", file=sys.stderr)
        return 2
    problems = level_problems(args.level, args.evidence or "", args.red_evidence or "", args.verifier or "")
    if args.level == "claimed":
        problems.append("a done step needs observed evidence or better; record what you saw, or skip it with a reason")
    for pointer in (args.evidence or "", args.red_evidence or "", verifier_pointer(args.verifier or "") or ""):
        why = pointer_problem(pointer, repo, path) if pointer else None
        if why:
            problems.append(f"evidence does not resolve: {why}")
    basis, found = receipt_findings(args.evidence or "", args.red_evidence or "", repo, path, fresh=True)
    problems += found
    if any(secret_in(text) for text in (args.evidence or "", args.red_evidence or "", args.verifier or "")):
        problems.append("a cell looks like a credential; the checklist never carries secrets")
    if problems:
        print("\n".join(f"done: {p}" for p in problems), file=sys.stderr)
        return 2
    evidence = args.evidence + (f" ; red: {args.red_evidence}" if args.red_evidence else "") + (f" ; verifier: {args.verifier}" if args.verifier else "") + revision_stamp(repo)
    row.update({"state": "done", "evidence": evidence, "level": args.level, "reason": "", "consequence": ""})
    write_checklist(checklist, checklist_header(checklist), rows)
    print(json.dumps({"workflow": args.workflow, "step": args.step, "state": "done", "level": args.level, "basis": basis}, sort_keys=True))
    return 0


def cmd_steps_skip(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    path, _, _ = require_run(repo, args.run)
    with run_lock(path):
        return _skip_locked(args, path)


def _skip_locked(args: argparse.Namespace, path: Path) -> int:
    checklist = path / "checklist.md"
    rows = read_checklist(checklist)
    row = _find_step(rows, args.workflow, args.step)
    if row is None:
        print(f"skip: step {args.step} of {args.workflow} is not frozen in this run", file=sys.stderr)
        return 2
    if len(args.reason.strip()) < MIN_REASON or len(args.consequence.strip()) < MIN_REASON:
        print("skip: a skipped step needs a real --reason and --consequence (what stays unproven), not a placeholder", file=sys.stderr)
        return 2
    if secret_in(args.reason) or secret_in(args.consequence):
        print("skip: a cell looks like a credential; the checklist never carries secrets", file=sys.stderr)
        return 2
    row.update({"state": "skipped", "reason": args.reason, "consequence": args.consequence, "evidence": "", "level": ""})
    write_checklist(checklist, checklist_header(checklist), rows)
    print(json.dumps({"workflow": args.workflow, "step": args.step, "state": "skipped"}, sort_keys=True))
    return 0


def manifest_problems(rows: list[dict], path: Path) -> list[str]:
    meta_path = path / "run.json"
    if not meta_path.is_file():
        return ["run.json is missing; the frozen manifest cannot be checked"]
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    problems = []
    for workflow in meta.get("workflows", []):
        name = workflow["name"]
        frozen = workflow.get("steps")
        if frozen is None:
            continue
        table = [(r["n"], r["step"], r["required"]) for r in rows if r["workflow"] == name]
        expected = [(f["n"], f["step"][:MAX_CELL], f["required"]) for f in frozen]
        if table != expected:
            problems.append(f"{name}: the checklist no longer matches the frozen manifest (steps, text, or requiredness changed); re-freeze with --force at a new head if the workflow really changed")
    table_names = {r["workflow"] for r in rows}
    for name in table_names - {w["name"] for w in meta.get("workflows", [])}:
        problems.append(f"{name}: appears in the checklist but was never frozen")
    return problems


def split_evidence(cell: str) -> tuple[str, str, str]:
    evidence, red, verifier = "", "", ""
    for part in re.split(r"\s;\s", cell):
        part = part.strip()
        if part.startswith("red:"):
            red = part[4:].strip()
        elif part.startswith("verifier:"):
            verifier = part[9:].strip()
        elif part.startswith("at:"):
            continue
        elif part and part != "-" and not evidence:
            evidence = part
    return evidence, red, verifier


def checklist_problems(rows: list[dict], repo: Path | None = None, run: Path | None = None) -> list[str]:
    problems = []
    for r in rows:
        where = f"{r['workflow']} step {r['n']}"
        if any(secret_in(r[k]) for k in ("step", "reason", "consequence", "evidence")):
            problems.append(f"{where}: a cell looks like a credential")
        if r["state"] not in STEP_STATES:
            problems.append(f"{where}: state {r['state']!r} is not one of {list(STEP_STATES)}")
            continue
        if r["required"] not in {"yes", "no"}:
            problems.append(f"{where}: required must be yes or no")
        if r["state"] == "done":
            if r["level"] not in LEVELS or r["level"] == "claimed":
                problems.append(f"{where}: done needs a level of observed or better, not {r['level']!r}")
            evidence, red, verifier = split_evidence(r["evidence"])
            if not evidence:
                problems.append(f"{where}: done needs evidence")
            elif r["level"] in LEVELS:
                problems += [f"{where}: {p}" for p in level_problems(r["level"], evidence, red, verifier)]
                if repo is not None and run is not None:
                    for pointer in (evidence, red, verifier_pointer(verifier) or ""):
                        why = pointer_problem(pointer, repo, run) if pointer else None
                        if why:
                            problems.append(f"{where}: evidence does not resolve: {why}")
                    problems += [f"{where}: {p}" for p in receipt_findings(evidence, red, repo, run, fresh=False)[1]]
        if r["state"] == "skipped" and (len(r["reason"].strip()) < MIN_REASON or len(r["consequence"].strip()) < MIN_REASON):
            problems.append(f"{where}: skipped needs a real reason and consequence")
    return problems


def gate_summary(rows: list[dict], repo: Path | None = None, run: Path | None = None) -> dict:
    required = [r for r in rows if r["required"] == "yes"]
    pending = [r for r in required if r["state"] == "pending"]
    skipped = [r for r in required if r["state"] == "skipped"]
    done = [r for r in required if r["state"] == "done"]
    blockers = [f"{r['workflow']} step {r['n']} ({r['step'][:60]}) was neither done nor skipped with a reason" for r in pending]
    blockers += checklist_problems(rows, repo, run)
    receipts = sum(1 for r in done if repo is not None and run is not None
                   and receipt_findings(split_evidence(r["evidence"])[0], "", repo, run, fresh=False)[0] == "receipt")
    if not rows:
        blockers.append("no workflow has been frozen into this run")
    return {
        "frozen": sorted({r["workflow"] for r in rows}),
        "required": len(required),
        "done": len(done),
        "skipped": [{"workflow": r["workflow"], "step": r["n"], "reason": r["reason"], "consequence": r["consequence"]} for r in skipped],
        "pending": len(pending),
        "basis": {"receipt": receipts, "asserted": len(done) - receipts},
        "blockers": blockers,
        "verdict": "PASS" if not blockers else "FAIL",
    }


def cmd_steps_gate(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    path, _, _ = require_run(repo, args.run)
    rows = read_checklist(path / "checklist.md")
    summary = gate_summary(rows, repo, path)
    drift = manifest_problems(rows, path)
    if drift:
        summary["blockers"] = drift + summary["blockers"]
        summary["verdict"] = "FAIL"
    print(json.dumps(summary, indent=2, sort_keys=True))
    for item in summary["skipped"]:
        print(f"  skipped: {item['workflow']} step {item['step']} — {item['reason']} → {item['consequence']}")
    for blocker in summary["blockers"]:
        print(f"  - {blocker}")
    print(f"VERDICT: {summary['verdict']}")
    return 0 if summary["verdict"] == "PASS" else 1


def cmd_check(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    path, _, _ = require_run(repo, args.run)
    argv = args.argv[1:] if args.argv[:1] == ["--"] else args.argv
    try:
        receipt_path, receipt = ledgerio.run_check(argv, repo=repo, out_dir=path / "receipts", observer="runctl",
                                                   passing=PASS_VERDICTS, failing=FAIL_VERDICTS, timeout=args.timeout)
    except ValueError as error:
        print(f"check: {error}", file=sys.stderr)
        return 2
    print(json.dumps({"pointer": f"run:receipts/{receipt_path.name}", "observed": receipt["observed"],
                      "exit": receipt["exit"], "revision": receipt["revision"]["id"], "stable": receipt["stable"]},
                     sort_keys=True))
    return 0


def validate(repo: Path, path: Path) -> list[str]:
    problems: list[str] = []
    rows = read_rows(path / "decisions.tsv")
    seen = set()
    for row in rows:
        n = row["row"]
        seen.add(n)
        if row["level"] not in LEVELS:
            problems.append(f"row {n}: level {row['level']!r} is not on the scale")
            continue
        evidence, red, verifier = split_evidence(row["evidence"])
        problems += [f"row {n}: {p}" for p in level_problems(row["level"], evidence, red, verifier)]
        if row["level"] != "claimed":
            for pointer in (evidence, red, verifier_pointer(verifier) or ""):
                why = pointer_problem(pointer, repo, path) if pointer else None
                if why:
                    problems.append(f"row {n}: evidence does not resolve: {why}")
            problems += [f"row {n}: {p}" for p in receipt_findings(evidence, red, repo, path, fresh=False)[1]]
        if row["supersedes"] and row["supersedes"] not in seen - {n}:
            problems.append(f"row {n}: supersedes row {row['supersedes']}, which does not precede it")
        if any(secret_in(row[k]) for k in ("decision", "why", "rejected", "evidence", "result")):
            problems.append(f"row {n}: a cell looks like a credential")
    problems += checklist_problems(read_checklist(path / "checklist.md"), repo, path)
    problems += manifest_problems(read_checklist(path / "checklist.md"), path)
    return problems


def cmd_validate(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    path, _, _ = require_run(repo, args.run)
    problems = validate(repo, path)
    rows = read_rows(path / "decisions.tsv")
    if problems:
        print("\n".join(f"validate: {p}" for p in problems), file=sys.stderr)
        print(f"VERDICT: FAIL ({len(problems)} problem(s) over {len(rows)} decision(s))")
        return 1
    print(f"VERDICT: PASS ({len(rows)} decision(s), every pointer resolves, no label above its evidence)")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    path, _, rid = require_run(repo, args.run)
    rows = read_rows(path / "decisions.tsv")
    print(f"run {rid} — {path}")
    for row in rows[-args.limit:]:
        sup = f" (supersedes #{row['supersedes']})" if row["supersedes"] else ""
        print(f"#{row['row']} [{row['phase']}] {row['decision']}{sup}")
        print(f"    why: {row['why']}")
        if row["rejected"]:
            print(f"    rejected: {row['rejected']}")
        print(f"    evidence: {row['evidence'] or '-'} [{row['level']}] → {row['result']}")
    summary = gate_summary(read_checklist(path / "checklist.md"))
    print(f"checklist: {summary['done']} done, {len(summary['skipped'])} skipped, {summary['pending']} pending → {summary['verdict']}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    root = state_root() / "runs"
    if not root.is_dir():
        print(f"no run records under {root}")
        return 0
    keys = [identity(Path(args.repo).resolve())["key"]] if args.repo else sorted(p.name for p in root.iterdir() if p.is_dir())
    for key in keys:
        for run in sorted((root / key).iterdir()) if (root / key).is_dir() else []:
            meta_path = run / "run.json"
            if not meta_path.is_file():
                continue
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            decisions = max(0, len(read_rows(run / "decisions.tsv")))
            print(f"{key}/{run.name}\t{meta.get('created', '?')}\t{decisions} decision(s)\t{meta.get('project', {}).get('identity', '?')}")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    path, _, rid = require_run(repo, args.run)
    if not args.i_own_this_repo:
        print("export: the record stays outside the repository unless you pass --i-own-this-repo", file=sys.stderr)
        return 2
    top = Path(git(repo, "rev-parse", "--show-toplevel") or repo).resolve()
    target = (top / args.into).resolve()
    if top not in target.parents and target != top:
        print(f"export: {target} is outside the repository {top}", file=sys.stderr)
        return 2
    target.mkdir(parents=True, exist_ok=True)
    for name in ("decisions.tsv", "checklist.md"):
        destination = target / f"{rid}-{name}"
        if destination.is_symlink() or (destination.exists() and not destination.is_file()):
            print(f"export: {destination} exists and is not a regular file; refusing to write through it", file=sys.stderr)
            return 2
        if top not in destination.resolve().parents:
            print(f"export: {destination} resolves outside the repository", file=sys.stderr)
            return 2
        shutil.copyfile(path / name, destination)
    print(json.dumps({"exported": [str(target / f"{rid}-decisions.tsv"), str(target / f"{rid}-checklist.md")]}, sort_keys=True))
    return 0


def cmd_prune(args: argparse.Namespace) -> int:
    root = state_root() / "runs"
    cutoff = datetime.now(timezone.utc) - timedelta(days=args.older_than)
    removed = []
    if root.is_dir():
        for key_dir in sorted(p for p in root.iterdir() if p.is_dir()):
            for run in sorted(p for p in key_dir.iterdir() if p.is_dir()):
                meta_path = run / "run.json"
                if not meta_path.is_file():
                    continue
                created = json.loads(meta_path.read_text(encoding="utf-8")).get("created", "")
                try:
                    stamp = datetime.fromisoformat(created)
                except ValueError:
                    continue
                if stamp < cutoff and run.resolve().is_relative_to(root.resolve()):
                    removed.append(str(run))
                    if not args.dry_run:
                        shutil.rmtree(run)
    print(json.dumps({"removed": removed, "dry_run": args.dry_run, "older_than_days": args.older_than}, sort_keys=True))
    return 0


def cmd_selftest(_args: argparse.Namespace) -> int:
    import tempfile

    def run(argv: list[str], expect: int, capture: bool = False) -> str:
        import contextlib
        import io

        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = main(argv)
            except SystemExit as stop:
                code = int(stop.code) if isinstance(stop.code, int) else 1
        if code != expect:
            raise SystemExit(f"selftest: {argv[:3]} exited {code}, want {expect}\n{err.getvalue()}{out.getvalue()}")
        return out.getvalue() + err.getvalue()

    with tempfile.TemporaryDirectory(prefix="runctl-selftest-") as tmp:
        os.environ["AI_SKILLS_STATE"] = str(Path(tmp) / "state")
        repo = Path(tmp) / "repo"
        repo.mkdir()
        subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "root"], check=True)
        (repo / "proof.txt").write_text("line1\nline2\n", encoding="utf-8")
        skill = Path(tmp) / "skills" / "release"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\nname: release\ndescription: x\n---\n# Release\n\n## Process\n\n1. **Discover** the publish path.\n2. **Bump** the version.\n3. **Narrate (optional).** Add a clip.\n4. **Publish** after confirmation.\n\n## Notes\n\n1. not a step\n",
            encoding="utf-8",
        )
        base = ["--repo", str(repo), "--run", "t1"]

        ident = json.loads(run(["identity", "--repo", str(repo), "--compact"], 0))
        if ident["kind"] != "root-commit" or str(repo) in ident["key"]:
            raise SystemExit(f"selftest: identity should key on the root commit, got {ident}")
        if normalize_remote("git@github.com:Owner/Repo.git") != normalize_remote("https://github.com/owner/repo/"):
            raise SystemExit("selftest: remote spellings must normalize to one identity")

        run(["init", *base], 0)
        run(["decide", *base, "--phase", "p", "--decision", "d", "--why", "w", "--level", "observed"], 2)
        run(["decide", *base, "--phase", "p", "--decision", "d", "--why", "w", "--level", "failure-proven", "--evidence", "proof.txt"], 2)
        run(["decide", *base, "--phase", "p", "--decision", "d", "--why", "w", "--level", "independently-verified", "--evidence", "proof.txt", "--verifier", "self"], 2)
        run(["decide", *base, "--phase", "p", "--decision", "d", "--why", "w", "--level", "bogus", "--evidence", "proof.txt"], 2)
        run(["decide", *base, "--phase", "p", "--decision", "d", "--why", "w", "--level", "observed", "--evidence", "https://example.invalid/pr/1"], 2)
        run(["decide", *base, "--phase", "p", "--decision", "d", "--why", "w", "--level", "failure-proven", "--evidence", "proof.txt", "--red-evidence", "proof.txt"], 2)
        run(["decide", *base, "--phase", "p", "--decision", "d", "--why", "w", "--level", "independently-verified", "--evidence", "proof.txt", "--verifier", "someone"], 2)
        run(["decide", *base, "--phase", "p", "--decision", "d", "--why", "w", "--level", "independently-verified", "--evidence", "proof.txt", "--verifier", "codex, cross-family"], 2)
        (Path(tmp) / "state" / "runs" / ident["key"] / "t1" / "review.json").write_text("{}", encoding="utf-8")
        run(["decide", *base, "--phase", "p", "--decision", "d", "--why", "w", "--level", "independently-verified", "--evidence", "proof.txt", "--verifier", "codex cross-family run:review.json"], 0)
        (repo / "docs").mkdir(exist_ok=True)
        run(["decide", *base, "--phase", "p", "--decision", "d", "--why", "w", "--level", "observed", "--evidence", "docs"], 0)
        if "not an observation" not in run(["validate", *base], 1):
            raise SystemExit("selftest: a directory pointer must fail validate")
        lines = (Path(tmp) / "state" / "runs" / ident["key"] / "t1" / "decisions.tsv").read_text(encoding="utf-8").splitlines()
        (Path(tmp) / "state" / "runs" / ident["key"] / "t1" / "decisions.tsv").write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
        fake_key = "AKIA" + "ABCDEFGHIJKLMNOP"
        run(["decide", *base, "--phase", "p", "--decision", f"token {fake_key}", "--why", "w"], 2)
        run(["decide", *base, "--phase", "plan", "--decision", "use route A", "--why", "cheaper", "--rejected", "route B — needs prod creds", "--evidence", "proof.txt:2", "--level", "observed", "--result", "tests green"], 0)
        run(["decide", *base, "--phase", "plan", "--decision", "claim only", "--why", "not run"], 0)
        run(["decide", *base, "--phase", "verify", "--decision", "gate proven", "--why", "planted break went red", "--evidence", "proof.txt", "--red-evidence", "proof.txt:1", "--level", "failure-proven"], 0)
        head = git(repo, "rev-parse", "HEAD")
        run(["decide", *base, "--phase", "verify", "--decision", "commit pointer works", "--why", "commit evidence is local", "--evidence", f"commit:{head}", "--level", "observed"], 0)
        run(["outcome", *base, "--row", "1", "--result", "route A shipped", "--evidence", "proof.txt", "--level", "observed"], 0)
        run(["decide", *base, "--phase", "p", "--decision", "x", "--why", "y", "--supersedes", "99"], 2)
        if "VERDICT: PASS" not in run(["validate", *base], 0):
            raise SystemExit("selftest: a clean trail must validate")
        (repo / "proof.txt").unlink()
        if "does not resolve" not in run(["validate", *base], 1):
            raise SystemExit("selftest: a dangling evidence pointer must fail validate")
        (repo / "proof.txt").write_text("line1\nline2\n", encoding="utf-8")
        trail = Path(tmp) / "state" / "runs" / ident["key"] / "t1" / "decisions.tsv"
        trail.write_text(trail.read_text(encoding="utf-8") + "9\t2026-01-01T00:00:00+00:00\tp\tforged\tw\t\t\tindependently-verified\topen\t\n", encoding="utf-8")
        if "independently-verified needs" not in run(["validate", *base], 1):
            raise SystemExit("selftest: a hand-planted high label without evidence must fail validate")
        lines = trail.read_text(encoding="utf-8").splitlines()
        trail.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
        trail.write_text(trail.read_text(encoding="utf-8") + "9\t2026-01-01T00:00:00+00:00\tp\tforged\tw\t\tverifier: codex\tindependently-verified\topen\t\n", encoding="utf-8")
        if "needs --evidence" not in run(["validate", *base], 1):
            raise SystemExit("selftest: a verifier-only cell must fail validate as missing evidence")
        lines = trail.read_text(encoding="utf-8").splitlines()
        trail.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
        trail.write_text(trail.read_text(encoding="utf-8") + "9\t2026-01-01T00:00:00+00:00\tp\tforged\tw\t\tproof.txt ; red: proof.txt\tfailure-proven\topen\t\n", encoding="utf-8")
        if "second pointer" not in run(["validate", *base], 1):
            raise SystemExit("selftest: a hand-planted failure-proven row with a duplicated pointer must fail validate")
        lines = trail.read_text(encoding="utf-8").splitlines()
        trail.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
        run(["decide", *base, "--phase", "p", "--decision", "=HYPERLINK(x)", "--why", "w"], 0)
        if "\t'=HYPERLINK(x)\t" not in trail.read_text(encoding="utf-8"):
            raise SystemExit("selftest: a formula-looking cell must be prefixed with a quote")

        proxy_url = "http://user:" + "hunter2" + "@proxy.invalid:8080"
        out = json.loads(run(["steps", "freeze", *base, "--skill", str(skill)], 0))
        if out["required"] != 3 or out["optional"] != 1:
            raise SystemExit(f"selftest: expected 3 required + 1 optional steps, got {out}")
        run(["steps", "freeze", *base, "--skill", str(skill)], 2)
        run(["steps", "freeze", *base, "--skill", str(skill), "--force"], 2)
        run(["steps", "gate", *base], 1)
        run(["steps", "done", *base, "--workflow", "release", "--step", "1", "--evidence", "proof.txt", "--level", "claimed"], 2)
        run(["steps", "done", *base, "--workflow", "release", "--step", "1", "--evidence", "nonexistent.txt"], 2)
        run(["steps", "done", *base, "--workflow", "release", "--step", "1", "--evidence", "proof.txt"], 0)
        run(["steps", "done", *base, "--workflow", "release", "--step", "2", "--evidence", "proof.txt"], 0)
        run(["steps", "skip", *base, "--workflow", "release", "--step", "4", "--reason", "n/a", "--consequence", "x"], 2)
        if "VERDICT: FAIL" not in run(["steps", "gate", *base], 1):
            raise SystemExit("selftest: a pending required step must fail the gate")
        run(["steps", "skip", *base, "--workflow", "release", "--step", "4", "--reason", "publishing needs the user's registry token", "--consequence", "the release is built but not published"], 0)
        gate = run(["steps", "gate", *base], 0)
        if "VERDICT: PASS" not in gate or "not published" not in gate:
            raise SystemExit("selftest: a skipped step must stay visible with its consequence")
        run(["steps", "done", *base, "--workflow", "release", "--step", "9", "--evidence", "proof.txt"], 2)
        checklist = Path(tmp) / "state" / "runs" / ident["key"] / "t1" / "checklist.md"
        rows = read_checklist(checklist)
        forged = [dict(r, state="done", level="claimed", evidence="") if r["n"] == "4" else r for r in rows]
        write_checklist(checklist, checklist_header(checklist), forged)
        if "VERDICT: FAIL" not in run(["steps", "gate", *base], 1) or "done needs" not in run(["validate", *base], 1):
            raise SystemExit("selftest: a hand-forged done row must fail the gate and validate")
        forged = [dict(r, state="done", level="independently-verified", evidence="proof.txt") if r["n"] == "4" else r for r in rows]
        write_checklist(checklist, checklist_header(checklist), forged)
        if "needs --verifier" not in run(["steps", "gate", *base], 1):
            raise SystemExit("selftest: a hand-forged independently-verified row must fail the gate for its missing verifier")
        forged = [dict(r, state="done", level="observed", evidence="vanished.txt") if r["n"] == "4" else r for r in rows]
        write_checklist(checklist, checklist_header(checklist), forged)
        if "does not resolve" not in run(["steps", "gate", *base], 1):
            raise SystemExit("selftest: a done row whose pointer does not resolve must fail the gate")
        run(["steps", "done", *base, "--workflow", "release", "--step", "4", "--evidence", "proof.txt", "--level", "independently-verified", "--verifier", f"codex run:review.json via {proxy_url}"], 2)
        run(["steps", "skip", *base, "--workflow", "release", "--step", "4", "--reason", f"blocked behind {proxy_url}", "--consequence", "the release is built but not published"], 2)
        forged = [dict(r, reason=f"via {proxy_url}") if r["n"] == "4" else r for r in rows]
        write_checklist(checklist, checklist_header(checklist), forged)
        if "looks like a credential" not in run(["steps", "gate", *base], 1):
            raise SystemExit("selftest: a credential in a hand-edited checklist cell must fail the gate")
        write_checklist(checklist, checklist_header(checklist), rows)
        run(["steps", "gate", *base], 0)
        relaxed = [dict(r, required="no") for r in rows]
        write_checklist(checklist, checklist_header(checklist), relaxed)
        if "frozen manifest" not in run(["steps", "gate", *base], 1):
            raise SystemExit("selftest: relaxing a frozen requirement must fail the gate")
        write_checklist(checklist, checklist_header(checklist), rows)
        run(["steps", "gate", *base], 0)
        saved = os.environ.get("HTTPS_PROXY")
        proxy_url = "http://user:" + "hunter2" + "@proxy.invalid:8080"
        os.environ["HTTPS_PROXY"] = proxy_url
        try:
            if "HTTPS_PROXY" not in minimal_env():
                raise SystemExit("selftest: the proxy must reach a worker or nothing connects")
            if "hunter2" in redact(f"proxy is {proxy_url} ok") or "[REDACTED]@" not in redact(proxy_url):
                raise SystemExit("selftest: a proxy password must be masked by redact")
            run(["decide", *base, "--phase", "p", "--decision", f"use {proxy_url}", "--why", "w"], 2)
        finally:
            if saved is None:
                del os.environ["HTTPS_PROXY"]
            else:
                os.environ["HTTPS_PROXY"] = saved

        def check(code: str) -> str:
            return json.loads(run(["check", *base, "--", sys.executable, "-c", code], 0))["pointer"]

        green = check("print('VERDICT: PASS')")
        run(["decide", *base, "--phase", "verify", "--decision", "red is not green", "--why", "w", "--level", "observed", "--evidence", check("raise SystemExit(1)")], 2)
        out = json.loads(run(["decide", *base, "--phase", "verify", "--decision", "tests green", "--why", "receipt", "--level", "observed", "--evidence", green], 0))
        if out["basis"] != "receipt":
            raise SystemExit("selftest: a receipt pointer must be counted as machine-observed")
        run(["decide", *base, "--phase", "verify", "--decision", "flaky", "--why", "same revision", "--level", "failure-proven", "--evidence", green, "--red-evidence", check("raise SystemExit(1)")], 2)
        receipts = Path(tmp) / "state" / "runs" / ident["key"] / "t1" / "receipts"
        forged = receipts / "forged.json"
        forged.write_text((receipts / green[len("run:receipts/"):]).read_text(encoding="utf-8"), encoding="utf-8")
        run(["decide", *base, "--phase", "verify", "--decision", "forged", "--why", "w", "--level", "observed", "--evidence", "run:receipts/forged.json"], 2)
        forged.unlink()
        (repo / "proof.txt").write_text("line1\nline2\nline3\n", encoding="utf-8")
        run(["decide", *base, "--phase", "verify", "--decision", "stale", "--why", "w", "--level", "observed", "--evidence", green], 2)
        red = check("raise SystemExit(1)")
        (repo / "proof.txt").write_text("line1\nline2\n", encoding="utf-8")
        run(["decide", *base, "--phase", "verify", "--decision", "gate proven by receipts", "--why", "planted break went red", "--level", "failure-proven", "--evidence", green, "--red-evidence", red], 0)
        run(["validate", *base], 0)
        stdout = receipts / (green[len("run:receipts/"):-len(".json")] + ".stdout")
        stdout.write_text("VERDICT: PASS (edited)\n", encoding="utf-8")
        if "changed after the run" not in run(["validate", *base], 1):
            raise SystemExit("selftest: an edited receipt capture must fail validate")
        stdout.unlink()
        if "capture is missing" not in run(["validate", *base], 1):
            raise SystemExit("selftest: a missing receipt capture must fail validate")
        stdout.write_text("VERDICT: PASS\n", encoding="utf-8")
        run(["validate", *base], 0)

        run(["export", *base, "--into", "docs/run"], 2)
        run(["export", *base, "--into", "../outside", "--i-own-this-repo"], 2)
        run(["export", *base, "--into", "docs/run", "--i-own-this-repo"], 0)
        if not (repo / "docs" / "run" / "t1-decisions.tsv").is_file():
            raise SystemExit("selftest: export must copy the trail into the repository")
        (repo / "docs" / "run" / "t1-decisions.tsv").unlink()
        os.symlink(Path(tmp) / "elsewhere.tsv", repo / "docs" / "run" / "t1-decisions.tsv")
        run(["export", *base, "--into", "docs/run", "--i-own-this-repo"], 2)
        if (Path(tmp) / "elsewhere.tsv").exists():
            raise SystemExit("selftest: export must not write through a symlink")
        (repo / "docs" / "run" / "t1-decisions.tsv").unlink()
        run(["prune", "--older-than", "365"], 0)
        if not trail.is_file():
            raise SystemExit("selftest: prune must keep a fresh run")
        run(["prune", "--older-than", "0", "--dry-run"], 0)
        if not trail.is_file():
            raise SystemExit("selftest: a dry run must delete nothing")
        run(["prune", "--older-than", "0"], 0)
        if trail.exists():
            raise SystemExit("selftest: prune older-than 0 must remove a run created today only when it is older than now")
        del os.environ["AI_SKILLS_STATE"]

    print("runctl_selftest_ok (labels, pointers, receipts, silent omission, export, and prune all proven able to refuse)")
    return 0


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo", default=".", help="a directory inside the project (default: cwd)")
    parser.add_argument("--run", help="run id (default: <branch>-<date>)")


def add_evidence(parser: argparse.ArgumentParser, default_level: str) -> None:
    parser.add_argument("--evidence", help="pointer: path, file:line, commit, URL, or run:<file>")
    parser.add_argument("--level", default=default_level, choices=LEVELS)
    parser.add_argument("--red-evidence", help="pointer to the run where the check turned red (failure-proven)")
    parser.add_argument("--verifier", help="the independent context that verified it (independently-verified)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Decision trail and frozen workflow checklist for a run.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    ident = sub.add_parser("identity", help="canonical project identity and sidecar key")
    ident.add_argument("--repo", default=".")
    ident.add_argument("--compact", action="store_true")
    ident.set_defaults(func=cmd_identity)

    init = sub.add_parser("init", help="create the run record")
    add_common(init)
    init.set_defaults(func=cmd_init)

    dec = sub.add_parser("decide", help="append one decision row")
    add_common(dec)
    dec.add_argument("--phase", required=True)
    dec.add_argument("--decision", required=True)
    dec.add_argument("--why", required=True)
    dec.add_argument("--rejected", action="append", help="'option — reason'; repeatable")
    dec.add_argument("--result", help="outcome so far (default: open)")
    dec.add_argument("--supersedes", type=int, help="row this one corrects; history is never edited")
    add_evidence(dec, "claimed")
    dec.set_defaults(func=cmd_decide)

    outc = sub.add_parser("outcome", help="record how an earlier decision turned out")
    add_common(outc)
    outc.add_argument("--row", type=int, required=True)
    outc.add_argument("--result", required=True)
    add_evidence(outc, "claimed")
    outc.set_defaults(func=cmd_outcome)

    steps = sub.add_parser("steps", help="frozen workflow checklist")
    ssub = steps.add_subparsers(dest="steps_cmd", required=True)
    frz = ssub.add_parser("freeze", help="freeze a selected workflow's required steps and version")
    add_common(frz)
    frz.add_argument("--skill", help="the selected skill's folder")
    frz.add_argument("--from", dest="from_file", help="any markdown with numbered steps: a goal file or runbook")
    frz.add_argument("--name", help="workflow name when freezing from --from")
    frz.add_argument("--step", action="append", help="extra required step; repeatable")
    frz.add_argument("--force", action="store_true", help="re-freeze at a new head; needs --reason")
    frz.add_argument("--reason", help="why the bar changed (required with --force)")
    frz.set_defaults(func=cmd_steps_freeze)
    done = ssub.add_parser("done", help="mark a step done with evidence")
    add_common(done)
    done.add_argument("--workflow", required=True)
    done.add_argument("--step", required=True)
    add_evidence(done, "observed")
    done.set_defaults(func=cmd_steps_done)
    skip = ssub.add_parser("skip", help="skip a step visibly, with a reason and a consequence")
    add_common(skip)
    skip.add_argument("--workflow", required=True)
    skip.add_argument("--step", required=True)
    skip.add_argument("--reason", required=True)
    skip.add_argument("--consequence", required=True, help="what stays unproven because of the skip")
    skip.set_defaults(func=cmd_steps_skip)
    gate = ssub.add_parser("gate", help="FAIL while any required step is silently omitted")
    add_common(gate)
    gate.set_defaults(func=cmd_steps_gate)

    chk = sub.add_parser("check", help="run a check and keep a receipt the gates can verify")
    add_common(chk)
    chk.add_argument("--timeout", type=float, default=3600)
    chk.add_argument("argv", nargs=argparse.REMAINDER)
    chk.set_defaults(func=cmd_check)

    val = sub.add_parser("validate", help="every pointer resolves; no label above its evidence")
    add_common(val)
    val.set_defaults(func=cmd_validate)

    show = sub.add_parser("show", help="print the trail and checklist summary")
    add_common(show)
    show.add_argument("--limit", type=int, default=40)
    show.set_defaults(func=cmd_show)

    lst = sub.add_parser("list", help="list run records")
    lst.add_argument("--repo")
    lst.set_defaults(func=cmd_list)

    exp = sub.add_parser("export", help="copy the record into the repository (explicit opt-in)")
    add_common(exp)
    exp.add_argument("--into", required=True, help="directory relative to the repository root")
    exp.add_argument("--i-own-this-repo", action="store_true")
    exp.set_defaults(func=cmd_export)

    prune = sub.add_parser("prune", help="delete run records older than N days")
    prune.add_argument("--older-than", type=int, required=True, help="days")
    prune.add_argument("--dry-run", action="store_true")
    prune.set_defaults(func=cmd_prune)

    sub.add_parser("selftest", help="prove every gate can refuse").set_defaults(func=cmd_selftest)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
