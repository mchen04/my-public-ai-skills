#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fcntl
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

LOCK = Path(os.environ.get("SAFE_PUSH_LOCK", Path.home() / ".cache" / "safe-push" / "gh-switch.lock"))


def active(host: str) -> str | None:
    out = subprocess.run(["gh", "auth", "status", "--active", "--hostname", host, "--json", "hosts"],
                         capture_output=True, text=True)
    try:
        accounts = json.loads(out.stdout)["hosts"][host]
    except (ValueError, KeyError, TypeError):
        return None
    return next((a.get("login") for a in accounts if a.get("active", True)), None)


def switch(host: str, user: str) -> bool:
    done = subprocess.run(["gh", "auth", "switch", "--hostname", host, "--user", user], capture_output=True, text=True)
    return done.returncode == 0 and active(host) == user


def raise_interrupt(*_):
    raise KeyboardInterrupt


def route_termination_to_restore() -> None:
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, raise_interrupt)


def ignore_signals_until_restored() -> None:
    for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        signal.signal(sig, signal.SIG_IGN)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run one command as a given GitHub account, then put the previous account back.",
        epilog="Exit code: the command's own, or 3 when the switch or the restore failed. "
               "The lock serializes only callers of this wrapper.")
    parser.add_argument("--user", required=True)
    parser.add_argument("--hostname", default="github.com")
    parser.add_argument("--timeout", type=float, default=600, help="seconds to wait for the lock")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("name the command after --")

    LOCK.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(LOCK, os.O_RDWR | os.O_CREAT, 0o600)
    deadline = time.monotonic() + args.timeout
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            if time.monotonic() > deadline:
                print("with_account: another account switch is still running", file=sys.stderr)
                return 3
            time.sleep(0.1)

    previous = active(args.hostname)
    if previous is None:
        print(f"with_account: no active gh account on {args.hostname}; log in first", file=sys.stderr)
        return 3

    route_termination_to_restore()
    code = 3
    try:
        if previous != args.user and not switch(args.hostname, args.user):
            print(f"with_account: could not switch to {args.user}; it may need `gh auth login`", file=sys.stderr)
        else:
            code = subprocess.run(command).returncode
    except KeyboardInterrupt:
        code = 130
    finally:
        ignore_signals_until_restored()
        now = active(args.hostname)
        if now != previous:
            restored = switch(args.hostname, previous)
            print(f"with_account: switched {previous} -> {now or 'unknown'} -> "
                  f"{previous if restored else 'RESTORE FAILED'}", file=sys.stderr)
            if not restored:
                print(f"with_account: run `gh auth switch --user {previous}` now", file=sys.stderr)
                code = 3
        elif previous != args.user and code != 3:
            print(f"with_account: switched {previous} -> {args.user} -> {previous}", file=sys.stderr)
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    return code


if __name__ == "__main__":
    sys.exit(main())
