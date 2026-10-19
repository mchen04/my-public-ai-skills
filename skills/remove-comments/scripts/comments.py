#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import bisect
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tokenize
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import notes

PYTHON_SUFFIXES = {".py", ".pyw", ".pyi"}
SHELL_SUFFIXES = {".sh", ".bash", ".ksh", ".dash"}
JS_SUFFIXES = {".js", ".mjs", ".cjs"}
TS_SUFFIXES = {".ts", ".mts", ".cts"}
HAND_ONLY = {
    ".jsx": "JSX text can contain comment-like text",
    ".tsx": "JSX text can contain comment-like text",
    ".zsh": "zsh glob flags use #",
    ".pyx": "Cython syntax",
    ".ipynb": "notebook JSON",
}
OTHER_CODE_SUFFIXES = {
    ".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".hh", ".m", ".mm", ".go", ".rs", ".java", ".kt",
    ".kts", ".scala", ".swift", ".cs", ".fs", ".rb", ".php", ".pl", ".pm", ".lua", ".r", ".jl",
    ".dart", ".ex", ".exs", ".erl", ".hs", ".clj", ".sql", ".css", ".scss", ".sass", ".less",
    ".html", ".htm", ".xml", ".vue", ".svelte", ".astro", ".yaml", ".yml", ".toml", ".ini",
    ".cfg", ".conf", ".tf", ".hcl", ".proto", ".graphql", ".gql", ".ps1", ".bat", ".cmd",
    ".fish", ".nix", ".cmake", ".gradle", ".groovy", ".vim", ".el", ".zig", ".nim", ".mk",
}
OTHER_CODE_NAMES = {
    "Makefile", "GNUmakefile", "Dockerfile", "Containerfile", "Justfile", "Rakefile", "Gemfile",
    "CMakeLists.txt", "BUILD", "BUILD.bazel", "WORKSPACE", "Vagrantfile", "Brewfile",
}
PROSE_SUFFIXES = {".md", ".markdown", ".mdx", ".rst", ".txt", ".adoc", ".org"}
SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "bower_components", "vendor", "third_party",
    "third-party", "site-packages", ".venv", "venv", "__pycache__", ".tox", ".nox",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build", ".next", ".nuxt",
    "coverage", ".gradle", "target", "Pods",
}
HEAVY_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "bower_components", "site-packages", ".venv", "venv",
    "__pycache__", ".tox", ".nox", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".next", ".nuxt",
    ".gradle", "Pods",
}
GENERATED = re.compile(r"@generated|DO NOT EDIT|Code generated|auto-?generated", re.IGNORECASE)
LICENSE = re.compile(
    r"copyright|\(c\)|\u00a9|\blicen[cs]e|spdx-license-identifier|all rights reserved|@preserve|@license",
    re.IGNORECASE,
)
DIRECTIVE = re.compile(
    "|".join([
        r"\bnoqa\b", r"\bnosec\b", r"\bNOSONAR\b", r"\bNOLINT", r"\bnolint\b", r"\bnoinspection\b",
        r"\bpragma\b", r"^\s*type:\s*\S",
        r"\b(pylint|pyright|mypy|pytype|ruff|flake8|isort|yapf|pydocstyle|bandit|coverage):",
        r"\bpyre-\w", r"\bfmt:\s*(off|on|skip)\b", r"\bcython:", r"\bdistutils:", r"\bnuitka-",
        r"\bshellcheck\s", r"\bshfmt:", r"\bbats\s+test_tags\b",
        r"\beslint(-disable|-enable|-env)?\b", r"^\s*(globals?|exported)\s", r"\bjshint\b",
        r"\bjslint\b", r"\bprettier-ignore\b", r"\bbiome-ignore\b", r"\bdeno-(lint|fmt)-ignore",
        r"\btslint:", r"\bstylelint-", r"@ts-(ignore|expect-error|nocheck|check)\b",
        r"^/\s*<(reference|amd-module|amd-dependency)\b", r"@jsx(ImportSource|Runtime|Frag)?\b",
        r"@(no)?flow\b", r"\b(istanbul|c8|v8)\s+ignore\b", r"\bwebpack[A-Z]\w*\s*:",
        r"@vite-ignore", r"[#@]__(PURE|NO_SIDE_EFFECTS|INLINE|NOINLINE|KEY)__",
        r"[#@]\s*source(MappingURL|URL)=", r"@(no)?format\b", r"\bcspell:", r"\bcodespell:",
        r"\bclang-format\b", r"\bgitleaks:allow\b", r"\bcheckov:skip\b", r"\btfsec:ignore\b",
        r"-\*-.*-\*-", r"(^|\s)vim?:\s*(set?\s|\w+=)", r"\blanguage=\w",
    ])
)
CODING = re.compile(r"^[ \t\f]*#.*?coding[:=][ \t]*[-\w.]+")
JSDOC_TYPES = re.compile(
    r"@(type|typedef|template|callback|satisfies|import|enum|this|extends|augments|implements|overload)\b"
    r"|@(param|returns?|prop|property)\s*\{"
)
TS_INTERNAL = re.compile(r"@internal\b")
DOC_READER_MODULES = {
    "click", "typer", "fire", "docopt", "invoke", "plac", "argh", "ply", "tyro", "cyclopts",
    "clize", "defopt", "simple_parsing", "jsonargparse", "fastapi", "rest_framework", "flasgger",
    "graphene", "nox", "pydoc",
}
DOC_READER_CALLS = {"getdoc", "help"}
SOURCE_READER_CALLS = {"getcomments", "getsource", "getsourcelines", "findsource"}
SHELL_SELF_READ = re.compile(
    r"\b(grep|egrep|sed|awk|head|tail|cat|perl|less|more|cut|tr|wc)\b[^\n;|&]*?[\"']?(\$0\b|\$\{0\}|\$\{?BASH_SOURCE)"
    r"|<\s*[\"']?(\$0\b|\$\{0\}|\$\{?BASH_SOURCE)"
)
CHECKJS = re.compile(r'"checkJs"\s*:\s*true')
DOC_GENERATORS = (("conf.py", re.compile(r"autodoc|autoapi")), ("mkdocs.yml", re.compile(r"mkdocstrings")))
JS_PUNCTUATORS = [
    ">>>=", "...", "===", "!==", "**=", "<<=", ">>=", ">>>", "&&=", "||=", "??=", "=>", "==",
    "!=", "<=", ">=", "&&", "||", "??", "?.", "++", "--", "+=", "-=", "*=", "%=", "&=", "|=",
    "^=", "**", "<<", ">>",
]
REGEX_AFTER_WORDS = {
    "return", "typeof", "instanceof", "in", "of", "new", "delete", "void", "throw", "case", "do",
    "else", "yield", "await",
}
PAREN_KEYWORDS = {"if", "while", "for", "with"}
JS_NUMBER = re.compile(
    r"0[xXoObB][\da-fA-F_]+n?|(?:\d[\d_]*(?:\.[\d_]*)?|\.\d[\d_]*)(?:[eE][+-]?\d[\d_]*)?n?"
)
JS_IDENT = re.compile(r"[\w$\u0080-\uffff]+")
JS_NEWLINES = "\n\r\u2028\u2029"
PREVIEW = 70
OUTPUT_CAP = 300


class Unclear(Exception):
    pass


@dataclass
class Item:
    line: int
    kind: str
    action: str
    reason: str
    preview: str


