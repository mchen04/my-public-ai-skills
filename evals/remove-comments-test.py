#!/usr/bin/env python3
from __future__ import annotations

import importlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1] / "skills/remove-comments/scripts"
SCRIPT = HERE / "comments.py"
sys.path.insert(0, str(HERE))
comments = importlib.import_module("comments")

PYTHON_BEFORE = '''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright 2026 Example Corp.
# SPDX-License-Identifier: MIT

"""Module docstring."""
import os  # noqa: F401

MARKER = "# not a comment"  # trailing note
PATH = 'http://example.com/#top'


def empty():
    """Only a docstring."""


class Thing:
    """Thing doc."""

    size = 1
    """Attribute docstring."""

    # explain the method
    def method(self):  # trailing
        return MARKER + PATH  # type: ignore[operator]


def doctested():
    """
    >>> doctested()
    3
    """
    return 3
'''

PYTHON_AFTER = '''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright 2026 Example Corp.
# SPDX-License-Identifier: MIT

import os  # noqa: F401

MARKER = "# not a comment"
PATH = 'http://example.com/#top'


def empty():
    pass


class Thing:
    size = 1

    def method(self):
        return MARKER + PATH  # type: ignore[operator]


def doctested():
    """
    >>> doctested()
    3
    """
    return 3
'''

SHELL_BEFORE = """#!/bin/sh
# shellcheck disable=SC2086
# plain comment
count=${#HOME}  # length
echo "a # b" '# c' $# a#b # real
cat <<'END'
# heredoc text stays
END
printf '%s\\n' \\
  # after continuation
echo done
"""

SHELL_AFTER = """#!/bin/sh
# shellcheck disable=SC2086
count=${#HOME}
echo "a # b" '# c' $# a#b
cat <<'END'
# heredoc text stays
END
printf '%s\\n' \\
  # after continuation
echo done
"""

JS_BEFORE = """// eslint-disable-next-line no-unused-vars
/*! Example v1 | MIT */
/** Adds two numbers. */
export function add(a, b) {
  const url = "http://example.com//path"; // trailing
  const re = /\\/\\/not-a-comment/g;
  const t = `text // ${a /* inline */ + b} /* kept text */`;
  return a/**/+b; /* end */
}
"""

JS_AFTER = """// eslint-disable-next-line no-unused-vars
/*! Example v1 | MIT */
export function add(a, b) {
  const url = "http://example.com//path";
  const re = /\\/\\/not-a-comment/g;
  const t = `text // ${a + b} /* kept text */`;
  return a+b;
}
"""


def run(mode: str, *paths, extra: tuple = ()) -> tuple:
    done = subprocess.run([sys.executable, str(SCRIPT), mode, "--json", *map(str, paths), *extra],
                          capture_output=True, text=True)
    return done.returncode, json.loads(done.stdout) if done.stdout.strip() else done.stderr


def by_path(report: dict) -> dict:
    return {Path(entry["path"]).name: entry for entry in report["files"]}


