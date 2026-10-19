#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


REDACTION = "[REDACTED]"
MAX_TEXT_BYTES = 10 * 1024 * 1024
MAX_REPORTED_FINDINGS = 100

SENSITIVE_KEY = (
    r"api[_-]?key|access[_-]?token|auth[_-]?token|bearer[_-]?token|client[_-]?secret|"
    r"database[_-]?url|db[_-]?url|password|passwd|private[_-]?key|secret|token"
)

CREDENTIAL_URL_RE = re.compile(
    r"(?i)\b(?P<scheme>[a-z][a-z0-9+.-]*://)"
    r"(?P<user>[^/\s:@'\"<>]+):(?P<secret>[^@\s/'\"<>]+)@"
    r"(?P<host>\[[^\]\s/'\"<>]+\]|[^:/\s/'\"<>]+)"
)
PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN (?P<label>(?:[A-Z0-9]+ )?PRIVATE KEY)-----"
    r"(?P<body>.*?)"
    r"-----END (?P=label)-----",
    re.DOTALL,
)
QUOTED_VALUE_RE = re.compile(
    rf"(?i)(?<![A-Za-z0-9_-])(?P<prefix>(?:[\"']?)(?:{SENSITIVE_KEY})"
    r"(?![A-Za-z0-9_-])(?:[\"']?)\s*[:=]\s*"
    r"(?P<quote>[\"']))(?P<secret>[^\"'\r\n]*)(?P=quote)"
)
CONFIG_VALUE_RE = re.compile(
    rf"(?im)^(?P<prefix>[ \t]*(?:export[ \t]+)?(?:{SENSITIVE_KEY})[ \t]*[:=][ \t]*)"
    r"(?P<secret>[^#\r\n]+?)(?P<suffix>[ \t]*(?:#.*)?)$"
)

TOKEN_PATTERNS = (
    (
        "provider-token",
        re.compile(r"\bsk-(?:proj-|ant-[A-Za-z0-9-]*-)?[A-Za-z0-9_-]{16,}\b"),
    ),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("github-token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{16,}\b")),
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    (
        "jwt",
        re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    ),
)

CONFIG_NAMES = {".env", ".npmrc", ".pypirc", ".netrc"}
CONFIG_SUFFIXES = {".env", ".ini", ".cfg", ".conf", ".toml", ".yaml", ".yml", ".properties"}
LOOPBACK_DATABASE_SCHEMES = {"mariadb", "mysql", "postgres", "postgresql"}
LOOPBACK_HOSTS = {"127.0.0.1", "[::1]", "localhost"}
MIN_GENERIC_QUOTED_SECRET_LENGTH = 4


@dataclass(frozen=True)
class Finding:
    kind: str
    line: int


class ScanError(RuntimeError):
    pass


def run_git(repo: Path, *args: str, allow_failure: bool = False) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        check=False,
    )
    if result.returncode and not allow_failure:
        raise ScanError(f"git {' '.join(args[:2])} failed")
    return result


def repo_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise ScanError("not inside a git repository")
    return Path(result.stdout.strip()).resolve()


def nul_paths(data: bytes) -> list[str]:
    return [part.decode("utf-8", "surrogateescape") for part in data.split(b"\0") if part]


def changed_worktree_paths(repo: Path) -> tuple[list[str], list[str]]:
    worktree = set(
        nul_paths(run_git(repo, "diff", "--name-only", "-z", "--diff-filter=ACMR").stdout)
    )
    worktree.update(
        nul_paths(run_git(repo, "ls-files", "--others", "--exclude-standard", "-z").stdout)
    )
    staged = set(
        nul_paths(
            run_git(repo, "diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR").stdout
        )
    )
    return sorted(worktree), sorted(staged)


def is_config_path(path: str) -> bool:
    name = Path(path).name.lower()
    return name in CONFIG_NAMES or name.startswith(".env.") or Path(name).suffix in CONFIG_SUFFIXES