@dataclass
class FileResult:
    path: str
    language: str
    status: str = "clean"
    reason: str = ""
    check: str = ""
    items: list = field(default_factory=list)
    new_text: Optional[str] = None
    encoding: str = "utf-8"
    clarity: list = field(default_factory=list)
    constraints: list = field(default_factory=list)
    suppressions: list = field(default_factory=list)

    def count(self, action: str, kind: Optional[str] = None) -> int:
        return sum(1 for item in self.items if item.action == action and (kind is None or item.kind == kind))


def preview(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= PREVIEW else flat[: PREVIEW - 3] + "..."


def split_lines(text: str) -> list:
    parts = text.split("\n")
    lines = [part + "\n" for part in parts[:-1]]
    if parts[-1]:
        lines.append(parts[-1])
    return lines


WORD_CHARS = re.compile(r"[\w$]")
OPERATOR_CHARS = set("+-*/%=<>!&|^~?:.")
CLOSERS = set(")]};,")


def needs_space(left: str, right: str) -> bool:
    if WORD_CHARS.match(left) and WORD_CHARS.match(right):
        return True
    return left in OPERATOR_CHARS and right in OPERATOR_CHARS


class Editor:
    def __init__(self, text: str):
        self.text = text
        self.lines = split_lines(text)
        self.starts = []
        offset = 0
        for line in self.lines:
            self.starts.append(offset)
            offset += len(line)
        self.drop = set()
        self.cuts = {}
        self.replace = {}

    def content(self, row: int) -> str:
        line = self.lines[row - 1]
        if line.endswith("\r\n"):
            return line[:-2]
        if line.endswith("\n"):
            return line[:-1]
        return line

    def ending(self, row: int) -> str:
        return self.lines[row - 1][len(self.content(row)):]

    def locate(self, offset: int) -> tuple:
        row = bisect.bisect_right(self.starts, offset)
        return row, offset - self.starts[row - 1]

    def blank(self, row: int) -> bool:
        return not self.content(row).strip()

    def owns(self, start_row: int, start_col: int, end_row: int, end_col: int) -> bool:
        return not self.content(start_row)[:start_col].strip() and not self.content(end_row)[end_col:].strip()

    def cut(self, row: int, start: int, end: int) -> None:
        line = self.content(row)
        before, after = line[:start], line[end:]
        replacement = ""
        if not after.strip():
            while start > 0 and line[start - 1] in " \t":
                start -= 1
            if start > 0 and line[start - 1] == "\\" and start < len(line) and line[start] in " \t":
                start += 1
            end = len(line)
        elif not before.strip():
            while end < len(line) and line[end] in " \t":
                end += 1
        elif before[-1:] in (" ", "\t") and after[:1] in (" ", "\t"):
            while end < len(line) and line[end] in " \t":
                end += 1
        elif before[-1:] in (" ", "\t") and after[:1] in CLOSERS:
            while start > 0 and line[start - 1] in " \t":
                start -= 1
        elif before[-1:] not in (" ", "\t") and after[:1] not in (" ", "\t"):
            replacement = " " if needs_space(before[-1], after[0]) else ""
        self.cuts.setdefault(row, []).append((start, end, replacement))

    def render(self) -> str:
        dropped = set(self.drop)
        changed = {}
        for row, cuts in self.cuts.items():
            if row in dropped or row in self.replace:
                continue
            line = self.content(row)
            for start, end, replacement in sorted(cuts, reverse=True):
                line = line[:start] + replacement + line[end:]
            if line.strip():
                changed[row] = line
            else:
                dropped.add(row)
        changed.update(self.replace)
        total = len(self.lines)
        tidy = set()
        row = 1
        while row <= total:
            if row not in dropped:
                row += 1
                continue
            last = row
            while last + 1 <= total and last + 1 in dropped:
                last += 1
            before, after = row - 1, last + 1
            while before >= 1 and (before in dropped or before in tidy):
                before -= 1
            opener = before >= 1 and (changed.get(before) or self.content(before)).rstrip().endswith((":", "{", "(", "["))
            before_blank = before < 1 or opener or (before not in changed and self.blank(before))
            if before < 1:
                while after <= total and after not in changed and self.blank(after):
                    tidy.add(after)
                    after += 1
            elif after <= total and after not in changed and self.blank(after) and before_blank:
                tidy.add(after)
            elif after > total and before >= 1 and before not in changed and self.blank(before):
                tidy.add(before)
            row = last + 1
        dropped |= tidy
        out = []
        for row in range(1, total + 1):
            if row in dropped:
                continue
            out.append(changed[row] + self.ending(row) if row in changed else self.lines[row - 1])
        return "".join(out)


def comment_body(text: str) -> str:
    for marker in ("//", "/*", "#"):
        if text.startswith(marker):
            text = text[len(marker):]
            break
    if text.endswith("*/"):
        text = text[:-2]
    return text


def is_directive(text: str) -> bool:
    body = comment_body(text)
    return bool(DIRECTIVE.search(body) or DIRECTIVE.search(text))


def mark_license_blocks(editor: Editor, comments: list) -> set:
    full_line = [c for c in comments if not c["text"].startswith("/*")
                 and editor.owns(c["row"], c["col"], c["end_row"], c["end_col"])]
    keep = set()
    block = []

    def flush():
        if any(LICENSE.search(c["text"]) for c in block):
            keep.update(c["id"] for c in block)

    for comment in full_line:
        if block and comment["row"] != block[-1]["end_row"] + 1:
            flush()
            block = []
        block.append(comment)
    flush()
    keep.update(c["id"] for c in comments if LICENSE.search(c["text"]))
    return keep


def license_or_directive(comment: dict, licensed: set) -> str:
    if LICENSE.search(comment["text"]):
        return "license or copyright notice"
    if is_directive(comment["text"]):
        return "tool directive"
    if comment["id"] in licensed:
        return "license or copyright notice"
    return ""


RESOLVABLE = ("warning constraint", "this file reads", "imported by", "doctest example")
RUNTIME_REASONS = ("this file reads", "imported by", "doctest example")


def new_sink() -> dict:
    return {"clarity": [], "constraints": [], "suppressions": [], "used": set()}


def resolve(reason: str, row: int, resolved: set, sink: dict) -> tuple:
    if reason.startswith(RESOLVABLE) and row in resolved:
        sink["used"].add(row)
        return "", reason
    return reason, ""


def note_flags(sink: dict, note: str, row: int, symbol: str, code: str, constraint: str) -> None:
    if constraint:
        status = "resolved and removed" if constraint == "resolved" else "kept until encoded"
        sink["constraints"].append({"line": row, "symbol": symbol, "status": status, "note": preview(note)})
        return
    suggestion = notes.clarity_flag(note, code, symbol)
    if suggestion:
        sink["clarity"].append({"line": row, "symbol": symbol, "suggestion": suggestion, "note": preview(note)})


def read_source(path: Path, language: str) -> tuple:
    data = path.read_bytes()
    if language == "python":
        encoding, _ = tokenize.detect_encoding(io.BytesIO(data).readline)
    else:
        encoding = "utf-8-sig" if data.startswith(b"\xef\xbb\xbf") else "utf-8"
    try:
        return data.decode(encoding), encoding
    except (UnicodeDecodeError, LookupError) as error:
        raise Unclear(f"cannot decode as {encoding}: {error}")


def char_col(line: str, byte_col: int) -> int:
    return len(line.encode("utf-8")[:byte_col].decode("utf-8", errors="ignore"))


def body_lists(tree: ast.AST):
    for node in ast.walk(tree):
        for name in ("body", "orelse", "finalbody"):
            body = getattr(node, name, None)
            if isinstance(body, list) and body and isinstance(body[0], ast.stmt):
                yield node, name, body


def is_string_statement(stmt: ast.stmt) -> bool:
    return isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str)


