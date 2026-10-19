#!/usr/bin/env python3

from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "safe-push" / "scripts" / "with_account.py"
FAKE_GH = r'''#!/usr/bin/env python3
import json, os, sys
state = os.environ["FAKE_GH_STATE"]
args = sys.argv[1:]
if args[:2] == ["auth", "status"]:
    user = open(state).read().strip()
    print(json.dumps({"hosts": {"github.com": [{"login": user, "active": True}]}}))
elif args[:2] == ["auth", "switch"]:
    user = args[args.index("--user") + 1]
    if user == "nobody":
        sys.exit(1)
    open(state, "w").write(user)
    if user == os.environ.get("FAKE_GH_SLOW_TO"):
        import time
        time.sleep(1)
else:
    sys.exit(2)
'''
failures: list[str] = []


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        bin_dir = tmp / "bin"
        bin_dir.mkdir()
        (bin_dir / "gh").write_text(FAKE_GH)
        (bin_dir / "gh").chmod(0o755)
        state = tmp / "active"
        state.write_text("home-account")
        env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "FAKE_GH_STATE": str(state),
               "SAFE_PUSH_LOCK": str(tmp / "lock")}
        seen = tmp / "seen"

        def run(user: str, *command: str, **kwargs) -> subprocess.CompletedProcess:
            return subprocess.run([sys.executable, str(SCRIPT), "--user", user, "--", *command], env=env,
                                  capture_output=True, text=True, **kwargs)

        probe = [sys.executable, "-c", f"import os;open({str(seen)!r},'a').write(open(os.environ['FAKE_GH_STATE']).read()+'\\n')"]
        done = run("work-account", *probe)
        if done.returncode or seen.read_text().split() != ["work-account"] or state.read_text() != "home-account":
            failures.append(f"switch, run as the target, and restore: {done.stderr}")
        if "home-account -> work-account -> home-account" not in done.stderr:
            failures.append("both switches must be reported")

        seen.unlink()
        done = run("home-account", *probe)
        if "switched" in done.stderr or seen.read_text().split() != ["home-account"]:
            failures.append("no switch when the account is already active")

        done = run("work-account", sys.executable, "-c", "raise SystemExit(7)")
        if done.returncode != 7 or state.read_text() != "home-account":
            failures.append("a failing command keeps its exit code and the account is restored")

        done = run("nobody", "true")
        if done.returncode != 3 or state.read_text() != "home-account":
            failures.append("a switch that fails runs nothing and leaves the account alone")

        proc = subprocess.Popen([sys.executable, str(SCRIPT), "--user", "work-account", "--", "sleep", "30"], env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for _ in range(50):
            if state.read_text() == "work-account":
                break
            time.sleep(0.1)
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=20)
        if state.read_text() != "home-account":
            failures.append("SIGTERM mid-command must still restore the previous account")
            state.write_text("home-account")

        proc = subprocess.Popen([sys.executable, str(SCRIPT), "--user", "work-account", "--", "sleep", "30"],
                                env={**env, "FAKE_GH_SLOW_TO": "work-account"},
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for _ in range(50):
            if state.read_text() == "work-account":
                break
            time.sleep(0.05)
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=20)
        if state.read_text() != "home-account":
            failures.append("SIGTERM during the switch itself must still restore the previous account")
            state.write_text("home-account")

        seen.unlink(missing_ok=True)
        slow = [sys.executable, "-c", "import os,time;s=os.environ['FAKE_GH_STATE'];a=open(s).read();time.sleep(0.3);"
                f"open({str(seen)!r},'a').write(a+' '+open(s).read()+'\\n')"]
        with ThreadPoolExecutor(4) as pool:
            list(pool.map(lambda u: run(u, *slow), ["acct-a", "acct-b", "acct-a", "acct-b"]))
        pairs = [line.split() for line in seen.read_text().splitlines()]
        if len(pairs) != 4 or any(a != b for a, b in pairs) or state.read_text() != "home-account":
            failures.append(f"concurrent callers must never see another caller's switch: {pairs}")

    for failure in failures:
        print(f"safe-push-account FAIL: {failure}", file=sys.stderr)
    if failures:
        return 1
    print("safe_push_account_ok (switch and restore, no-op when active, failures, SIGTERM, serialized callers)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