class RemoveCommentsTest(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory(prefix="remove-comments-test-")
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)

    def write(self, name: str, text: str) -> Path:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def test_python_shell_and_js_removal_keeps_literals_and_required_comments(self):
        files = {"sample.py": (PYTHON_BEFORE, PYTHON_AFTER), "sample.sh": (SHELL_BEFORE, SHELL_AFTER),
                 "sample.js": (JS_BEFORE, JS_AFTER)}
        for name, (before, _) in files.items():
            self.write(name, before)
        code, scan = run("scan", self.root)
        self.assertEqual(code, 0, scan)
        for name, (before, _) in files.items():
            self.assertEqual((self.root / name).read_text(), before, f"scan wrote {name}")
        expected_status = "change" if shutil.which("bash") else "skipped"
        self.assertEqual(by_path(scan)["sample.sh"]["status"], expected_status)
        code, applied = run("apply", self.root)
        self.assertEqual(code, 0, applied)
        self.assertEqual((self.root / "sample.py").read_text(), PYTHON_AFTER)
        self.assertEqual((self.root / "sample.js").read_text(), JS_AFTER)
        if shutil.which("bash"):
            self.assertEqual((self.root / "sample.sh").read_text(), SHELL_AFTER)
        kept = {(item["line"], item["reason"]) for item in by_path(applied)["sample.py"]["items"]
                if item["action"] == "keep"}
        self.assertIn((29, "doctest example (>>>)"), kept)
        self.assertIn((7, "tool directive"), kept)
        code, again = run("scan", self.root)
        self.assertEqual(again["summary"]["files_to_change"], 0, again)

    def test_runtime_read_docstrings_are_kept(self):
        self.write("pkg/__init__.py", '"""Package doc that nothing reads."""\n')
        self.write("pkg/util.py", 'def helper():\n    """Helper doc."""\n    return 1\n')
        self.write("cli.py", '"""Usage: cli [--help]"""\nimport argparse\n\nfrom pkg import util\n\n\n'
                             'def main():\n    parser = argparse.ArgumentParser(description=__doc__)\n'
                             '    return parser, util.helper.__doc__\n')
        self.write("tool.py", 'import click\n\n\n@click.command()\ndef hello():\n    """Say hello."""\n')
        self.write("plain.py", 'def f():\n    """Plain doc."""\n    return 2\n')
        code, applied = run("apply", self.root)
        self.assertEqual(code, 0, applied)
        files = by_path(applied)
        reasons = {name: [i["reason"] for i in files[name]["items"] if i["kind"] == "docstring"]
                   for name in ("cli.py", "util.py", "tool.py")}
        self.assertTrue(reasons["cli.py"][0].startswith("this file reads docstrings"), reasons)
        self.assertTrue(reasons["util.py"][0].startswith("imported by cli.py"), reasons)
        self.assertIn("click", reasons["tool.py"][0])
        self.assertIn('"""Helper doc."""', (self.root / "pkg/util.py").read_text())
        self.assertEqual((self.root / "plain.py").read_text(), "def f():\n    return 2\n")
        self.assertEqual((self.root / "pkg/__init__.py").read_text(), "")

    def test_unclear_and_unsupported_files_are_skipped_untouched(self):
        sources = {
            "slash.js": "if (a) {}\n/foo/.test(s); // note\n",
            "view.js": "const v = <div>// text</div>;\n",
            "app.tsx": "export const A = () => <p>// text</p>; // note\n",
            "main.go": "package main // note\n",
            "run.zsh": "print ok # note\n",
            "gen.py": "# @generated by a tool\nx = 1  # note\n",
            "vendor/lib.py": "x = 1  # note\n",
        }
        for name, text in sources.items():
            self.write(name, text)
        self.write("README.md", "# Title\n")
        code, applied = run("apply", self.root)
        self.assertEqual(code, 0, applied)
        statuses = {name: entry["status"] for name, entry in by_path(applied).items()}
        self.assertEqual(set(statuses.values()), {"skipped"}, statuses)
        self.assertEqual(applied["summary"]["prose_files_left_alone"], 1)
        for name, text in sources.items():
            self.assertEqual((self.root / name).read_text(), text, name)

    def test_shell_check_never_runs_code_from_a_file_that_does_not_parse(self):
        marker = self.root / "ran"
        self.write("trap.sh", f"# note\n:\n}}\ntouch {marker}\nf() {{\n:\n")
        code, applied = run("apply", self.root)
        self.assertEqual(by_path(applied)["trap.sh"]["status"], "skipped", applied)
        self.assertFalse(marker.exists())

    def test_each_check_fails_on_a_changed_program(self):
        ok, _ = comments.verify_python("x = 1\n", "x = 2\n", set())
        self.assertFalse(ok)
        ok, _ = comments.verify_js("a/**/b\n", "ab\n", False, [], ".js")
        self.assertFalse(ok)
        ok, _ = comments.verify_js("x = a\n/* c */\n(b)\n", "x = a (b)\n", False, [], ".js")
        self.assertFalse(ok)
        ok, _ = comments.verify_js("a/**/b\n", "a b\n", False, [], ".js")
        self.assertTrue(ok)
        if shutil.which("bash"):
            ok, _ = comments.verify_shell("a \\\n# c\nb\n", "a \\\nb\n")
            self.assertFalse(ok)
            ok, _ = comments.verify_shell("a # c\nb\n", "a\nb\n")
            self.assertTrue(ok)

    def test_warning_constraints_stay_until_resolved(self):
        python = self.write("fields.py", 'FIELDS = ["id", "email"]  # do not reorder: the importer reads by position\n'
                                         'RATE = 0.08  # Talk to billing before changing this rate\n')
        script = self.write("deploy.sh", "#!/bin/sh\n# keep this name in sync with the deploy job\nAPP=web\n")
        typed = self.write("kinds.ts", "// IMPORTANT: order matters for the wire format\nexport const KINDS = ['a', 'b'];\n")
        before = {path: path.read_text() for path in (python, script, typed)}
        code, scan = run("scan", self.root)
        found = {(Path(f["path"]).name, c["line"], c["symbol"], c["status"]) for f in scan["files"]
                 for c in f["constraints"]}
        self.assertEqual(found, {("fields.py", 1, "FIELDS", "kept until encoded"),
                                 ("fields.py", 2, "RATE", "kept until encoded"),
                                 ("deploy.sh", 2, "APP", "kept until encoded"),
                                 ("kinds.ts", 1, "KINDS", "kept until encoded")})
        code, applied = run("apply", self.root)
        self.assertEqual({path: path.read_text() for path in before}, before)
        code, message = run("apply", self.root, extra=("--resolved", f"{python}:9"))
        self.assertEqual(code, 2)
        self.assertIn("matched no warning constraint", message)
        self.assertEqual({path: path.read_text() for path in before}, before)
        code, applied = run("apply", self.root, extra=("--resolved", f"{python}:1", "--resolved", f"{typed}:1"))
        self.assertEqual(code, 0, applied)
        self.assertEqual(python.read_text(), 'FIELDS = ["id", "email"]\n'
                                             'RATE = 0.08  # Talk to billing before changing this rate\n')
        self.assertEqual(typed.read_text(), "export const KINDS = ['a', 'b'];\n")
        self.assertEqual(applied["summary"]["constraints_resolved"], 2)
        self.assertEqual(applied["summary"]["constraints_kept"], 2)

    def test_runtime_docstring_leaves_only_when_its_behavior_moves(self):
        cli = self.write("cli.py", '"""Greet people."""\nimport argparse\n\n\n'
                                   'def parser():\n    return argparse.ArgumentParser(description=__doc__)\n')
        maths = self.write("maths.py", 'def mean(values):\n    """Average.\n\n    >>> mean([2, 4])\n    3.0\n    """\n'
                                       '    return sum(values) / len(values)\n')
        code, scan = run("scan", self.root)
        self.assertEqual(scan["summary"]["runtime_docstrings_kept"], 2)
        cli.write_text('import argparse\n\nDESCRIPTION = "Greet people."\n\n\n'
                       'def parser():\n    return argparse.ArgumentParser(description=DESCRIPTION)\n')
        code, applied = run("apply", self.root, extra=("--resolved", f"{maths}:2"))
        self.assertEqual(code, 0, applied)
        self.assertEqual(applied["summary"]["runtime_docstrings_kept"], 0)
        self.assertEqual(maths.read_text(), "def mean(values):\n    return sum(values) / len(values)\n")

    def test_clarity_flags_name_the_symbol_and_skip_plain_narration(self):
        self.write("timing.py", "d = 86400  # seconds per day\n\n\ndef ok(a, b, c):\n"
                                "    # retry when either side is stale\n    if a and b or c:\n        return 1\n"
                                "    # load users\n    users = list(a)\n    return users\n\n\n"
                                "def fetch(url):\n    # workaround: the vendor drops the first call after idle\n"
                                "    return url\n")
        code, scan = run("scan", self.root)
        flags = {(c["line"], c["symbol"], c["suggestion"]) for c in by_path(scan)["timing.py"]["clarity"]}
        self.assertEqual(flags, {
            (1, "d", "name the number 86400; rename `d`"),
            (5, "ok", "extract the condition into a named predicate"),
            (14, "fetch", "the note explained intent; make `fetch` say it (rename or extract)"),
        })

    def test_suppressions_are_classified_from_rule_sources_and_never_removed(self):
        rules = self.root / "node_modules/eslint/lib/rules"
        rules.mkdir(parents=True)
        (rules / "no-unsafe-finally.js").write_text(
            'module.exports = { meta: { type: "problem", docs: { description: "Disallow control flow in `finally`" } } };\n')
        self.write(".eslintrc.json", '{"rules": {"no-unsafe-finally": "error"}}\n')
        source = self.write("app.js", "function f() {\n  try { return 1; } finally {\n"
                                      "    // eslint-disable-next-line no-unsafe-finally\n    return 2;\n  }\n}\n"
                                      "// eslint-disable-next-line no-console, made-up/rule -- noisy\nconsole.log(f());\n"
                                      "/* eslint-disable */\nexport { f };\n")
        typed = self.write("lib.ts", "// @ts-expect-error legacy\nconst n: number = '1';\nexport { n };\n")
        python = self.write("mod.py", "import os  # noqa: F401\nx: int = 'a'  # type: ignore[assignment]\n"
                                      "import yaml  # type: ignore[import-untyped]\ny = 1  # noqa\n")
        script = self.write("run.sh", "#!/bin/sh\n# shellcheck disable=SC2086\necho $1\n")
        before = {path: path.read_text() for path in (source, typed, python, script)}
        code, applied = run("apply", source, typed, python, script)
        self.assertEqual({path: path.read_text() for path in before}, before)
        found = {(Path(f["path"]).name, s["rule"], s["category"]) for f in applied["files"] for s in f["suppressions"]}
        self.assertEqual(found, {
            ("app.js", "no-unsafe-finally", "correctness"), ("app.js", "no-console", "hygiene"),
            ("app.js", "made-up/rule", "unknown"), ("app.js", "(all rules)", "unscoped"),
            ("lib.ts", "@ts-expect-error", "correctness"), ("mod.py", "F401", "hygiene"),
            ("mod.py", "assignment", "correctness"), ("mod.py", "import-untyped", "environment"),
            ("mod.py", "(all rules)", "unscoped"), ("run.sh", "SC2086", "correctness"),
        })
        finally_rule = next(s for f in applied["files"] for s in f["suppressions"] if s["rule"] == "no-unsafe-finally")
        self.assertIn("node_modules/eslint/lib/rules/no-unsafe-finally.js", finally_rule["source"])
        self.assertEqual(finally_rule["config"], "configured: error")
        self.assertEqual(applied["summary"]["suppressions_actionable"], 6)


if __name__ == "__main__":
    unittest.main()