def owns_statement(editor: Editor, first: int, start_col: int, last: int, end_col: int) -> bool:
    suffix = editor.content(last)[end_col:].strip()
    return not editor.content(first)[:start_col].strip() and (not suffix or suffix.startswith("#"))


def expected_python_dump(text: str, removed: set) -> str:
    tree = parse_quietly(text)
    for node, name, body in list(body_lists(tree)):
        kept = [stmt for stmt in body if (stmt.lineno, stmt.col_offset) not in removed]
        if len(kept) != len(body):
            setattr(node, name, kept or ([] if isinstance(node, ast.Module) else [ast.Pass()]))
    return ast.dump(tree)


def parse_quietly(text: str) -> ast.AST:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return ast.parse(text)


def plan_python(text: str, guard: dict, resolved: set, sink: dict) -> tuple:
    try:
        tree = parse_quietly(text)
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (SyntaxError, tokenize.TokenError, ValueError) as error:
        raise Unclear(f"does not parse: {error}")
    editor = Editor(text)
    lines = [editor.content(row) for row in range(1, len(editor.lines) + 1)]
    scopes, targets = notes.python_symbols(tree)
    items = []
    keep_all = guard.get("all")
    keep_docs = guard.get("docstrings")
    comments = []
    for token in tokens:
        if token.type == tokenize.COMMENT:
            row, col = token.start
            comments.append({"id": len(comments), "row": row, "col": col, "end_row": row,
                             "end_col": col + len(token.string), "text": token.string})
    licensed = mark_license_blocks(editor, comments)
    comment_rows = {}
    for comment in comments:
        row = comment["row"]
        if row == 1 and comment["col"] == 0 and comment["text"].startswith("#!"):
            keep = "shebang"
        elif row <= 2 and CODING.match(editor.content(row)):
            keep = "encoding declaration"
        elif keep_all:
            keep = keep_all
        else:
            keep = license_or_directive(comment, licensed)
            if not keep and notes.is_constraint(comment_body(comment["text"])):
                keep = "warning constraint"
        comment["keep"], comment["resolved"] = resolve(keep, row, resolved, sink)
        sink["suppressions"].extend(dict(entry, line=row) for entry in notes.find_suppressions(comment["text"], "python"))
        comment_rows.setdefault(row, []).append(comment)
    removed_positions = set()
    covered_rows = set()
    for node, name, body in body_lists(tree):
        removable = []
        for index, stmt in enumerate(body):
            if not is_string_statement(stmt):
                continue
            is_doc = (index == 0 and name == "body"
                      and isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)))
            kind = "docstring" if is_doc else "string statement"
            first, last = stmt.lineno, stmt.end_lineno
            start_col = char_col(editor.content(first), stmt.col_offset)
            end_col = char_col(editor.content(last), stmt.end_col_offset)
            rows = range(first, last + 1)
            value = stmt.value.value
            reason = ""
            if keep_all or keep_docs:
                reason = keep_all or keep_docs
            elif is_doc and ">>>" in value:
                reason = "doctest example (>>>)"
            elif notes.is_constraint(value):
                reason = "warning constraint"
            reason, handled = resolve(reason, first, resolved, sink)
            if not reason:
                if not owns_statement(editor, first, start_col, last, end_col):
                    reason = "shares a line with code"
                elif any(c["keep"] for row in rows for c in comment_rows.get(row, [])):
                    reason = "shares a line with a kept comment"
            owner = node.lineno if is_doc and not isinstance(node, ast.Module) else first
            symbol = "module" if isinstance(node, ast.Module) and is_doc else notes.python_symbol(scopes, targets, owner)
            if reason == "warning constraint" or handled == "warning constraint":
                note_flags(sink, value, first, symbol, "", "resolved" if handled else "kept")
            elif not reason and is_doc and not isinstance(node, ast.Module):
                note_flags(sink, value, first, symbol, lines[node.lineno - 1], "")
            items.append(Item(first, kind, "keep" if reason else "remove", reason, preview(value)))
            if not reason:
                removable.append(stmt)
        if not removable:
            continue
        remaining = [stmt for stmt in body if stmt not in removable]
        for position, stmt in enumerate(removable):
            removed_positions.add((stmt.lineno, stmt.col_offset))
            rows = range(stmt.lineno, stmt.end_lineno + 1)
            covered_rows.update(rows)
            if position == 0 and not remaining and not isinstance(node, ast.Module):
                indent = editor.content(stmt.lineno)[: char_col(editor.content(stmt.lineno), stmt.col_offset)]
                editor.replace[stmt.lineno] = indent + "pass"
                editor.drop.update(range(stmt.lineno + 1, stmt.end_lineno + 1))
            else:
                editor.drop.update(rows)
    for comment in comments:
        row = comment["row"]
        kind = "shebang" if comment["keep"] == "shebang" else "comment"
        owned = editor.owns(row, comment["col"], row, comment["end_col"])
        attached = notes.next_code_row(lines, row, ("#",)) if owned else row
        symbol = notes.python_symbol(scopes, targets, attached)
        code = lines[attached - 1] if owned else lines[row - 1][: comment["col"]]
        if comment["keep"] == "warning constraint" or comment["resolved"] == "warning constraint":
            note_flags(sink, comment["text"], row, symbol, code, "resolved" if comment["resolved"] else "kept")
        if comment["keep"]:
            items.append(Item(row, kind, "keep", comment["keep"], preview(comment["text"])))
            continue
        if not comment["resolved"]:
            note_flags(sink, comment_body(comment["text"]), row, symbol, code, "")
        items.append(Item(row, kind, "remove", "", preview(comment["text"])))
        if row in covered_rows:
            continue
        if owned:
            editor.drop.add(row)
        else:
            editor.cut(row, comment["col"], comment["end_col"])
    return items, editor, removed_positions


def verify_python(original: str, result: str, removed: set) -> tuple:
    try:
        after = ast.dump(parse_quietly(result))
    except (SyntaxError, ValueError) as error:
        return False, f"result does not parse: {error}"
    if after != expected_python_dump(original, removed):
        return False, "Python AST changed beyond the removed docstrings"
    return True, "Python AST unchanged apart from removed docstrings"


