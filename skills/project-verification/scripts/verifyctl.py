#!/usr/bin/env python3

from __future__ import annotations

import argparse
import contextlib
import fnmatch
import hashlib
import json
import os
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from testselect import cache_root, default_base

LOOP_SCRIPTS = Path(__file__).resolve().parents[2] / "loop" / "scripts"
sys.path.insert(0, str(LOOP_SCRIPTS))
try:
    import ledgerio  # noqa: E402
except ImportError:  # pragma: no cover
    sys.exit("verifyctl: the loop skill (ledgerio.py) must be installed beside project-verification")

DEFAULT_DIR = Path(".agents") / "skills" / "verify-project"
FORMAT = 1
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")
MAP_HEADING = re.compile(r"^## +([a-z0-9][a-z0-9._-]{1,63}) +— +(.+?)\s*$", re.M)
PLACEHOLDER = re.compile(r"TODO|<fill|FIXME")
PASSING, FAILING = {"PASS"}, {"FAIL"}
DEFAULT_GONE_TIMEOUT_S = 15
EXIT = {"pass": 0, "product-regression": 1, "invalid": 2, "drift": 3, "harness-failure": 4, "blocked": 5}


def recipe_dir(args: argparse.Namespace) -> Path:
    return Path(args.project).resolve() / (args.dir or DEFAULT_DIR)


def load(rdir: Path) -> dict:
    path = rdir / "recipe.json"
    if not path.is_file():
        raise SystemExit(f"no recipe at {path}; run `verifyctl.py init --project <dir>` first")
    return json.loads(path.read_text(encoding="utf-8"))


def save(rdir: Path, recipe: dict) -> None:
    ledgerio.atomic_write(rdir / "recipe.json", json.dumps(recipe, indent=2, sort_keys=False) + "\n")