def is_placeholder(value: str) -> bool:
    candidate = value.strip().strip("'\"").strip()
    lowered = candidate.lower()
    if not candidate or REDACTION.lower() in lowered:
        return True
    if lowered.startswith(
        ("$", "{", "<", "env.", "os.environ", "process.env", "keychain", "your_", "your-")
    ):
        return True
    return bool(
        re.fullmatch(
            r"(?:your[-_ ]?)?(?:example|sample|placeholder|dummy|fake|test|changeme|replace[-_ ]?me)"
            r"(?:[-_ ].*)?",
            lowered,
        )
    )


def is_loopback_default_database_url(match: re.Match[str]) -> bool:
    scheme = match.group("scheme").removesuffix("://").lower()
    host = match.group("host").lower()
    return (
        scheme in LOOPBACK_DATABASE_SCHEMES
        and host in LOOPBACK_HOSTS
        and match.group("user") == match.group("secret")
    )


def is_high_confidence_quoted_secret(value: str) -> bool:
    candidate = value.strip()
    return len(candidate) >= MIN_GENERIC_QUOTED_SECRET_LENGTH and not is_placeholder(candidate)


def line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def is_conditional_key_choice(text: str, offset: int) -> bool:
    line_start = text.rfind("\n", 0, offset) + 1
    before = text[line_start:offset].rstrip()
    if "?" not in before or not before.endswith(("?", ":")):
        return False
    branch = before[before.rindex("?") + 1:]
    return not any(token in branch for token in (",", ";", "="))


def findings_for(text: str, path: str) -> list[Finding]:
    findings: set[Finding] = set()

    for match in CREDENTIAL_URL_RE.finditer(text):
        if not is_placeholder(match.group("secret")) and not is_loopback_default_database_url(match):
            findings.add(Finding("credential-url", line_number(text, match.start("secret"))))

    for match in PRIVATE_KEY_RE.finditer(text):
        if not is_placeholder(match.group("body")):
            findings.add(Finding("private-key", line_number(text, match.start())))

    for match in QUOTED_VALUE_RE.finditer(text):
        if (
            not is_conditional_key_choice(text, match.start())
            and is_high_confidence_quoted_secret(match.group("secret"))
        ):
            findings.add(Finding("secret-assignment", line_number(text, match.start("secret"))))

    if is_config_path(path):
        for match in CONFIG_VALUE_RE.finditer(text):
            if not is_placeholder(match.group("secret")):
                findings.add(Finding("secret-assignment", line_number(text, match.start("secret"))))

    for kind, pattern in TOKEN_PATTERNS:
        for match in pattern.finditer(text):
            if not is_placeholder(match.group(0)):
                findings.add(Finding(kind, line_number(text, match.start())))

    return sorted(findings, key=lambda finding: (finding.line, finding.kind))


def redact_text(text: str, path: str) -> tuple[str, int]:
    redactions = 0

    def redact_url(match: re.Match[str]) -> str:
        nonlocal redactions
        if is_placeholder(match.group("secret")) or is_loopback_default_database_url(match):
            return match.group(0)
        redactions += 1
        return (
            f"{match.group('scheme')}{match.group('user')}:{REDACTION}@{match.group('host')}"
        )

    def redact_private_key(match: re.Match[str]) -> str:
        nonlocal redactions
        if is_placeholder(match.group("body")):
            return match.group(0)
        redactions += 1
        label = match.group("label")
        return f"-----BEGIN {label}-----\n{REDACTION}\n-----END {label}-----"

    def redact_quoted_value(match: re.Match[str]) -> str:
        nonlocal redactions
        if not is_high_confidence_quoted_secret(match.group("secret")):
            return match.group(0)
        redactions += 1
        return f"{match.group('prefix')}{REDACTION}{match.group('quote')}"

    def redact_config_value(match: re.Match[str]) -> str:
        nonlocal redactions
        if is_placeholder(match.group("secret")):
            return match.group(0)
        redactions += 1
        return f"{match.group('prefix')}{REDACTION}{match.group('suffix')}"

    text = CREDENTIAL_URL_RE.sub(redact_url, text)
    text = PRIVATE_KEY_RE.sub(redact_private_key, text)
    text = QUOTED_VALUE_RE.sub(redact_quoted_value, text)
    if is_config_path(path):
        text = CONFIG_VALUE_RE.sub(redact_config_value, text)

    for _, pattern in TOKEN_PATTERNS:
        def redact_token(match: re.Match[str]) -> str:
            nonlocal redactions
            if is_placeholder(match.group(0)):
                return match.group(0)
            redactions += 1
            return REDACTION

        text = pattern.sub(redact_token, text)

    return text, redactions