def shell_comments(text: str) -> list:
    comments = []
    frames = [["top", 0]]
    pending = []
    word_start = True
    i, n = 0, len(text)

    def scan_single(j):
        end = text.find("'", j)
        if end < 0:
            raise Unclear("unterminated single quote")
        return end + 1

    def scan_ansi(j):
        while j < n:
            if text[j] == "\\":
                j += 2
                continue
            if text[j] == "'":
                return j + 1
            j += 1
        raise Unclear("unterminated $'...' string")

    def dollar(j):
        if text.startswith("$((", j):
            frames.append(["arith", 0])
            return j + 3
        if text.startswith("$(", j):
            frames.append(["cmd", 0])
            return j + 2
        if text.startswith("${", j):
            frames.append(["param", 0])
            return j + 2
        if text.startswith("$'", j):
            return scan_ansi(j + 2)
        return j + 1

    def heredoc_bodies(j):
        for delimiter, strip_tabs in pending:
            while True:
                if j >= n:
                    raise Unclear(f"unterminated heredoc {delimiter!r}")
                end = text.find("\n", j)
                end = n if end < 0 else end
                line = text[j:end].rstrip("\r")
                j = end + 1
                if (line.lstrip("\t") if strip_tabs else line) == delimiter:
                    break
        pending.clear()
        return j

    while i < n:
        kind = frames[-1][0]
        c = text[i]
        if kind in ("top", "cmd"):
            if c == "\n":
                i += 1
                word_start = True
                if pending:
                    i = heredoc_bodies(i)
                continue
            if c == "#" and word_start:
                end = text.find("\n", i)
                end = n if end < 0 else end
                if end > i and text[end - 1] == "\r":
                    end -= 1
                comments.append((i, end))
                i = end
                continue
            if c == "\\":
                if text.startswith("\\\n", i):
                    i += 2
                    continue
                i += 2
                word_start = False
                continue
            if c in " \t\r":
                i += 1
                word_start = True
                continue
            if c == "'":
                i = scan_single(i + 1)
                word_start = False
                continue
            if c == '"':
                frames.append(["dq", 0])
                i += 1
                word_start = False
                continue
            if c == "`":
                frames.append(["tick", 0])
                i += 1
                word_start = False
                continue
            if c == "$":
                i = dollar(i)
                word_start = text[i - 1] == "(" if frames[-1][0] == "cmd" else False
                continue
            if c == "(":
                if word_start and text.startswith("((", i):
                    frames.append(["arith", 0])
                    i += 2
                    continue
                if kind == "cmd":
                    frames[-1][1] += 1
                i += 1
                word_start = True
                continue
            if c == ")":
                if kind == "cmd":
                    if frames[-1][1] == 0:
                        frames.pop()
                        i += 1
                        word_start = False
                        continue
                    frames[-1][1] -= 1
                i += 1
                word_start = True
                continue
            if text.startswith("<<<", i):
                i += 3
                word_start = True
                continue
            if text.startswith("<<", i):
                j = i + 2
                strip_tabs = text.startswith("-", j)
                if strip_tabs:
                    j += 1
                while j < n and text[j] in " \t":
                    j += 1
                start = j
                while j < n and text[j] not in " \t\n;&|<>()":
                    if text[j] in "'\"":
                        close = text.find(text[j], j + 1)
                        if close < 0:
                            raise Unclear("unterminated heredoc delimiter quote")
                        j = close + 1
                        continue
                    j += 1
                word = re.sub(r"[\"'\\]", "", text[start:j])
                if not word:
                    raise Unclear("heredoc without a delimiter")
                pending.append((word, strip_tabs))
                i = j
                word_start = False
                continue
            i += 1
            word_start = c in ";&|<>"
            continue
        if kind == "dq":
            if c == "\\":
                i += 2
            elif c == '"':
                frames.pop()
                i += 1
            elif c == "`":
                frames.append(["tick", 0])
                i += 1
            elif c == "$":
                i = dollar(i)
                if frames[-1][0] == "cmd":
                    word_start = True
            else:
                i += 1
            continue
        if kind == "param":
            if c == "\\":
                i += 2
            elif c == "'":
                i = scan_single(i + 1)
            elif c == '"':
                frames.append(["dq", 0])
                i += 1
            elif c == "`":
                frames.append(["tick", 0])
                i += 1
            elif c == "$":
                i = dollar(i)
                if frames[-1][0] == "cmd":
                    word_start = True
            elif c == "{":
                frames[-1][1] += 1
                i += 1
            elif c == "}":
                if frames[-1][1] == 0:
                    frames.pop()
                else:
                    frames[-1][1] -= 1
                i += 1
            else:
                i += 1
            continue
        if kind == "arith":
            if c == "(":
                frames[-1][1] += 1
                i += 1
            elif c == ")":
                if frames[-1][1] == 0 and text.startswith("))", i):
                    frames.pop()
                    i += 2
                else:
                    frames[-1][1] = max(0, frames[-1][1] - 1)
                    i += 1
            elif c == "$":
                i = dollar(i)
                if frames[-1][0] == "cmd":
                    word_start = True
            elif c == '"':
                frames.append(["dq", 0])
                i += 1
            elif c == "'":
                i = scan_single(i + 1)
            else:
                i += 1
            continue
        if kind == "tick":
            if c == "\\":
                i += 2
            elif c == "`":
                frames.pop()
                i += 1
            else:
                i += 1
            continue
    if len(frames) != 1 or pending:
        raise Unclear("unbalanced quotes, substitutions, or heredocs")
    return comments


def plan_shell(text: str, resolved: set, sink: dict) -> tuple:
    editor = Editor(text)
    lines = [editor.content(row) for row in range(1, len(editor.lines) + 1)]
    spans = shell_comments(text)
    self_read = bool(SHELL_SELF_READ.search(text))
    comments = []
    for start, end in spans:
        row, col = editor.locate(start)
        comments.append({"id": len(comments), "row": row, "col": col, "end_row": row,
                         "end_col": col + (end - start), "text": text[start:end]})
    licensed = mark_license_blocks(editor, comments)
    items = []
    for comment in comments:
        row, col = comment["row"], comment["col"]
        previous = editor.content(row - 1) if row > 1 else ""
        continued = len(previous) - len(previous.rstrip("\\")) if previous.endswith("\\") else 0
        sink["suppressions"].extend(dict(entry, line=row) for entry in notes.find_suppressions(comment["text"], "shell"))
        owned = editor.owns(row, col, row, comment["end_col"])
        attached = notes.next_code_row(lines, row, ("#",)) if owned else row
        symbol = notes.text_symbol(lines, attached, "shell")
        code = lines[attached - 1] if owned else lines[row - 1][:col]
        if row == 1 and col == 0 and comment["text"].startswith("#!"):
            reason = "shebang"
        elif self_read:
            reason = "script reads its own source ($0 or BASH_SOURCE)"
        elif license_or_directive(comment, licensed):
            reason = license_or_directive(comment, licensed)
        elif notes.is_constraint(comment_body(comment["text"])):
            reason = "warning constraint"
        elif continued % 2 == 1:
            reason = "follows a line continuation"
        else:
            reason = ""
        reason, handled = resolve(reason, row, resolved, sink)
        if reason == "warning constraint" or handled:
            note_flags(sink, comment["text"], row, symbol, code, "resolved" if handled else "kept")
        elif not reason:
            note_flags(sink, comment_body(comment["text"]), row, symbol, code, "")
        kind = "shebang" if reason == "shebang" else "comment"
        items.append(Item(row, kind, "keep" if reason else "remove", reason, preview(comment["text"])))
        if reason:
            continue
        if owned:
            editor.drop.add(row)
        else:
            editor.cut(row, col, comment["end_col"])
    return items, editor


def bash_function_dump(bash: str, text: str) -> Optional[str]:
    with tempfile.TemporaryDirectory(prefix="remove-comments-") as scratch:
        env = {"PATH": os.defpath, "HOME": scratch, "LANG": os.environ.get("LANG", "C")}
        options = [bash, "--norc", "--noprofile", "-O", "extglob"]
        parsed = subprocess.run(options + ["-n"], input=text, capture_output=True, text=True,
                                timeout=60, cwd=scratch, env=env)
        if parsed.returncode != 0:
            return None
        script = 'src=$(cat); eval "__remove_comments_check() {\n$src\n}" && declare -f __remove_comments_check'
        done = subprocess.run(options + ["-c", script], input=text, capture_output=True, text=True,
                              timeout=60, cwd=scratch, env=env)
    return done.stdout if done.returncode == 0 else None


def verify_shell(original: str, result: str) -> tuple:
    bash = shutil.which("bash")
    if not bash:
        return None, "bash not found; shell files need bash to verify"
    before = bash_function_dump(bash, original)
    if before is None:
        return None, "bash cannot parse the original"
    after = bash_function_dump(bash, result)
    if after is None:
        return False, "bash cannot parse the result"
    if after != before:
        return False, "bash parse differs after removal"
    return True, "bash parse unchanged (declare -f)"


