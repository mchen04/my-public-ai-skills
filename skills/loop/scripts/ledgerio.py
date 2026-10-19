#!/usr/bin/env python3

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

LOCK_TIMEOUT = 60.0
RECEIPT_KIND = "check-receipt"
INDEX = "index.jsonl"
VERDICT_LINE = re.compile(r"^VERDICT:\s*([A-Z]+)\s*$")
_held: dict[str, int] = {}


class LedgerBusy(RuntimeError):
    pass


@contextlib.contextmanager
def locked(path: Path, timeout: float = LOCK_TIMEOUT):
    key = str(Path(path).absolute())
    if key in _held:
        _held[key] += 1
        try:
            yield
        finally:
            _held[key] -= 1
        return
    lock_path = Path(key + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise LedgerBusy(f"{path} stayed locked by another writer for {timeout:.0f}s") from None
                time.sleep(0.02)
        _held[key] = 1
        try:
            yield
        finally:
            del _held[key]
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def atomic_write(path: Path, text: str) -> None:
    target = Path(os.path.realpath(path))
    target.parent.mkdir(parents=True, exist_ok=True)
    mode = target.stat().st_mode & 0o777 if target.exists() else None
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, target)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise
    with contextlib.suppress(OSError):
        dir_fd = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)


def append_line(path: Path, line: str, header: str | None = None) -> None:
    old = Path(path).read_text(encoding="utf-8") if Path(path).exists() else (header or "")
    if old and not old.endswith("\n"):
        old += "\n"
    atomic_write(path, old + line.rstrip("\n") + "\n")


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, timeout=120,
                          stdin=subprocess.DEVNULL, env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"})


def _z(out: bytes) -> list[str]:
    return [p for p in out.decode("utf-8", "surrogateescape").split("\0") if p]