def decode_text(data: bytes) -> str | None:
    if b"\0" in data:
        return None
    if len(data) > MAX_TEXT_BYTES:
        raise ScanError(f"text file exceeds {MAX_TEXT_BYTES} bytes")
    return data.decode("utf-8", "surrogateescape")


def display_path(path: str) -> str:
    return json.dumps(path, ensure_ascii=True)


def report_findings(records: list[tuple[str, Finding]], scope: str) -> int:
    for location, finding in records[:MAX_REPORTED_FINDINGS]:
        print(f"finding {display_path(location)}:{finding.line} {finding.kind}")
    if len(records) > MAX_REPORTED_FINDINGS:
        print(f"finding output capped; {len(records) - MAX_REPORTED_FINDINGS} more")
    print(f"secret scan: {len(records)} finding(s) in {scope}; values withheld")
    return 2 if records else 0


def check_working_tree(repo: Path) -> int:
    records: list[tuple[str, Finding]] = []
    scanned = 0
    worktree_paths, staged_paths = changed_worktree_paths(repo)
    for relative in worktree_paths:
        path = repo / relative
        if path.is_symlink():
            data = os.fsencode(os.readlink(path))
        elif path.is_file():
            data = path.read_bytes()
        else:
            continue
        text = decode_text(data)
        if text is None:
            continue
        scanned += 1
        records.extend((relative, finding) for finding in findings_for(text, relative))
    for relative in staged_paths:
        blob = run_git(repo, "cat-file", "-p", f":{relative}", allow_failure=True)
        if blob.returncode:
            continue
        text = decode_text(blob.stdout)
        if text is None:
            continue
        scanned += 1
        location = f"staged:{relative}"
        records.extend((location, finding) for finding in findings_for(text, relative))
    if records:
        return report_findings(records, "working tree/index")
    print(f"secret scan: clean ({scanned} changed text snapshot(s))")
    return 0


def redact_paths(repo: Path, paths: list[str]) -> int:
    total = 0
    for raw_path in paths:
        candidate = Path(raw_path)
        unresolved = candidate if candidate.is_absolute() else repo / candidate
        path = Path(os.path.abspath(unresolved))
        try:
            relative_path = path.relative_to(repo)
            relative = relative_path.as_posix()
        except ValueError as error:
            raise ScanError(f"refusing path outside repository: {display_path(raw_path)}") from error
        component = repo
        for part in relative_path.parts:
            component /= part
            if component.is_symlink():
                raise ScanError(f"refusing symlink path: {display_path(relative)}")
        if not path.is_file():
            raise ScanError(f"not a regular file: {display_path(relative)}")
        original_bytes = path.read_bytes()
        original = decode_text(original_bytes)
        if original is None:
            raise ScanError(f"refusing binary file: {display_path(relative)}")
        redacted, count = redact_text(original, relative)
        if not count:
            print(f"redacted {display_path(relative)}: 0 value(s)")
            continue

        mode = stat.S_IMODE(path.stat().st_mode)
        encoded = redacted.encode("utf-8", "surrogateescape")
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
            temporary.write(encoded)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        os.chmod(temporary_path, mode)
        os.replace(temporary_path, path)
        total += count
        print(f"redacted {display_path(relative)}: {count} value(s)")

    print(f"secret redaction: {total} value(s); values withheld")
    return 0