@dataclass
class Token:
    kind: str
    text: str
    start: int
    end: int
    newline_before: bool
    paren_keyword: bool = False


def js_tokens(text: str, typescript: bool) -> list:
    tokens = []
    braces = []
    parens = []
    state = {"newline": False}
    i, n = 0, len(text)

    def line_of(offset):
        return text.count("\n", 0, offset) + 1

    def emit(kind, start, end, paren_keyword=False):
        tokens.append(Token(kind, text[start:end], start, end, state["newline"], paren_keyword))
        if kind != "comment":
            state["newline"] = False

    def significant(back=1):
        seen = 0
        for token in reversed(tokens):
            if token.kind == "comment":
                continue
            seen += 1
            if seen == back:
                return token
        return None

    def template_chunk(j, kind_done, kind_open, start):
        while j < n:
            ch = text[j]
            if ch == "\\":
                j += 2
                continue
            if ch == "`":
                emit(kind_done, start, j + 1)
                return j + 1
            if text.startswith("${", j):
                emit(kind_open, start, j + 2)
                braces.append("${")
                return j + 2
            j += 1
        raise Unclear(f"unterminated template literal at line {line_of(start)}")

    def operand_expected():
        prev = significant()
        if prev is None:
            return True
        if prev.kind in ("number", "string", "template", "regex"):
            return False
        if prev.kind == "template-open":
            return True
        if prev.kind == "name":
            before = significant(2)
            if before is not None and before.kind == "punct" and before.text in (".", "?."):
                return False
            return prev.text in REGEX_AFTER_WORDS
        if prev.text == ")":
            return prev.paren_keyword
        if prev.text == "]" or prev.text in ("++", "--"):
            return False
        if prev.text == "}":
            return None
        if typescript and prev.text == "!":
            before = significant(2)
            if before is not None and (before.kind in ("name", "number", "string", "template", "regex")
                                       or before.text in (")", "]")):
                return None
        return True

    if text.startswith("#!"):
        end = len(text.split("\n", 1)[0])
        emit("comment", 0, end)
        i = end
    while i < n:
        c = text[i]
        if c in JS_NEWLINES:
            state["newline"] = True
            i += 1
            continue
        if c in " \t\f\v\ufeff\xa0":
            i += 1
            continue
        if text.startswith("//", i):
            j = i
            while j < n and text[j] not in JS_NEWLINES:
                j += 1
            emit("comment", i, j)
            i = j
            continue
        if text.startswith("/*", i):
            end = text.find("*/", i + 2)
            if end < 0:
                raise Unclear(f"unterminated block comment at line {line_of(i)}")
            emit("comment", i, end + 2)
            if any(ch in JS_NEWLINES for ch in text[i:end]):
                state["newline"] = True
            i = end + 2
            continue
        if c in "'\"":
            j = i + 1
            while j < n and text[j] != c:
                if text[j] == "\\":
                    j += 1
                elif text[j] in "\n\r":
                    raise Unclear(f"unterminated string at line {line_of(i)}")
                j += 1
            if j >= n:
                raise Unclear(f"unterminated string at line {line_of(i)}")
            emit("string", i, j + 1)
            i = j + 1
            continue
        if c == "`":
            i = template_chunk(i + 1, "template", "template-open", i)
            continue
        if c == "}" and braces and braces[-1] == "${":
            braces.pop()
            i = template_chunk(i + 1, "template", "template-open", i)
            continue
        if c == "<" and not typescript and operand_expected():
            raise Unclear(f"JSX syntax at line {line_of(i)}; JSX text can contain comment-like text")
        if c == "/":
            allowed = operand_expected()
            if allowed is None:
                raise Unclear(f"'/' at line {line_of(i)} could be division or a regular expression")
            if allowed:
                j, in_class = i + 1, False
                while True:
                    if j >= n or text[j] in "\n\r":
                        raise Unclear(f"unterminated regular expression at line {line_of(i)}")
                    ch = text[j]
                    if ch == "\\":
                        j += 2
                        continue
                    if in_class:
                        in_class = ch != "]"
                    elif ch == "[":
                        in_class = True
                    elif ch == "/":
                        break
                    j += 1
                j += 1
                while j < n and (text[j].isalnum() or text[j] in "_$"):
                    j += 1
                emit("regex", i, j)
                i = j
                continue
        if c.isdigit() or (c == "." and i + 1 < n and text[i + 1].isdigit()):
            match = JS_NUMBER.match(text, i)
            emit("number", i, match.end())
            i = match.end()
            continue
        if c.isalpha() or c in "_$" or ord(c) > 127 or (c == "#" and i + 1 < n and (text[i + 1].isalpha() or text[i + 1] in "_$")):
            match = JS_IDENT.match(text, i + 1 if c == "#" else i)
            end = match.end() if match else i + 1
            emit("name", i, end)
            i = end
            continue
        if c == "(":
            prev = significant()
            before = significant(2)
            keyword = (prev is not None and prev.kind == "name" and prev.text in PAREN_KEYWORDS
                       and not (before is not None and before.text in (".", "?.")))
            parens.append(keyword)
            emit("punct", i, i + 1)
            i += 1
            continue
        if c == ")":
            emit("punct", i, i + 1, parens.pop() if parens else False)
            i += 1
            continue
        if c == "{":
            braces.append("{")
        elif c == "}" and braces:
            braces.pop()
        width = next((len(p) for p in JS_PUNCTUATORS if text.startswith(p, i)), 1)
        emit("punct", i, i + width)
        i += width
    if braces and "${" in braces:
        raise Unclear("unterminated template expression")
    return tokens


def plan_js(text: str, typescript: bool, type_checked: bool, resolved: set, sink: dict) -> tuple:
    tokens = js_tokens(text, typescript)
    type_checked = type_checked or "@ts-check" in text
    editor = Editor(text)
    lines = [editor.content(row) for row in range(1, len(editor.lines) + 1)]
    language = "typescript" if typescript else "javascript"
    comments = []
    for token in tokens:
        if token.kind != "comment":
            continue
        row, col = editor.locate(token.start)
        end_row, end_col = editor.locate(token.end - 1)
        comments.append({"id": len(comments), "row": row, "col": col, "end_row": end_row,
                         "end_col": end_col + 1, "text": token.text})
    licensed = mark_license_blocks(editor, comments)
    items = []
    kept_texts = []
    for comment in comments:
        text_value = comment["text"]
        row = comment["row"]
        sink["suppressions"].extend(dict(entry, line=row) for entry in notes.find_suppressions(text_value, language))
        owned = editor.owns(row, comment["col"], comment["end_row"], comment["end_col"])
        attached = notes.next_code_row(lines, comment["end_row"], ("//", "/*", "*")) if owned else row
        symbol = notes.text_symbol(lines, attached, language)
        code = lines[attached - 1] if owned else lines[row - 1][: comment["col"]]
        if row == 1 and comment["col"] == 0 and text_value.startswith("#!"):
            reason = "shebang"
        elif text_value.startswith("/*!"):
            reason = "license or copyright notice"
        elif license_or_directive(comment, licensed):
            reason = license_or_directive(comment, licensed)
        elif not typescript and type_checked and text_value.startswith("/**") and JSDOC_TYPES.search(text_value):
            reason = "JSDoc type that TypeScript checks"
        elif typescript and TS_INTERNAL.search(text_value):
            reason = "@internal tag that TypeScript stripInternal reads"
        elif notes.is_constraint(comment_body(text_value).strip(" *\n")):
            reason = "warning constraint"
        else:
            reason = ""
        reason, handled = resolve(reason, row, resolved, sink)
        if not reason and comment["end_row"] != row and not owned:
            reason = "multi-line comment shares a line with code"
        if reason == "warning constraint" or handled:
            note_flags(sink, text_value, row, symbol, code, "resolved" if handled else "kept")
        elif not reason:
            note_flags(sink, comment_body(text_value), row, symbol, code, "")
        kind = "shebang" if reason == "shebang" else "comment"
        items.append(Item(row, kind, "keep" if reason else "remove", reason, preview(text_value)))
        if reason:
            kept_texts.append(text_value)
            continue
        if owned:
            editor.drop.update(range(row, comment["end_row"] + 1))
        else:
            editor.cut(row, comment["col"], comment["end_col"])
    return items, editor, kept_texts


