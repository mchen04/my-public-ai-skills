#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERIFY = ROOT / "skills" / "project-verification" / "scripts" / "verifyctl.py"
sys.path.insert(0, str(ROOT / "skills" / "loop" / "scripts"))
import ledgerio  # noqa: E402

APP = r'''
import json, os, sys, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
threading.Timer(120, os._exit, [0]).start()
from urllib.parse import parse_qs
DATA = os.path.join(os.environ["DATA_DIR"], "notes.json")
WORD = "created"
def notes():
    return json.load(open(DATA)) if os.path.exists(DATA) else []
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def reply(self, code, text):
        self.send_response(code); self.end_headers(); self.wfile.write(text.encode())
    def do_GET(self):
        if self.path == "/health": return self.reply(200, "ok")
        if self.path == "/notes": return self.reply(200, json.dumps(notes()))
        if self.path == "/": return self.reply(200, "<html><title>Notes</title><h1>Notes</h1></html>")
        self.reply(404, "missing")
    def do_POST(self):
        size = int(self.headers.get("Content-Length", 0))
        title = parse_qs(self.rfile.read(size).decode()).get("title", [""])[0]
        json.dump(notes() + [title], open(DATA, "w"))
        self.reply(201, WORD + " " + title)
HTTPServer(("127.0.0.1", int(os.environ["PORT"])), H).serve_forever()
'''

CLIENT = r'''
import os, sys, urllib.request
method, path = sys.argv[1], sys.argv[2]
data = sys.argv[3].encode() if len(sys.argv) > 3 else None
url = "http://127.0.0.1:%s%s" % (os.environ["PORT"], path)
with urllib.request.urlopen(urllib.request.Request(url, data=data, method=method), timeout=5) as r:
    print(r.read().decode())
'''


def recipe(port_probe_path: str = "/health") -> dict:
    py = sys.executable
    return {
        "launch": {"command": [py, "app.py"], "ready": {"command": [py, "client.py", "GET", port_probe_path], "timeout_s": 8}},
        "doctor": {"command": [py, "client.py", "GET", "/health"]},
        "features": [
            {"id": "notes.create", "title": "Create a note", "sources": ["app.py"],
             "steps": [{"name": "post", "run": [py, "client.py", "POST", "/notes", "title=milk"],
                        "expect": {"exit": 0, "stdout_contains": "created milk"}},
                       {"name": "list", "run": [py, "client.py", "GET", "/notes"],
                        "expect": {"exit": 0, "stdout_contains": "milk"}}]},
            {"id": "notes.empty", "title": "A new instance starts empty", "sources": ["app.py"],
             "steps": [{"name": "list", "run": [py, "client.py", "GET", "/notes"], "expect": {"exit": 0, "stdout_regex": r"^\[\]$"}}]},
            {"id": "docs.readme", "title": "Readme names the app", "sources": ["README.md"],
             "steps": [{"name": "cat", "run": [py, "-c", "print(open('README.md').read())"], "expect": {"exit": 0, "stdout_contains": "Notes"}}]},
        ],
    }


MAP = """# notes feature map

## notes.create — Create a note
A user posts a title; the list then shows it.

## notes.empty — A new instance starts empty
A fresh instance lists no notes.

## docs.readme — Readme names the app
The readme says what the app is.
"""

failures: list[str] = []


def expect(condition: bool, message: str) -> None:
    if not condition:
        failures.append(message)


def vc(project: Path, *args: str, env: dict | None = None) -> tuple[int, dict | str]:
    done = subprocess.run([sys.executable, str(VERIFY), *args, "--project", str(project)],
                          capture_output=True, text=True,
                          env={**os.environ, "PROJECT_VERIFICATION_CACHE": str(project.parent / "verification-cache"), **(env or {})}, timeout=300)
    try:
        return done.returncode, json.loads(done.stdout)
    except ValueError:
        return done.returncode, done.stdout + done.stderr