def sources_digest(project: Path, patterns: list[str]) -> tuple[str, list[str]]:
    digest, missing = hashlib.sha256(), []
    for pattern in patterns:
        matches = sorted(p for p in project.glob(pattern) if p.is_file())
        if not matches:
            missing.append(pattern)
        for path in matches:
            digest.update(str(path.relative_to(project)).encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest(), missing


def spec_digest(feature: dict) -> str:
    spec = {"steps": feature.get("steps"), "requires": feature.get("requires", [])}
    return hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()


def discover(project: Path) -> list[dict]:
    found = []
    package = project / "package.json"
    if package.is_file():
        with contextlib.suppress(ValueError):
            scripts = json.loads(package.read_text(encoding="utf-8")).get("scripts", {})
            for name in ("dev", "start", "serve", "test", "e2e", "test:e2e", "playwright"):
                if name in scripts:
                    found.append({"kind": "npm-script", "command": ["npm", "run", name], "source": "package.json"})
    makefile = project / "Makefile"
    if makefile.is_file():
        for target in re.findall(r"^([A-Za-z][\w-]*):", makefile.read_text(encoding="utf-8", errors="replace"), re.M):
            if target in {"run", "dev", "serve", "start", "test", "e2e", "check", "verify"}:
                found.append({"kind": "make", "command": ["make", target], "source": "Makefile"})
    for name, kind in (("playwright.config.ts", "playwright"), ("playwright.config.js", "playwright"),
                       ("cypress.config.ts", "cypress"), ("cypress.config.js", "cypress"),
                       ("pytest.ini", "pytest"), ("pyproject.toml", "python-project"),
                       ("scripts/check.sh", "repository-gate"), ("docker-compose.yml", "compose")):
        if (project / name).is_file():
            found.append({"kind": kind, "source": name})
    if shutil.which("agent-browser"):
        found.append({"kind": "agent-browser", "command": ["agent-browser", "--help"], "source": "PATH"})
    return found


SKILL_TEMPLATE = """---
name: verify-project
description: >
  Prove {app}'s user-facing features work: launch an isolated instance, drive each mapped feature,
  keep evidence, tear down. Use before claiming a change to {app} works.
---
# Verify {app}

`recipe.json` is the runnable recipe; `features.md` is the user-facing feature map. Both belong
to this project. The shared `project-verification` skill's `verifyctl.py` runs them:

```bash
VERIFY=<project-verification-dir>/scripts/verifyctl.py
python3 "$VERIFY" check --project .                     # recipe, map, and drift
python3 "$VERIFY" run --project . --changed {base} # features whose sources changed
python3 "$VERIFY" run --project . --feature <id>        # one feature; omit for all
```

Exit 0 means every driven feature passed. 1 is a product regression, 3 is source drift that
needs triage, 4 is a broken harness, and 5 is a named missing precondition. Never edit an
expected result to make a run pass; a changed expectation is a product decision.
Keep evidence outside the checkout. The default cache is `~/.cache/project-verification/`;
`PROJECT_VERIFICATION_CACHE` overrides it. Teardown stops only the instance this run started.
"""


def cmd_init(args: argparse.Namespace) -> int:
    project = Path(args.project).resolve()
    rdir = recipe_dir(args)
    if (rdir / "recipe.json").exists() and not args.force:
        print(f"init: {rdir} already has a recipe; maintain it with `check` and `accept`", file=sys.stderr)
        return 2
    app = args.app or project.name
    recipe = {
        "format": FORMAT,
        "app": app,
        "surface": args.surface,
        "harnesses": discover(project),
        "isolation": {"port_env": "PORT", "data_dir_env": "DATA_DIR"},
        "launch": {"command": ["TODO: start command, e.g. python3 app.py"], "ready": {"command": [
            "TODO: probe that exits 0 when ready"], "timeout_s": 30}},
        "doctor": {"command": ["TODO: read-only health check"]},
        "teardown": None,
        "features": [],
        "history": [],
    }
    rdir.mkdir(parents=True, exist_ok=True)
    save(rdir, recipe)
    ledgerio.atomic_write(rdir / "features.md", f"# {app} feature map\n\nOne section per user-facing feature. "
                          "Each says what the user does, every entry point, and the observable result.\n")
    ledgerio.atomic_write(rdir / "SKILL.md", SKILL_TEMPLATE.format(app=app, base=shlex.quote(default_base(project))))
    print(json.dumps({"recipe": str(rdir / "recipe.json"), "harnesses": recipe["harnesses"],
                      "next": "fill launch, doctor, and features from the project; then run check"}, indent=2))
    return 0


def problems_of(project: Path, rdir: Path, recipe: dict) -> tuple[list[str], list[dict]]:
    invalid, drift = [], []
    if recipe.get("format") != FORMAT:
        invalid.append(f"recipe format {recipe.get('format')!r} is not {FORMAT}; refusing to guess a migration")
    text = json.dumps({k: v for k, v in recipe.items() if k != "history"})
    if PLACEHOLDER.search(text):
        invalid.append("the recipe still has placeholders (TODO); fill them from the project")
    launch = recipe.get("launch")
    if launch is not None and not (launch.get("command") and (launch.get("ready") or {}).get("command")):
        invalid.append("launch needs a command and a ready probe, or launch must be null for a CLI-only surface")
    if not (recipe.get("doctor") or {}).get("command"):
        invalid.append("doctor needs a read-only command")
    features = recipe.get("features") or []
    if not features:
        invalid.append("the recipe maps no features")
    ids = [f.get("id") for f in features]
    for fid in ids:
        if not fid or not ID_RE.match(fid):
            invalid.append(f"feature id {fid!r} must match {ID_RE.pattern}")
    if len(set(ids)) != len(ids):
        invalid.append(f"duplicate feature ids: {sorted({i for i in ids if ids.count(i) > 1})}")
    mapped = dict(MAP_HEADING.findall((rdir / "features.md").read_text(encoding="utf-8"))) \
        if (rdir / "features.md").is_file() else {}
    for fid in sorted(set(ids) - set(mapped)):
        invalid.append(f"{fid} is in the recipe but not in features.md")
    for fid in sorted(set(mapped) - set(ids)):
        invalid.append(f"{fid} is in features.md but has no runnable steps in the recipe")
    for feature in features:
        fid = feature.get("id")
        steps = feature.get("steps") or []
        if not steps:
            invalid.append(f"{fid}: no drive steps")
        for step in steps:
            expect = step.get("expect") or {}
            if not step.get("run") or not expect:
                invalid.append(f"{fid}: step {step.get('name')!r} needs `run` and an observable `expect`")
        if not feature.get("sources"):
            invalid.append(f"{fid}: name the source paths that implement it, so drift can be seen")
            continue
        digest, missing = sources_digest(project, feature["sources"])
        accepted = feature.get("accepted") or {}
        if missing:
            drift.append({"feature": fid, "kind": "source-missing", "detail": f"no file matches {missing}"})
        if not accepted:
            drift.append({"feature": fid, "kind": "never-accepted", "detail": "no passing run has been accepted yet"})
            continue
        if accepted.get("sources") != digest:
            drift.append({"feature": fid, "kind": "source-changed", "detail": "implementation changed since the last accepted pass"})
        if accepted.get("spec") != spec_digest(feature):
            drift.append({"feature": fid, "kind": "spec-changed",
                          "detail": "steps or expectations changed since acceptance; a changed expectation needs a product decision"})
    return invalid, drift


def uncovered(project: Path, recipe: dict, base: str, rdir: Path) -> list[str]:
    changed = changed_files(project, base)
    patterns = [p for f in recipe.get("features", []) for p in f.get("sources", [])]
    try:
        rdir_rel = rdir.resolve().relative_to(project.resolve()).as_posix()
    except ValueError:
        rdir_rel = None
    return sorted(c for c in changed if (rdir_rel is None or not (c == rdir_rel or c.startswith(rdir_rel + "/")))
                  and not any(fnmatch.fnmatch(c, p) or Path(c).match(p) for p in patterns))


def changed_files(project: Path, base: str) -> list[str]:
    out = subprocess.run(["git", "-C", str(project), "diff", "--name-only", base], capture_output=True, text=True)
    if out.returncode:
        raise SystemExit(f"cannot diff against {base!r}: {out.stderr.strip()}")
    extra = subprocess.run(["git", "-C", str(project), "ls-files", "--others", "--exclude-standard"],
                           capture_output=True, text=True).stdout
    return sorted(set(out.stdout.split()) | set(extra.split()))


def cmd_check(args: argparse.Namespace) -> int:
    project, rdir = Path(args.project).resolve(), recipe_dir(args)
    recipe = load(rdir)
    invalid, drift = problems_of(project, rdir, recipe)
    result = {"invalid": invalid, "drift": drift}
    if args.uncovered:
        result["uncovered"] = uncovered(project, recipe, args.uncovered, rdir)
    print(json.dumps(result, indent=2))
    if invalid:
        return EXIT["invalid"]
    return EXIT["drift"] if drift else 0


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def expand(argv: list[str], values: dict) -> list[str]:
    return [re.sub(r"\{(\w+)\}", lambda m: str(values.get(m.group(1), m.group(0))), part) for part in argv]


def probe(argv: list[str], env: dict, cwd: Path, timeout: float) -> tuple[bool, str]:
    try:
        done = subprocess.run(argv, cwd=str(cwd), env=env, capture_output=True, text=True, timeout=timeout,
                              stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as error:
        return False, str(error)
    return done.returncode == 0, (done.stdout + done.stderr)[-500:]


class Instance:
    def __init__(self, recipe: dict, project: Path, values: dict, env: dict, log: Path):
        self.recipe, self.project, self.values, self.env, self.log = recipe, project, values, env, log
        self.proc: subprocess.Popen | None = None

    def start(self) -> tuple[bool, str]:
        launch = self.recipe.get("launch")
        if launch is None:
            return True, "no long-lived instance (CLI surface)"
        argv = expand(launch["command"], self.values)
        try:
            self.proc = subprocess.Popen(argv, cwd=str(self.project / launch.get("cwd", ".")), env=self.env,
                                         stdout=self.log.open("wb"), stderr=subprocess.STDOUT,
                                         stdin=subprocess.DEVNULL, start_new_session=True)
        except OSError as error:
            return False, f"launch command failed to start: {error}"
        ready = launch["ready"]
        deadline = time.monotonic() + float(ready.get("timeout_s", 30))
        last = ""
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                return False, f"the instance exited with {self.proc.returncode} before it was ready"
            ok, last = probe(expand(ready["command"], self.values), self.env, self.project, 10)
            if ok:
                return True, "ready"
            time.sleep(0.2)
        return False, f"ready probe never passed within {ready.get('timeout_s', 30)}s: {last}"

    def alive(self) -> bool:
        return self.proc is None or self.proc.poll() is None

    def stop(self) -> dict:
        if self.proc is None:
            return {"stopped": [], "left": []}
        pgid = self.proc.pid
        with contextlib.suppress(ProcessLookupError):
            os.killpg(pgid, signal.SIGTERM)
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(pgid, signal.SIGKILL)
            self.proc.wait(timeout=10)
        time.sleep(0.1)
        left = group_members(pgid)
        for pid in left:
            with contextlib.suppress(ProcessLookupError):
                os.kill(pid, signal.SIGKILL)
        return {"stopped": [pgid], "left": group_members(pgid)}


def group_members(pgid: int) -> list[int]:
    out = subprocess.run(["ps", "-A", "-o", "pid=,pgid="], capture_output=True, text=True).stdout
    return [int(pid) for pid, group in (line.split() for line in out.splitlines() if line.strip())
            if int(group) == pgid]


def select(recipe: dict, project: Path, args: argparse.Namespace) -> list[dict]:
    features = recipe["features"]
    if args.feature:
        unknown = set(args.feature) - {f["id"] for f in features}
        if unknown:
            raise SystemExit(f"run: unknown feature ids {sorted(unknown)}")
        return [f for f in features if f["id"] in args.feature]
    if args.changed:
        changed = changed_files(project, args.changed)
        return [f for f in features
                if any(fnmatch.fnmatch(c, p) or Path(c).match(p) for c in changed for p in f.get("sources", []))]
    return features


def check_expect(expect: dict, receipt: dict, out_dir: Path) -> list[str]:
    stdout = (out_dir / receipt["stdout"]["file"]).read_text(encoding="utf-8", errors="replace")
    misses = []
    if "exit" in expect and receipt["exit"] != expect["exit"]:
        misses.append(f"exit {receipt['exit']}, expected {expect['exit']}")
    contains = expect.get("stdout_contains", [])
    for needle in [contains] if isinstance(contains, str) else contains:
        if needle not in stdout:
            misses.append(f"stdout lacks {needle!r}")
    if "stdout_regex" in expect and not re.search(expect["stdout_regex"], stdout, re.M):
        misses.append(f"stdout does not match /{expect['stdout_regex']}/")
    for needle in expect.get("stdout_absent", []):
        if needle in stdout:
            misses.append(f"stdout contains forbidden {needle!r}")
    return misses


def unmet(requires: list[str]) -> list[str]:
    missing = []
    for item in requires:
        kind, _, name = item.partition(":")
        if kind == "env" and not os.environ.get(name):
            missing.append(f"environment variable {name} is not set")
        elif kind == "cmd" and not shutil.which(name):
            missing.append(f"command {name} is not installed")
        elif kind not in ("env", "cmd"):
            missing.append(f"unknown precondition {item!r}")
    return missing


def run_feature(feature: dict, inst: Instance, project: Path, evidence: Path, doctor: list[str]) -> dict:
    result = {"id": feature["id"], "status": "pass", "steps": [], "detail": ""}
    missing = unmet(feature.get("requires", []))
    if missing:
        result.update(status="blocked", detail=f"not driven: {'; '.join(missing)}")
        return result
    for step in feature["steps"]:
        argv = expand(step["run"], inst.values)
        try:
            path, receipt = ledgerio.run_check(argv, repo=project, out_dir=evidence / "receipts", observer="verifyctl",
                                               passing=PASSING, failing=FAILING, timeout=float(step.get("timeout_s", 60)),
                                               cwd=project, env=inst.env, label=f"{feature['id']}:{step.get('name', '')}")
        except ValueError as error:
            result.update(status="harness-failure", detail=str(error))
            return result
        entry = {"name": step.get("name"), "receipt": str(path.relative_to(evidence)), "exit": receipt["exit"]}
        result["steps"].append(entry)
        if receipt["exit"] in (126, 127) or receipt["timed_out"]:
            result.update(status="harness-failure", detail=f"step {step.get('name')!r} could not run (exit {receipt['exit']})")
            return result
        if not receipt["stable"]:
            result.update(status="harness-failure", detail="the step changed the worktree; keep instance data outside the project")
            return result
        misses = check_expect(step["expect"], receipt, evidence / "receipts")
        if misses:
            healthy = inst.alive() and probe(expand(doctor, inst.values), inst.env, project, 30)[0]
            status = "product-regression" if healthy else "harness-failure"
            why = "" if healthy else " (the instance was unhealthy afterwards, so the harness cannot tell)"
            result.update(status=status, detail=f"step {step.get('name')!r}: {'; '.join(misses)}{why}")
            return result
    return result


def cmd_run(args: argparse.Namespace) -> int:
    project, rdir = Path(args.project).resolve(), recipe_dir(args)
    recipe = load(rdir)
    invalid, drift = problems_of(project, rdir, recipe)
    if invalid:
        print(json.dumps({"invalid": invalid}, indent=2), file=sys.stderr)
        return EXIT["invalid"]
    revision = ledgerio.worktree_revision(project)
    if revision is None:
        print("run: the project is not a git worktree; evidence needs a revision to bind to", file=sys.stderr)
        return EXIT["harness-failure"]
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + f"-{os.getpid()}"
    root = Path(args.evidence).expanduser() if args.evidence else \
        cache_root() / project.name
    evidence = root / run_id
    evidence.mkdir(parents=True, exist_ok=False)
    scratch = Path(tempfile.mkdtemp(prefix=f"verify-{project.name}-"))
    iso = recipe.get("isolation") or {}
    features = select(recipe, project, args)
    report = {"project": str(project), "app": recipe["app"], "run_id": run_id, "revision": revision,
              "drift": drift, "instances": [], "features": []}
    doctor = recipe["doctor"]["command"]
    shared = iso.get("per_feature") is False
    groups = [features] if shared else [[f] for f in features]
    for index, group in enumerate(groups):
        values = {"port": free_port(), "data_dir": str(scratch / f"data-{index}"), "evidence": str(evidence),
                  "run_id": run_id}
        Path(values["data_dir"]).mkdir()
        env = {**os.environ, **{k: str(v) for k, v in (recipe.get("env") or {}).items()}}
        if iso.get("port_env"):
            env[iso["port_env"]] = str(values["port"])
        if iso.get("data_dir_env"):
            env[iso["data_dir_env"]] = values["data_dir"]
        inst = Instance(recipe, project, values, env, evidence / f"instance-{index}.log")
        record = {"port": values["port"], "data_dir": values["data_dir"], "features": [f["id"] for f in group]}
        try:
            ok, why = inst.start()
            record["launch"] = why
            if ok:
                ok, why = probe(expand(doctor, values), env, project, 30)
                record["doctor"] = "ok" if ok else why
            if not ok:
                report["features"] += [{"id": f["id"], "status": "harness-failure", "steps": [], "detail": why,
                                        "drift": []} for f in group]
            else:
                for feature in group:
                    result = run_feature(feature, inst, project, evidence, doctor)
                    result["drift"] = [d["kind"] for d in drift if d["feature"] == feature["id"]]
                    report["features"].append(result)
        finally:
            record["teardown"] = inst.stop()
            teardown = recipe.get("teardown") or {}
            if teardown.get("command"):
                record["teardown"]["command"] = probe(expand(teardown["command"], values), env, project, 60)[0]
            record["teardown"]["confirmed"] = not record["teardown"]["left"]
            if teardown.get("gone"):
                deadline = time.monotonic() + float(teardown["gone"].get("timeout_s", DEFAULT_GONE_TIMEOUT_S))
                while not (gone := probe(expand(teardown["gone"]["command"], values), env, project, 10)[0]) \
                        and time.monotonic() < deadline:
                    time.sleep(0.5)
                record["teardown"]["confirmed"] = record["teardown"]["confirmed"] and gone
            report["instances"].append(record)
    shutil.rmtree(scratch, ignore_errors=True)
    outcome = "pass"
    statuses = [f["status"] for f in report["features"]]
    for status in ("harness-failure", "product-regression", "blocked"):
        if status in statuses:
            outcome = status
            break
    driven_drift = [d for d in drift if d["feature"] in {f["id"] for f in features} and d["kind"] != "never-accepted"]
    if outcome == "pass" and driven_drift:
        outcome = "drift"
    report["outcome"] = outcome
    report["evidence_kept"] = all((evidence / s["receipt"]).is_file() for f in report["features"] for s in f["steps"])
    report["cleanup_confirmed"] = all(i["teardown"]["confirmed"] for i in report["instances"])
    ledgerio.atomic_write(evidence / "report.json", json.dumps(report, indent=2) + "\n")
    print(json.dumps({"outcome": outcome, "report": str(evidence / "report.json"),
                      "cleanup_confirmed": report["cleanup_confirmed"],
                      "features": {f["id"]: f["status"] for f in report["features"]},
                      "drift": [f"{d['feature']}: {d['kind']}" for d in driven_drift]}, indent=2))
    return EXIT[outcome]


def lock_path_outside_project(project: Path) -> Path:
    key = hashlib.sha256(str(project).encode()).hexdigest()[:16]
    path = (cache_root() / "locks" / key).resolve()
    if path == project or project in path.parents:
        raise SystemExit("PROJECT_VERIFICATION_CACHE must stay outside the project")
    return path


def cmd_accept(args: argparse.Namespace) -> int:
    project, rdir = Path(args.project).resolve(), recipe_dir(args)
    report_path = Path(args.report)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if len((args.reason or "").strip()) < 8:
        print("accept: --reason must say what was checked", file=sys.stderr)
        return 2
    current = ledgerio.worktree_revision(project)
    if not current or report["revision"]["content"] != current["content"]:
        print("accept: the report is from another revision; run again first", file=sys.stderr)
        return 2
    with ledgerio.locked(lock_path_outside_project(project)):
        recipe = load(rdir)
        results = {f["id"]: f for f in report["features"]}
        for fid in args.feature:
            feature = next((f for f in recipe["features"] if f["id"] == fid), None)
            if feature is None or results.get(fid, {}).get("status") != "pass":
                print(f"accept: {fid} has no passing result in that report", file=sys.stderr)
                return 2
            for step in results[fid]["steps"]:
                problems = ledgerio.receipt_problems(report_path.parent / step["receipt"], repo=project,
                                                     require_fresh=True)
                if problems:
                    print(f"accept: {fid}: {problems[0]}", file=sys.stderr)
                    return 2
            digest, missing = sources_digest(project, feature["sources"])
            if missing:
                print(f"accept: {fid} names sources that match nothing: {missing}", file=sys.stderr)
                return 2
            feature["accepted"] = {"sources": digest, "spec": spec_digest(feature), "revision": current["id"]}
            recipe["history"].append({"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                      "feature": fid, "revision": current["id"], "reason": args.reason.strip()})
        save(rdir, recipe)
    print(json.dumps({"accepted": args.feature, "revision": current["id"]}))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Project-local verification recipes and feature maps.",
        epilog="Exit codes: 0 pass, 1 product regression, 2 invalid recipe, 3 unresolved drift, "
               "4 harness failure, 5 blocked.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--project", default=".")
        p.add_argument("--dir", help=f"recipe folder inside the project (default {DEFAULT_DIR})")

    p = sub.add_parser("init", help="discover harnesses; write a draft recipe, map, and SKILL.md")
    common(p)
    p.add_argument("--app")
    p.add_argument("--surface", default="http", choices=["http", "cli", "browser", "desktop", "library"])
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_init)
    p = sub.add_parser("check", help="schema, map parity, placeholders, and drift")
    common(p)
    p.add_argument("--uncovered", metavar="BASE", help="also list changed files no feature claims")
    p.set_defaults(func=cmd_check)
    p = sub.add_parser("run", help="launch, check health, drive features, tear down")
    common(p)
    p.add_argument("--feature", action="append", help="feature id; repeatable")
    p.add_argument("--changed", metavar="BASE", help="only features whose sources changed since BASE")
    p.add_argument("--evidence", help="evidence root (default: configured verification cache/<project>)")
    p.set_defaults(func=cmd_run)
    p = sub.add_parser("accept", help="record a passing feature's sources and spec as current")
    common(p)
    p.add_argument("--report", required=True)
    p.add_argument("--feature", action="append", required=True)
    p.add_argument("--reason", required=True)
    p.set_defaults(func=cmd_accept)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