def js_signature(text: str, typescript: bool) -> tuple:
    tokens = js_tokens(text, typescript)
    code = [(t.kind, t.text, t.newline_before) for t in tokens if t.kind != "comment"]
    if code:
        code[0] = code[0][:2] + (False,)
    return code, [t.text for t in tokens if t.kind == "comment"]


def node_syntax_ok(text: str, suffix: str) -> Optional[bool]:
    node = shutil.which("node")
    if not node:
        return None
    source = text
    target_suffix = {".ts": ".js", ".mts": ".mjs", ".cts": ".cjs"}.get(suffix, suffix)
    if suffix in TS_SUFFIXES:
        strip = ("let s='';process.stdin.on('data',d=>s+=d).on('end',()=>{try{process.stdout.write("
                 "require('node:module').stripTypeScriptTypes(s))}catch(e){process.exit(3)}})")
        done = subprocess.run([node, "--no-warnings", "-e", strip], input=text, capture_output=True,
                              text=True, timeout=60)
        if done.returncode != 0:
            return None
        source = done.stdout
    with tempfile.TemporaryDirectory(prefix="remove-comments-") as scratch:
        path = Path(scratch) / ("check" + target_suffix)
        path.write_text(source, encoding="utf-8")
        done = subprocess.run([node, "--check", str(path)], capture_output=True, text=True, timeout=60)
    return done.returncode == 0


def verify_js(original: str, result: str, typescript: bool, kept_texts: list, suffix: str) -> tuple:
    try:
        before_code, _ = js_signature(original, typescript)
        after_code, after_comments = js_signature(result, typescript)
    except Unclear as error:
        return False, f"result does not lex: {error}"
    if before_code != after_code:
        return False, "token stream or line breaks changed"
    if after_comments != kept_texts:
        return False, "kept comments changed"
    before_ok = node_syntax_ok(original, suffix)
    if before_ok:
        if not node_syntax_ok(result, suffix):
            return False, "node syntax check fails after removal"
        return True, "tokens and line breaks unchanged; node syntax check passes"
    return True, "tokens and line breaks unchanged (node syntax check unavailable)"


def language_of(path: Path) -> tuple:
    suffix = path.suffix.lower()
    if path.name in OTHER_CODE_NAMES:
        return "other", "no safe parser in this script"
    if suffix in PYTHON_SUFFIXES:
        return "python", ""
    if suffix in SHELL_SUFFIXES:
        return "shell", ""
    if suffix in JS_SUFFIXES:
        return ("other", "minified file") if path.name.endswith(".min" + suffix) else ("javascript", "")
    if suffix in TS_SUFFIXES:
        return "typescript", ""
    if suffix in HAND_ONLY:
        return "other", HAND_ONLY[suffix]
    if suffix in OTHER_CODE_SUFFIXES:
        return "other", "no safe parser in this script"
    if suffix in PROSE_SUFFIXES:
        return "prose", ""
    try:
        with path.open("rb") as handle:
            first = handle.readline(200).decode("utf-8", errors="replace")
    except OSError:
        return "ignored", ""
    if first.startswith("#!"):
        if "python" in first:
            return "python", ""
        if re.search(r"\b(bash|sh|dash|ksh)\b", first):
            return "shell", ""
        if "node" in first:
            return "javascript", ""
        if "zsh" in first:
            return "other", "zsh glob flags use #"
        return "other", "no safe parser in this script"
    return "ignored", ""


def git_root(path: Path) -> Optional[Path]:
    where = path if path.is_dir() else path.parent
    done = subprocess.run(["git", "-C", str(where), "rev-parse", "--show-toplevel"],
                          capture_output=True, text=True)
    return Path(done.stdout.strip()) if done.returncode == 0 else None


def expand(path: Path) -> list:
    if path.is_file():
        return [(path, "")]
    found = []
    if git_root(path):
        done = subprocess.run(["git", "-C", str(path), "ls-files", "-z", "--cached", "--others",
                               "--exclude-standard"], capture_output=True, text=True)
        candidates = [path / name for name in done.stdout.split("\0") if name]
    else:
        candidates = []
        for directory, names, files in os.walk(path):
            names[:] = sorted(name for name in names if name not in HEAVY_DIRS)
            candidates.extend(Path(directory) / name for name in sorted(files))
    for candidate in candidates:
        if not candidate.is_file():
            continue
        parts = set(candidate.relative_to(path).parts[:-1])
        found.append((candidate, "vendored, dependency, or build folder" if parts & SKIP_DIRS else ""))
    return found