def edit_recipe(project: Path, change) -> None:
    path = project / ".agents/skills/verify-project/recipe.json"
    data = json.loads(path.read_text())
    change(data)
    path.write_text(json.dumps(data, indent=2))


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="pv-test-") as tmp:
        tmp = Path(tmp)
        project = tmp / "notes"
        project.mkdir()
        (project / "app.py").write_text(APP)
        (project / "client.py").write_text(CLIENT)
        (project / "README.md").write_text("# Notes\n")
        (project / "Makefile").write_text("run:\n\tpython3 app.py\ntest:\n\ttrue\n")
        subprocess.run(["git", "init", "-q", str(project)], check=True)
        evidence = tmp / "evidence"
        ev = ["--evidence", str(evidence)]

        code, out = vc(project, "init", "--app", "notes")
        expect(code == 0 and any(h["kind"] == "make" for h in out["harnesses"]), f"init should discover make targets: {out}")
        code, out = vc(project, "init")
        expect(code == 2, "init must refuse to overwrite an existing recipe")
        code, out = vc(project, "check")
        expect(code == 2 and any("placeholders" in p for p in out["invalid"]), f"a draft with TODOs must be invalid: {out}")
        skill = (project / ".agents/skills/verify-project/SKILL.md").read_text()
        expect(skill.startswith("---\nname: verify-project\n"), "the generated SKILL.md needs frontmatter")

        edit_recipe(project, lambda r: r.update(recipe()))
        code, out = vc(project, "check")
        expect(code == 2 and any("not in features.md" in p for p in out["invalid"]), "a recipe feature missing from the map must be invalid")
        (project / ".agents/skills/verify-project/features.md").write_text(MAP)
        code, out = vc(project, "check")
        expect(code == 3 and {d["kind"] for d in out["drift"]} == {"never-accepted"}, f"a new map is never-accepted drift: {out}")

        code, out = vc(project, "run", *ev)
        expect(code == 0 and out["outcome"] == "pass", f"the first run should pass: {out}")
        report_path = Path(out["report"])
        report = json.loads(report_path.read_text())
        expect(len(report["instances"]) == 3 and all(i["teardown"]["left"] == [] for i in report["instances"]),
               "each feature gets its own instance, and teardown leaves no process from its group")
        receipts = [report_path.parent / s["receipt"] for f in report["features"] for s in f["steps"]]
        expect(receipts and all(not ledgerio.receipt_problems(r, repo=project) for r in receipts),
               "every step receipt must verify after teardown")
        code, out = vc(project, "accept", "--report", str(report_path), "--feature", "notes.create",
                       "--feature", "notes.empty", "--feature", "docs.readme", "--reason", "first verified run")
        expect(code == 0, f"accept after a passing run: {out}")
        expect(any((tmp / "verification-cache" / "locks").glob("*")), "accept must keep its lock in the configured temporary cache")
        code, out = vc(project, "check")
        expect(code == 0, f"after acceptance the recipe is clean: {out}")

        receipts[0].with_suffix(".stdout").write_text("created milk (edited)\n")
        code, out = vc(project, "accept", "--report", str(report_path), "--feature", "notes.create", "--reason", "try forged")
        expect(code == 2, "accept must refuse a report whose receipt was edited")

        app = (project / "app.py").read_text()
        (project / "app.py").write_text(app.replace('WORD = "created"', 'WORD = "saved"'))
        code, out = vc(project, "run", *ev)
        expect(code == 1 and out["features"]["notes.create"] == "product-regression",
               f"a wrong response from a healthy app is a product regression: {out}")
        expect("notes.create: source-changed" in out["drift"], "the regression run must also show source drift")
        report_bad = Path(out["report"])
        code, _ = vc(project, "accept", "--report", str(report_bad), "--feature", "notes.create", "--reason", "accept the failure")
        expect(code == 2, "accept must refuse a failing feature")
        (project / "app.py").write_text(app)

        (project / "app.py").write_text(app + "\n# refactor: no behavior change\n")
        code, out = vc(project, "run", *ev, "--feature", "notes.create")
        expect(code == 3 and out["outcome"] == "drift", f"passing changed source is drift needing triage: {out}")
        code, _ = vc(project, "accept", "--report", out["report"], "--feature", "notes.create", "--reason", "comment-only change, re-driven")
        expect(code == 0, "a passing re-run can accept source drift")
        (project / "README.md").write_text("# Notes\nmore\n")
        code, _ = vc(project, "accept", "--report", out["report"], "--feature", "notes.create", "--reason", "stale report")
        expect(code == 2, "accept must refuse a report from another revision")

        subprocess.run(["git", "-C", str(project), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(project), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base"], check=True)
        (project / "README.md").write_text("# Notes\nchanged\n")
        custom = project / "custom-verification"
        shutil.copytree(project / ".agents/skills/verify-project", custom)
        other = project / "custom-verification-other.txt"
        other.write_text("unmapped synthetic file\n")
        code, out = vc(project, "check", "--dir", "custom-verification", "--uncovered", "HEAD")
        expect(not any(path.startswith("custom-verification/") for path in out["uncovered"]),
               "uncovered must exclude the selected custom recipe directory")
        expect(other.name in out["uncovered"], "a similar filename outside the recipe directory stays uncovered")
        shutil.rmtree(custom)
        other.unlink()
        code, out = vc(project, "run", *ev, "--changed", "HEAD")
        expect(set(out["features"]) == {"docs.readme"}, f"--changed must select only docs.readme: {out}")

        edit_recipe(project, lambda r: r["features"][0]["steps"][0]["expect"].update(stdout_contains="saved milk"))
        code, out = vc(project, "check")
        expect(code == 3 and any(d["kind"] == "spec-changed" for d in out["drift"]), "an edited expectation must show as spec drift")
        edit_recipe(project, lambda r: r["features"][0]["steps"][0]["expect"].update(stdout_contains="created milk"))

        edit_recipe(project, lambda r: r["launch"]["ready"].update(command=[sys.executable, "client.py", "GET", "/nope"], timeout_s=2))
        code, out = vc(project, "run", *ev)
        expect(code == 4 and out["outcome"] == "harness-failure", f"a probe that never passes is a harness failure: {out}")
        edit_recipe(project, lambda r: r["launch"].update(command=["no-such-binary-xyz"], ready={"command": [sys.executable, "client.py", "GET", "/health"], "timeout_s": 2}))
        code, out = vc(project, "run", *ev)
        expect(code == 4, f"a launch command that cannot start is a harness failure: {out}")
        edit_recipe(project, lambda r: r["launch"].update(command=[sys.executable, "app.py"]))
        edit_recipe(project, lambda r: r["features"][2]["steps"][0].update(run=["no-such-tool-xyz"]))
        code, out = vc(project, "run", *ev, "--feature", "docs.readme")
        expect(code == 4 and out["features"]["docs.readme"] == "harness-failure", f"a missing step tool is a harness failure: {out}")
        edit_recipe(project, lambda r: r["features"][2]["steps"][0].update(run=[sys.executable, "-c", "print(open('README.md').read())"]))

        edit_recipe(project, lambda r: r.update(teardown={"command": [sys.executable, "-c", "pass"],
                                                          "gone": {"command": [sys.executable, "-c", "raise SystemExit(1)"], "timeout_s": 1}}))
        code, out = vc(project, "run", *ev, "--feature", "docs.readme")
        expect(out["cleanup_confirmed"] is False, f"a gone probe that never passes must leave cleanup unconfirmed: {out}")
        edit_recipe(project, lambda r: r.update(teardown=None))

        edit_recipe(project, lambda r: r["features"][2].update(requires=["env:PV_TEST_NEVER_SET"]))
        code, out = vc(project, "run", *ev, "--feature", "docs.readme")
        expect(code == 5 and out["features"]["docs.readme"] == "blocked", f"an unmet precondition is blocked: {out}")
        edit_recipe(project, lambda r: r["features"][2].pop("requires"))

        decoy_port = str(ledgerio_free_port())
        decoy_data = tmp / "decoy"
        decoy_data.mkdir()
        decoy = subprocess.Popen([sys.executable, "app.py"], cwd=project, env={**os.environ, "PORT": decoy_port, "DATA_DIR": str(decoy_data)},
                                 start_new_session=True)
        try:
            with ThreadPoolExecutor(2) as pool:
                runs = list(pool.map(lambda _: vc(project, "run", *ev, "--feature", "notes.create", "--feature", "notes.empty"), range(2)))
            for code, out in runs:
                expect(out["features"] == {"notes.create": "pass", "notes.empty": "pass"},
                       f"concurrent isolated runs must each see an empty store and pass: {out}")
            ports = [i["port"] for _, out in runs for i in json.loads(Path(out["report"]).read_text())["instances"]]
            expect(len(set(ports)) == len(ports) == 4, "concurrent runs and features must use different ports")
            time.sleep(0.3)
            expect(decoy.poll() is None, "teardown must not stop a process the run did not start")
        finally:
            decoy.terminate()
            decoy.wait(timeout=10)

    if failures:
        for failure in failures:
            print(f"project-verification FAIL: {failure}", file=sys.stderr)
        return 1
    print("project_verification_ok (generate, check, run, accept, regression, drift, spec drift, harness, blocked, isolation, owned teardown)")
    return 0


def ledgerio_free_port() -> int:
    import socket
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


if __name__ == "__main__":
    sys.exit(main())
