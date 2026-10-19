#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCANNER_PATH = ROOT / "skills/safe-push/scripts/redact-secrets.py"
SPEC = importlib.util.spec_from_file_location("public_secret_scanner", SCANNER_PATH)
SCANNER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = SCANNER
SPEC.loader.exec_module(SCANNER)
HOME_PATH = re.compile(r"/(?:Users|home)/[A-Za-z0-9_.-]+(?:/|\b)")
LOCAL_LINK = re.compile(r"\[[^\]]*\]\(([^\s)]+)\)")
PRIVATE_NAMES = {".env", ".netrc", ".npmrc", "credentials.json", "auth.json", "config.yaml"}
PRIVATE_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".sqlite", ".db", ".jsonl"}


def tracked_and_new(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        capture_output=True, check=True,
    )
    return sorted({root / name.decode() for name in result.stdout.split(b"\0") if name})


def text_problems(name: str, text: str) -> list[str]:
    findings = [f"{name}:{finding.line}: {finding.kind}" for finding in SCANNER.findings_for(text, name)]
    for match in HOME_PATH.finditer(text):
        findings.append(f"{name}:{text.count(chr(10), 0, match.start()) + 1}: personal-home-path")
    return findings


def check(root: Path) -> list[str]:
    problems = []
    files = tracked_and_new(root)
    for path in files:
        name = path.relative_to(root).as_posix()
        if not path.exists() and not path.is_symlink():
            continue
        if path.is_symlink():
            problems.append(f"{name}: symlinks must not enter the public bundle")
            continue
        if not path.is_file():
            problems.append(f"{name}: unsupported file type")
            continue
        if path.name in PRIVATE_NAMES or path.name.startswith(".env.") or path.suffix in PRIVATE_SUFFIXES:
            problems.append(f"{name}: private configuration or runtime artifact")
        if path.stat().st_size > 512 * 1024:
            problems.append(f"{name}: too large for the reviewed text bundle")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeError:
            problems.append(f"{name}: only UTF-8 text belongs in this bundle")
            continue
        if "\0" in text:
            problems.append(f"{name}: binary content")
            continue
        problems.extend(text_problems(name, text))
        if path.suffix == ".md":
            for match in LOCAL_LINK.finditer(text):
                link = match.group(1).split("#", 1)[0]
                if not link or re.match(r"[a-z][a-z0-9+.-]*:", link, re.I):
                    continue
                target = (path.parent / link).resolve()
                if root.resolve() not in target.parents or not target.exists():
                    problems.append(f"{name}: broken or external local link")
    readme = root / "README.md"
    skills = {path.parent.name for path in (root / "skills").glob("*/SKILL.md")}
    if not skills:
        problems.append("skills: empty catalog")
    if readme.exists():
        entries = re.findall(r"\[`([^`]+)`\]\(skills/[^)]+/SKILL\.md\)", readme.read_text())
        if set(entries) != skills or len(entries) != len(skills):
            problems.append("README.md: catalog must list each bundled skill exactly once")
    return problems


def selftest() -> int:
    cases = [
        ("sample.py", "value = 'ghp_" + "A" * 36 + "'"),
        ("notes.md", "/" + "Users/" + "private-person/project"),
        ("notes.md", "/" + "home/" + "private-person/project"),
    ]
    for name, text in cases:
        if not text_problems(name, text):
            raise SystemExit("public check failed to reject a planted disclosure")
    if text_problems("notes.md", "Use ~/project and keep credentials outside the repository."):
        raise SystemExit("public check rejected a generic path")
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        skill = root / "skills/demo"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("---\nname: demo\ndescription: Demonstrate a check.\n---\n# Demo\n")
        (root / "README.md").write_text("[`demo`](skills/demo/SKILL.md)\n")
        if check(root):
            raise SystemExit("public check rejected a clean bundle")
        (root / "README.md").write_text("[`demo`](skills/demo/SKILL.md)\n[Missing](missing.md)\n")
        if not check(root):
            raise SystemExit("public check accepted a missing reference")
        (root / "README.md").write_text("[`demo`](skills/demo/SKILL.md)\n")
        (root / "local-link").symlink_to(skill)
        if not check(root):
            raise SystemExit("public check accepted a symlink")
        (root / "local-link").unlink()
        (root / "auth.json").write_text("{}")
        if not check(root):
            raise SystemExit("public check accepted a credential store")
    print("public_check_selftest_ok: planted disclosures and unsafe bundles are rejected")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Check the public text bundle without printing secret values.")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        return selftest()
    problems = check(ROOT)
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    print("public_check_ok: secret patterns, personal home paths, bundle files, catalog, and links")
    return 0


if __name__ == "__main__":
    sys.exit(main())