def module_names(relative: Path) -> list:
    parts = list(relative.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return [".".join(parts[index:]) for index in range(len(parts))]


def python_guards(root: Path, files: list) -> dict:
    index = {}
    trees = {}
    for path in files:
        relative = path.relative_to(root)
        for name in module_names(relative):
            index.setdefault(name, set()).add(path)
        try:
            trees[path] = parse_quietly(read_source(path, "python")[0])
        except (Unclear, SyntaxError, ValueError, OSError):
            continue
    guards = {}

    def protect(target, scope, reason):
        current = guards.setdefault(target, {})
        if scope == "all" or "all" not in current:
            current.setdefault(scope, reason)

    for path, tree in trees.items():
        relative = path.relative_to(root)
        readers = []
        source_readers = []
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == "__doc__":
                readers.append((node.lineno, "reads __doc__"))
            elif isinstance(node, ast.Attribute) and node.attr == "__doc__":
                readers.append((node.lineno, "reads __doc__"))
            elif isinstance(node, ast.Constant) and node.value == "__doc__":
                readers.append((node.lineno, "names __doc__"))
            elif isinstance(node, ast.Call):
                func = node.func
                name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""
                if name in DOC_READER_CALLS:
                    readers.append((node.lineno, f"calls {name}()"))
                if name in SOURCE_READER_CALLS:
                    source_readers.append((node.lineno, f"calls {name}()"))
                if name == "import_module" and node.args and isinstance(node.args[0], ast.Constant) \
                        and isinstance(node.args[0].value, str):
                    imported.append((node.lineno, node.args[0].value, True))
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported.append((node.lineno, alias.name, True))
                    if alias.name.split(".")[0] in DOC_READER_MODULES:
                        readers.append((node.lineno, f"imports {alias.name}, which reads docstrings"))
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    base = list(relative.parent.parts)
                    base = base[: len(base) - (node.level - 1)] if node.level > 1 else base
                    module = ".".join(base + (node.module.split(".") if node.module else []))
                else:
                    module = node.module or ""
                for alias in node.names:
                    submodule = f"{module}.{alias.name}" if module else alias.name
                    if alias.name != "*" and submodule in index:
                        imported.append((node.lineno, submodule, True))
                    elif module:
                        imported.append((node.lineno, module, False))
                if not node.level and module.split(".")[0] in DOC_READER_MODULES:
                    readers.append((node.lineno, f"imports from {module}, which reads docstrings"))
        if "use_attribute_docstrings" in ast.dump(tree):
            readers.append((1, "pydantic use_attribute_docstrings"))
        if not readers and not source_readers:
            continue
        line, why = (source_readers or readers)[0]
        scope = "all" if source_readers else "docstrings"
        protect(path, scope, f"this file reads {'source text' if source_readers else 'docstrings'} (line {line}: {why})")
        for line_number, name, children in imported:
            for module, targets in index.items():
                if module == name or (children and module.startswith(name + ".")):
                    for target in targets:
                        if target != path:
                            protect(target, scope, f"imported by {relative}:{line_number}, which reads "
                                                   f"{'source text' if source_readers else 'docstrings'}")
    return guards


def analyze(path: Path, display: str, language: str, context: dict) -> FileResult:
    result = FileResult(display, language)
    resolved = context["resolved"].get(path.resolve(), set())
    sink = new_sink()
    try:
        text, result.encoding = read_source(path, language)
        head = "\n".join(text.split("\n", 5)[:5])
        if GENERATED.search(head):
            raise Unclear("generated file")
        if language == "python":
            items, editor, removed = plan_python(text, context["guards"].get(path.resolve(), {}), resolved, sink)
        elif language == "shell":
            items, editor = plan_shell(text, resolved, sink)
        else:
            items, editor, kept_texts = plan_js(text, language == "typescript", context["type_checked"],
                                                resolved, sink)
    except Unclear as error:
        result.status, result.reason = "skipped", str(error)
        return result
    except OSError as error:
        result.status, result.reason = "skipped", f"cannot read: {error}"
        return result
    context["used"].update((path.resolve(), row) for row in sink["used"])
    root = context["root_of"](path)
    configs = notes.nearest_configs(path.resolve(), root, context["configs"])
    for entry in sink["suppressions"]:
        for finding in notes.classify(entry, path, root, context["lookups"]):
            finding["line"] = entry["line"]
            finding["config"] = notes.configured(entry["tool"], finding["rule"], configs)
            result.suppressions.append(finding)
    result.constraints = sorted(sink["constraints"], key=lambda entry: entry["line"])
    result.clarity = sorted(sink["clarity"], key=lambda entry: entry["line"])
    result.suppressions.sort(key=lambda entry: entry["line"])
    result.items = sorted(items, key=lambda item: item.line)
    if not result.count("remove"):
        result.clarity = []
        return result
    new_text = editor.render()
    if language == "python":
        ok, check = verify_python(text, new_text, removed)
    elif language == "shell":
        ok, check = verify_shell(text, new_text)
    else:
        ok, check = verify_js(text, new_text, language == "typescript", kept_texts, path.suffix.lower())
    result.check = check
    if ok:
        result.status, result.new_text = "change", new_text
    elif ok is None:
        result.status, result.reason = "skipped", check
        result.clarity = []
    else:
        result.status, result.reason = "failed", check
        result.clarity = []
    return result


def run(paths: list, write: bool, resolved: Optional[dict] = None) -> dict:
    scopes = {}
    for path in paths:
        repo = git_root(path)
        if repo:
            scopes.setdefault(repo.resolve(), None)
        elif path.is_dir():
            scopes.setdefault(path.resolve(), None)
        else:
            scopes.setdefault(path.parent.resolve(), set())
            if scopes[path.parent.resolve()] is not None:
                scopes[path.parent.resolve()].add(path.resolve())
    roots = list(scopes)
    base = Path.cwd()
    targets = []
    seen = set()
    for path in paths:
        for candidate, vendored in expand(path):
            key = candidate.resolve()
            if key not in seen:
                seen.add(key)
                targets.append((candidate, vendored))
    repo_files = []
    guards = {}
    for root in roots:
        files = sorted(scopes[root]) if scopes[root] is not None else [c.resolve() for c, v in expand(root) if not v]
        repo_files.extend(files)
        python_files = [p for p in files if language_of(p)[0] == "python"]
        for key, value in python_guards(root, python_files).items():
            guards.setdefault(key.resolve(), {}).update(value)
    type_checked = any(CHECKJS.search(p.read_text(errors="replace")) for p in repo_files
                       if p.name.startswith(("tsconfig", "jsconfig")) and p.suffix == ".json")
    doc_notes = []
    for path in repo_files:
        for name, pattern in DOC_GENERATORS:
            if path.name == name and pattern.search(path.read_text(errors="replace")):
                doc_notes.append(f"{display_path(path, base)} builds documentation from docstrings")

    def root_of(path):
        resolved_path = path.resolve()
        return max((r for r in roots if resolved_path == r or r in resolved_path.parents),
                   key=lambda r: len(r.parts), default=roots[0])

    context = {"guards": guards, "type_checked": type_checked, "resolved": resolved or {}, "used": set(),
               "lookups": {}, "configs": {}, "root_of": root_of}
    results = []
    prose = ignored = 0
    for candidate, vendored in targets:
        display = display_path(candidate, base)
        if candidate.is_symlink():
            results.append(FileResult(display, "?", "skipped", "symlink"))
            continue
        language, why = language_of(candidate)
        if language == "prose":
            prose += 1
            continue
        if language == "ignored":
            ignored += 1
            continue
        if vendored:
            results.append(FileResult(display, language, "skipped", vendored))
            continue
        if language == "other":
            results.append(FileResult(display, language, "skipped", why + "; edit by hand or leave"))
            continue
        result = analyze(candidate, display, language, context)
        if write and result.status == "change":
            candidate.write_bytes(result.new_text.encode(result.encoding))
        results.append(result)
    unmatched = sorted(f"{display_path(path, base)}:{row}" for path, rows in (resolved or {}).items()
                       for row in rows if (path, row) not in context["used"])
    return {"results": results, "prose": prose, "ignored": ignored, "notes": doc_notes, "unmatched": unmatched}


def display_path(path: Path, base: Path) -> str:
    try:
        return str(path.resolve().relative_to(base.resolve()))
    except ValueError:
        return str(path)


ROUTINE_KEEPS = {"shebang", "encoding declaration"}
ACTIONABLE = {"correctness", "safety", "unscoped"}


def category(reason: str) -> str:
    if reason.startswith("imported by"):
        return "imported by a file that reads " + ("source text" if reason.endswith("source text") else "docstrings")
    return reason.split(" (line")[0]


def summary(report: dict, write: bool) -> dict:
    results = report["results"]
    removed = {"comment": 0, "docstring": 0, "string statement": 0}
    kept_by_reason = {}
    suppressions = {}
    for result in results:
        for item in result.items:
            if item.action == "keep":
                key = category(item.reason)
                kept_by_reason[key] = kept_by_reason.get(key, 0) + 1
            elif result.status == "change":
                removed[item.kind] = removed.get(item.kind, 0) + 1
        for finding in result.suppressions:
            suppressions[finding["category"]] = suppressions.get(finding["category"], 0) + 1
    constraints = [c for r in results for c in r.constraints]
    return {
        "mode": "apply" if write else "scan",
        "files_checked": len(results),
        "files_changed" if write else "files_to_change": sum(r.status == "change" for r in results),
        "removed" if write else "to_remove": removed,
        "kept": sum(result.count("keep") for result in results),
        "kept_by_reason": dict(sorted(kept_by_reason.items(), key=lambda pair: -pair[1])),
        "runtime_docstrings_kept": sum(1 for r in results for item in r.items
                                       if item.action == "keep" and item.reason.startswith(RUNTIME_REASONS)),
        "clarity_flags": sum(len(r.clarity) for r in results),
        "constraints_kept": sum(c["status"] == "kept until encoded" for c in constraints),
        "constraints_resolved": sum(c["status"] == "resolved and removed" for c in constraints),
        "suppressions": dict(sorted(suppressions.items(), key=lambda pair: -pair[1])),
        "suppressions_actionable": sum(count for name, count in suppressions.items() if name in ACTIONABLE),
        "skipped": sum(r.status == "skipped" for r in results),
        "failed_verification": sum(r.status == "failed" for r in results),
        "prose_files_left_alone": report["prose"],
        "other_files_ignored": report["ignored"],
    }


def capped(lines: list) -> None:
    for line in lines[:OUTPUT_CAP]:
        print(line)
    if len(lines) > OUTPUT_CAP:
        print(f"... {len(lines) - OUTPUT_CAP} more lines; rerun with --json for the full list")


def suppression_line(path: str, finding: dict) -> str:
    detail = f"  [{finding['description']}]" if finding["description"] else ""
    config = f"; {finding['config']}" if finding.get("config") else ""
    return (f"SUPPRESS    {path}:{finding['line']}  {finding['tool']} {finding['rule']}: {finding['category']} "
            f"({finding['source']}); {finding['action']}{config}{detail}")


def print_text(report: dict, write: bool, details: bool) -> None:
    info = summary(report, write)
    verb = "removed" if write else "to remove"
    counts = info["removed" if write else "to_remove"]
    changed = info["files_changed" if write else "files_to_change"]
    print(f"remove-comments {info['mode']}{'' if write else ' (dry run, nothing written)'}: "
          f"{info['files_checked']} code files checked")
    print(f"  {verb}: {counts['comment']} comments, {counts['docstring']} docstrings, "
          f"{counts['string statement']} string statements in {changed} files")
    reasons = ", ".join(f"{name} {count}" for name, count in info["kept_by_reason"].items())
    print(f"  kept: {info['kept']} items{' (' + reasons + ')' if reasons else ''}")
    print(f"  flags: {info['clarity_flags']} clarity, {info['constraints_kept']} constraints kept until encoded, "
          f"{info['constraints_resolved']} constraints resolved, {info['runtime_docstrings_kept']} runtime "
          f"docstrings kept")
    kinds = ", ".join(f"{name} {count}" for name, count in info["suppressions"].items())
    print(f"  suppressions: {sum(info['suppressions'].values())} ({kinds or 'none'}); "
          f"{info['suppressions_actionable']} actionable")
    print(f"  skipped: {info['skipped']} files; failed verification: {info['failed_verification']} files")
    print(f"  not code: {info['prose_files_left_alone']} prose files left alone, "
          f"{info['other_files_ignored']} other files ignored")
    results = report["results"]
    for result in results:
        if result.status == "failed":
            print(f"FAIL        {result.path}  {result.reason}; left untouched")
    for result in results:
        if result.status == "skipped":
            print(f"SKIP        {result.path}  {result.reason}")
    for result in results:
        for constraint in result.constraints:
            print(f"CONSTRAINT  {result.path}:{constraint['line']}  {constraint['symbol']}: {constraint['status']}"
                  f"  [{constraint['note']}]")
    for result in results:
        for item in result.items:
            if item.action == "keep" and item.reason.startswith(RUNTIME_REASONS):
                print(f"RUNTIME     {result.path}:{item.line}  {item.kind}: {item.reason}  [{item.preview}]")
    for result in results:
        for finding in result.suppressions:
            if finding["category"] in ACTIONABLE:
                print(suppression_line(result.path, finding))
    capped([f"CLARIFY     {r.path}:{flag['line']}  {flag['symbol']}: {flag['suggestion']}  [{flag['note']}]"
            for r in results for flag in r.clarity])
    lines = []
    for result in results:
        if result.status == "change":
            parts = [f"{result.count('remove', k)} {k}s" for k in ("comment", "docstring", "string statement")
                     if result.count("remove", k)]
            label = "CHANGED" if write else "CHANGE"
            lines.append(f"{label:<12}{result.path}  ({', '.join(parts)}; {result.check})")
        for finding in result.suppressions:
            if finding["category"] not in ACTIONABLE:
                lines.append(suppression_line(result.path, finding))
        for item in result.items:
            routine = item.reason in ROUTINE_KEEPS
            shown = item.reason == "warning constraint" or item.reason.startswith(RUNTIME_REASONS)
            if item.action == "keep" and not shown and (details or not routine):
                lines.append(f"KEEP        {result.path}:{item.line}  {item.kind}: {item.reason}  [{item.preview}]")
            elif item.action == "remove" and details and result.status == "change":
                lines.append(f"REMOVE      {result.path}:{item.line}  {item.kind}  [{item.preview}]")
    capped(lines)
    for note in report["notes"]:
        print(f"NOTE        {note}")


def print_json(report: dict, write: bool) -> None:
    payload = {
        "summary": summary(report, write),
        "notes": report["notes"],
        "files": [
            {"path": r.path, "language": r.language, "status": r.status, "reason": r.reason,
             "check": r.check, "items": [item.__dict__ for item in r.items], "clarity": r.clarity,
             "constraints": r.constraints, "suppressions": r.suppressions}
            for r in report["results"]
        ],
    }
    print(json.dumps(payload, indent=2))


def parse_resolved(values: list, parser: argparse.ArgumentParser) -> dict:
    resolved = {}
    for value in values or []:
        path, _, line = value.rpartition(":")
        if not path or not line.isdigit():
            parser.error(f"--resolved takes PATH:LINE, got {value!r}")
        resolved.setdefault(Path(path).resolve(), set()).add(int(line))
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inventory or remove code comments and docstrings without changing behavior. "
                    "Python, sh/bash/dash/ksh, JavaScript and TypeScript are supported; other code "
                    "files are reported as skipped. The report also flags code that may need a clearer "
                    "name, warning notes to encode as checks, and lint or type suppressions to audit.")
    sub = parser.add_subparsers(dest="mode", required=True)
    for mode, text in (("scan", "dry run: report what would be removed, kept, skipped, and flagged"),
                       ("apply", "remove comments and docstrings, verifying each file first")):
        command = sub.add_parser(mode, help=text)
        command.add_argument("paths", nargs="+", type=Path, help="files or folders in scope")
        command.add_argument("--json", action="store_true", help="print the full report as JSON")
        command.add_argument("--details", action="store_true", help="also list every removed item")
        command.add_argument("--resolved", action="append", metavar="PATH:LINE",
                             help="a warning constraint now encoded as a check, or a runtime docstring whose "
                                  "behavior now lives elsewhere; remove it (repeatable)")
    args = parser.parse_args()
    missing = [str(p) for p in args.paths if not p.exists()]
    if missing:
        parser.error(f"no such path: {', '.join(missing)}")
    resolved = parse_resolved(args.resolved, parser)
    write = args.mode == "apply"
    if resolved:
        unmatched = run(args.paths, False, resolved)["unmatched"]
        if unmatched:
            print("remove-comments: --resolved matched no warning constraint or runtime docstring at: "
                  + ", ".join(unmatched), file=sys.stderr)
            return 2
    report = run(args.paths, write, resolved)
    if args.json:
        print_json(report, write)
    else:
        print_text(report, write, args.details)
    return 1 if any(r.status == "failed" for r in report["results"]) else 0


if __name__ == "__main__":
    sys.exit(main())
