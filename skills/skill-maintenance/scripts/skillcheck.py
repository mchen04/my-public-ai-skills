#!/usr/bin/env python3
import os
import re
import sys

USAGE = """usage: skillcheck.py <path-to-skill-folder>

Portable shape validation for one Agent Skill folder, stdlib only.
Exit 0 clean, 1 violations, 2 usage error."""

STANDARD_DIRS = {"scripts", "references", "assets", "agents"}
OPTIONAL_KEYS = {"license", "metadata", "allowed-tools"}
NAME_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
RESERVED_NAME_WORDS = ("anthropic", "claude")


def parse_frontmatter(text):
    m = re.match(r"\A---\n(.*?)\n---\n", text, re.S)
    if not m:
        return None
    keys = {}
    current = None
    for line in m.group(1).splitlines():
        km = re.match(r"^([A-Za-z_-]+):\s*(.*)$", line)
        if km:
            current = km.group(1)
            keys[current] = km.group(2).lstrip(">|").strip()
        elif current and (line.startswith("  ") or line.startswith("\t")):
            keys[current] = (keys[current] + " " + line.strip()).strip()
    return keys



def plain_scalar_problems(text):
    match = re.match(r"\A---\n(.*?)\n---\n", text, re.S)
    if not match:
        return []
    problems = []
    for number, line in enumerate(match.group(1).splitlines(), 2):
        field = re.match(r"^\s*[A-Za-z0-9_-]+:\s*(.*)$", line)
        if not field:
            continue
        value = field.group(1).strip()
        if not value or value[0] in "\"'" or re.fullmatch(r"[>|][+-]?", value):
            continue
        if ": " in value or " #" in value or value[0] in "!&*{}[],#?%@`:-|>":
            problems.append(f"{number}: unsafe YAML plain scalar; fold it with > or quote the whole value")
    return problems


def main():
    if len(sys.argv) != 2:
        print(USAGE, file=sys.stderr)
        return 2
    folder = os.path.abspath(sys.argv[1].rstrip("/"))
    skill_md = os.path.join(folder, "SKILL.md")
    problems = []

    if not os.path.isfile(skill_md):
        print(f"FAIL: no SKILL.md in {folder}")
        return 1
    text = open(skill_md).read()

    problems.extend(f"{skill_md}:{problem}" for problem in plain_scalar_problems(text))
    fm = parse_frontmatter(text)
    if fm is None:
        problems.append("no valid frontmatter block")
        fm = {}
    extras = set(fm) - {"name", "description"} - OPTIONAL_KEYS
    if extras:
        problems.append(f"unsupported frontmatter keys: {', '.join(sorted(extras))}")
    name = fm.get("name", "")
    if not name:
        problems.append("missing frontmatter `name`")
    else:
        if name != os.path.basename(folder):
            problems.append(f"name `{name}` != folder `{os.path.basename(folder)}`")
        if len(name) > 64 or not NAME_RE.fullmatch(name):
            problems.append(f"name `{name}`: use <= 64 lowercase letters and digits, joined by single hyphens")
        reserved = [word for word in RESERVED_NAME_WORDS if word in name]
        if reserved:
            problems.append(f"name `{name}` contains reserved word {reserved[0]!r}")
    desc = fm.get("description", "")
    if not desc:
        problems.append("missing frontmatter `description`")
    else:
        if len(desc) > 1024:
            problems.append(f"description {len(desc)} chars (> 1024)")
        if "<" in desc or ">" in desc:
            problems.append("description contains < or >; reword without angle brackets")

    body_lines = text.count("\n")

    for entry in sorted(os.listdir(folder)):
        full = os.path.join(folder, entry)
        if entry == "SKILL.md" or entry.startswith("."):
            continue
        if os.path.isdir(full):
            if entry not in STANDARD_DIRS and entry != "__pycache__":
                problems.append(f"non-standard directory: {entry}/")
        else:
            problems.append(f"stray root file: {entry}")

    if problems:
        print(f"FAIL: {os.path.basename(folder)}")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"ok: {os.path.basename(folder)} ({body_lines} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