HUNK_HEADER_RE = re.compile(rb"^@@ -\d+(?:,\d+)? \+(?P<line>\d+)(?:,\d+)? @@")


def added_text(repo: Path, parent: str, commit: str, relative: str) -> str | None:
    patch = run_git(
        repo,
        "diff",
        "--no-ext-diff",
        "--no-color",
        "--unified=0",
        parent,
        commit,
        "--",
        relative,
    ).stdout
    additions: dict[int, bytes] = {}
    new_line: int | None = None
    for line in patch.splitlines():
        header = HUNK_HEADER_RE.match(line)
        if header:
            new_line = int(header.group("line"))
            continue
        if new_line is None or line.startswith(b"\\ No newline"):
            continue
        if line.startswith(b"+") and not line.startswith(b"+++"):
            additions[new_line] = line[1:]
            new_line += 1
        elif line.startswith(b"-") and not line.startswith(b"---"):
            continue
        elif line.startswith(b" "):
            new_line += 1
    if not additions:
        return ""
    data = b"\n".join(additions.get(line, b"") for line in range(1, max(additions) + 1))
    return decode_text(data)


def check_range(repo: Path, revision_range: str) -> int:
    commits_result = run_git(repo, "rev-list", "--reverse", revision_range, allow_failure=True)
    if commits_result.returncode:
        raise ScanError(f"invalid git range: {revision_range}")
    commits = [line for line in commits_result.stdout.decode("ascii", "strict").splitlines() if line]
    records: list[tuple[str, Finding]] = []
    scanned = 0
    for commit in commits:
        parents = run_git(repo, "rev-list", "--parents", "-n", "1", commit).stdout.split()
        parent_commits = [parent.decode("ascii", "strict") for parent in parents[1:]]
        paths = nul_paths(
            run_git(
                repo,
                "diff-tree",
                "--root",
                "--no-commit-id",
                "-m",
                "--name-only",
                "-r",
                "-z",
                "--diff-filter=ACMR",
                commit,
            ).stdout
        )
        for relative in paths:
            texts: list[str] = []
            if parent_commits:
                for parent in parent_commits:
                    text = added_text(repo, parent, commit, relative)
                    if text is not None:
                        texts.append(text)
            else:
                blob = run_git(repo, "cat-file", "-p", f"{commit}:{relative}", allow_failure=True)
                if not blob.returncode:
                    text = decode_text(blob.stdout)
                    if text is not None:
                        texts.append(text)
            location = f"{commit[:12]}:{relative}"
            path_findings: set[Finding] = set()
            for text in texts:
                scanned += 1
                path_findings.update(findings_for(text, relative))
            records.extend((location, finding) for finding in sorted(
                path_findings,
                key=lambda finding: (finding.line, finding.kind),
            ))
    if records:
        return report_findings(records, f"{len(commits)} outgoing commit(s)")
    print(f"secret scan: clean ({len(commits)} commit(s), {scanned} text snapshot(s))")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Detect or redact high-confidence secrets without printing values."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("check-working-tree", help="scan changed and untracked text files")
    range_parser = subparsers.add_parser("check-range", help="scan additions in every commit in a git range")
    range_parser.add_argument("revision_range")
    redact_parser = subparsers.add_parser("redact", help="redact exact repository-relative files")
    redact_parser.add_argument("paths", nargs="+")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        repo = repo_root()
        if args.command == "check-working-tree":
            return check_working_tree(repo)
        if args.command == "check-range":
            return check_range(repo, args.revision_range)
        return redact_paths(repo, args.paths)
    except ScanError as error:
        print(f"secret scan error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