def _blob(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def worktree_revision(repo: Path) -> dict | None:
    top = _git(Path(repo), "rev-parse", "--show-toplevel")
    if top.returncode:
        return None
    root = Path(top.stdout.decode().strip())
    head = _git(root, "rev-parse", "HEAD")
    head_sha = head.stdout.decode().strip() if head.returncode == 0 else "none"
    entries: dict[str, tuple[str, str]] = {}
    for item in _z(_git(root, "ls-files", "-s", "-z").stdout):
        meta, _, path = item.partition("\t")
        mode, sha, _stage = meta.split()
        entries[path] = (mode, sha)
    deleted = set(_z(_git(root, "ls-files", "-d", "-z").stdout))
    changed = set(_z(_git(root, "ls-files", "-m", "-z").stdout))
    changed |= set(_z(_git(root, "ls-files", "-o", "--exclude-standard", "-z").stdout))
    for path in deleted:
        entries.pop(path, None)
    for path in changed - deleted:
        full = root / path
        if full.is_symlink():
            entries[path] = ("120000", _blob(os.readlink(full).encode("utf-8", "surrogateescape")))
        elif full.is_dir():
            sub = _git(full, "rev-parse", "HEAD")
            entries[path] = ("160000", sub.stdout.decode().strip() or "unknown")
        elif full.is_file():
            mode = "100755" if os.access(full, os.X_OK) else "100644"
            entries[path] = (mode, _blob(full.read_bytes()))
    digest = hashlib.sha256()
    for path in sorted(entries):
        mode, sha = entries[path]
        digest.update(f"{mode} {sha} {path}\0".encode("utf-8", "surrogateescape"))
    content = digest.hexdigest()
    return {"root": str(root), "head": head_sha, "content": content, "id": f"{head_sha[:12]}+{content[:12]}"}


def _digest(receipt: dict) -> str:
    body = {k: v for k, v in receipt.items() if k != "digest"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def observed_verdict(exit_code: int | None, stdout: str, passing: set, failing: set) -> tuple[str, str | None]:
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    match = VERDICT_LINE.match(lines[-1]) if lines else None
    token = match.group(1) if match else None
    if exit_code is None:
        return "INDETERMINATE", token
    if token in passing:
        return ("PASS" if exit_code == 0 else "INDETERMINATE"), token
    if token in failing:
        return "FAIL", token
    if token is not None:
        return "INDETERMINATE", token
    return ("PASS" if exit_code == 0 else "FAIL"), None


def run_check(argv: list[str], *, repo: Path, out_dir: Path, observer: str, passing: set,
              failing: set, timeout: float = 3600, cwd: Path | None = None,
              env: dict | None = None, label: str | None = None) -> tuple[Path, dict]:
    if not argv:
        raise ValueError("check needs a command after --")
    before = worktree_revision(repo)
    if before is None:
        raise ValueError(f"{repo} is not a git worktree; a receipt needs a revision to bind to")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc)
    rid = stamp.strftime("%Y%m%dT%H%M%S") + "-" + hashlib.sha256(os.urandom(16)).hexdigest()[:8]
    started = time.monotonic()
    timed_out = False
    try:
        done = subprocess.run(argv, cwd=str(cwd or before["root"]), capture_output=True, timeout=timeout,
                              stdin=subprocess.DEVNULL, env=env)
        exit_code, stdout, stderr = done.returncode, done.stdout, done.stderr
    except subprocess.TimeoutExpired as stop:
        timed_out, exit_code = True, None
        stdout, stderr = stop.stdout or b"", stop.stderr or b""
    except OSError as error:
        exit_code, stdout, stderr = 127, b"", str(error).encode()
    duration = round(time.monotonic() - started, 3)
    after = worktree_revision(repo)
    streams = {}
    for name, data in (("stdout", stdout), ("stderr", stderr)):
        stream = out_dir / f"{rid}.{name}"
        stream.write_bytes(data)
        streams[name] = {"file": stream.name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
    observed, token = observed_verdict(exit_code, stdout.decode("utf-8", "replace"), passing, failing)
    receipt = {
        "format": 1,
        "kind": RECEIPT_KIND,
        "observer": observer,
        "label": label,
        "argv": list(argv),
        "started": stamp.isoformat(timespec="seconds"),
        "duration_s": duration,
        "exit": exit_code,
        "timed_out": timed_out,
        "verdict_token": token,
        "observed": observed,
        "revision": before,
        "revision_after": after,
        "stable": bool(after) and after["content"] == before["content"],
        **streams,
    }
    receipt["digest"] = _digest(receipt)
    path = out_dir / f"{rid}.json"
    index = out_dir / INDEX
    with locked(index):
        atomic_write(path, json.dumps(receipt, indent=2, sort_keys=True) + "\n")
        append_line(index, json.dumps({"receipt": path.name, "digest": receipt["digest"]}, sort_keys=True))
    return path, receipt


def load_receipt(path: Path) -> dict | None:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("kind") == RECEIPT_KIND else None


def looks_like_receipt(path: Path) -> bool:
    return Path(path).suffix == ".json" and load_receipt(path) is not None


def receipt_problems(path: Path, *, repo: Path | None, expect: str | None = None,
                     require_fresh: bool = False) -> list[str]:
    path = Path(path)
    receipt = load_receipt(path)
    if receipt is None:
        return [f"{path.name} is missing or is not a check receipt"]
    problems = []
    if receipt.get("digest") != _digest(receipt):
        problems.append(f"{path.name} was edited after it was written (digest mismatch)")
    index = path.parent / INDEX
    listed = []
    if index.is_file():
        for line in index.read_text(encoding="utf-8").splitlines():
            with contextlib.suppress(ValueError):
                entry = json.loads(line)
                if entry.get("receipt") == path.name:
                    listed.append(entry.get("digest"))
    if receipt.get("digest") not in listed:
        problems.append(f"{path.name} is not in its folder's receipt index; it was not written by a check run")
    for name in ("stdout", "stderr"):
        meta = receipt.get(name) or {}
        stream = path.parent / str(meta.get("file", ""))
        if not meta.get("file") or not stream.is_file():
            problems.append(f"{path.name}: its {name} capture is missing")
        elif _sha_file(stream) != meta.get("sha256"):
            problems.append(f"{path.name}: its {name} capture was changed after the run")
    if not receipt.get("stable"):
        problems.append(f"{path.name}: the worktree changed while the check ran, so the result binds to no revision")
    if expect and receipt.get("observed") != expect:
        problems.append(f"{path.name} observed {receipt.get('observed')}, not {expect}")
    if require_fresh:
        current = worktree_revision(repo) if repo is not None else None
        observed_rev = (receipt.get("revision") or {})
        if current is None:
            problems.append(f"{path.name}: the current revision is unknown, so freshness cannot be checked")
        elif observed_rev.get("content") != current["content"]:
            problems.append(f"{path.name} is stale: it observed {observed_rev.get('id')}, the worktree is now {current['id']}")
    return problems


def receipt_tag(path: Path) -> str:
    receipt = load_receipt(path) or {}
    return f"receipt:{Path(path).name}#{str(receipt.get('digest', ''))[:12]}"
