#!/usr/bin/env python3

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "skills" / "project-verification" / "scripts" / "testselect.py"

PYTHON_REPO = {
    "calc/__init__.py": "",
    "calc/ops.py": "def add(a, b):\n    return a + b\n",
    "calc/fmt.py": "def show(x):\n    return str(x)\n",
    "textutil/__init__.py": "",
    "textutil/words.py": "def count(s):\n    return len(s.split())\n",
    "tests/__init__.py": "",
    "tests/test_ops.py": "import unittest\nfrom calc.ops import add\n\n\nclass T(unittest.TestCase):\n"
                         "    def test_add(self):\n        self.assertEqual(add(1, 2), 3)\n",
    "tests/test_format.py": "import unittest\nfrom calc import fmt\n\n\nclass T(unittest.TestCase):\n"
                            "    def test_show(self):\n        self.assertEqual(fmt.show(1), '1')\n",
    "tests/test_words.py": "import unittest\nimport textutil.words as w\n\n\nclass T(unittest.TestCase):\n"
                           "    def test_count(self):\n        self.assertEqual(w.count('a b'), 2)\n",
    "README.md": "demo\n",
}


class TestSelectTest(unittest.TestCase):
    def make(self, files: dict[str, str]) -> Path:
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        repo = Path(holder.name).resolve()
        for path, text in files.items():
            (repo / path).parent.mkdir(parents=True, exist_ok=True)
            (repo / path).write_text(text)
        subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m",
                        "base"], check=True)
        return repo

    def select(self, repo: Path, *args: str) -> tuple[int, dict, str]:
        done = subprocess.run([sys.executable, str(SCRIPT), "--repo", str(repo), "--base", "main", "--json",
                               "--log", "-", *args], capture_output=True, text=True, timeout=120)
        data = json.loads(done.stdout) if done.stdout.startswith("{") else {}
        return done.returncode, data, done.stdout + done.stderr

    def test_actual_remote_default_is_used_without_a_base_option(self):
        repo = self.make(PYTHON_REPO)
        subprocess.run(["git", "-C", str(repo), "update-ref", "refs/remotes/origin/integration/team", "HEAD"], check=True)
        subprocess.run(["git", "-C", str(repo), "symbolic-ref", "refs/remotes/origin/HEAD",
                        "refs/remotes/origin/integration/team"], check=True)
        (repo / "calc/ops.py").write_text("def add(a, b):\n    return b + a\n")
        result = subprocess.run([sys.executable, str(SCRIPT), "--repo", str(repo), "--json", "--log", "-"],
                                capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        self.assertEqual(data["base"], "origin/integration/team")
        self.assertEqual(data["tests"], ["tests/test_ops.py"])
        verifier = SCRIPT.with_name("verifyctl.py")
        subprocess.run([sys.executable, str(verifier), "init", "--project", str(repo), "--app", "demo"],
                       capture_output=True, text=True, check=True)
        generated = (repo / ".agents/skills/verify-project/SKILL.md").read_text()
        self.assertIn("--changed origin/integration/team", generated)

    def test_a_python_change_selects_only_its_tests(self):
        repo = self.make(PYTHON_REPO)
        (repo / "calc/ops.py").write_text("def add(a, b):\n    return b + a\n")
        code, result, out = self.select(repo)
        self.assertEqual((code, result["status"]), (0, "selected"), out)
        self.assertEqual(result["tests"], ["tests/test_ops.py"])
        self.assertEqual(result["files"][0]["rules"], ["name", "imports"])
        self.assertEqual(sorted(result["not_selected"]), ["tests/test_format.py", "tests/test_words.py"])
        self.assertEqual(result["commands"], [{"kind": "test", "package": ".", "cwd": ".",
                                               "argv": ["python3", "-m", "unittest", "tests/test_ops.py"]}])

    def test_from_imports_and_package_init_find_their_tests(self):
        repo = self.make(PYTHON_REPO)
        (repo / "calc/fmt.py").write_text("def show(x):\n    return f'{x}'\n")
        (repo / "textutil/__init__.py").write_text("VERSION = 1\n")
        code, result, out = self.select(repo)
        self.assertEqual(code, 0, out)
        self.assertEqual(result["tests"], ["tests/test_format.py", "tests/test_words.py"])

    def test_run_executes_the_selection_and_writes_an_audit_log(self):
        repo = self.make(PYTHON_REPO)
        (repo / "calc/ops.py").write_text("def add(a, b):\n    return a + b + 0\n")
        log = repo.parent / f"{repo.name}-audit.json"
        self.addCleanup(lambda: log.unlink(missing_ok=True))
        done = subprocess.run([sys.executable, str(SCRIPT), "--repo", str(repo), "--base", "main", "--run",
                               "--log", str(log)], capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("PASS: 1 of 1 selected command(s) passed", done.stdout)
        record = json.loads(log.read_text())
        self.assertEqual(record["runs"][0]["outcome"], "pass")
        self.assertEqual(record["tests"], ["tests/test_ops.py"])
        (repo / "calc/ops.py").write_text("def add(a, b):\n    return a - b\n")
        done = subprocess.run([sys.executable, str(SCRIPT), "--repo", str(repo), "--base", "main", "--run",
                               "--log", "-"], capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn("FAIL", done.stdout)

    def test_an_unmapped_file_is_unknown_never_an_empty_pass(self):
        repo = self.make(PYTHON_REPO)
        (repo / "calc/ops.py").write_text("def add(a, b):\n    return a + b + 0\n")
        (repo / "calc/newthing.py").write_text("X = 1\n")
        code, result, out = self.select(repo)
        self.assertEqual((code, result["status"], result["unmapped"]), (3, "unknown", ["calc/newthing.py"]), out)
        self.assertTrue(result["fallback"], "unknown must name the full-suite fallback")
        done = subprocess.run([sys.executable, str(SCRIPT), "--repo", str(repo), "--base", "main", "--run",
                               "--log", "-"], capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 3, done.stdout)
        self.assertIn("UNKNOWN (selected part passed)", done.stdout)
        done = subprocess.run([sys.executable, str(SCRIPT), "--repo", str(repo), "--base", "main", "--run",
                               "--fallback-full", "--log", "-"], capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("full command(s) passed", done.stdout)

    def test_docs_need_a_declaration_and_manifests_need_the_full_suite(self):
        repo = self.make(PYTHON_REPO)
        (repo / "README.md").write_text("changed\n")
        code, result, _ = self.select(repo)
        self.assertEqual((code, result["status"]), (3, "unknown"))
        config = repo / ".agents/skills/verify-project/tests.json"
        config.parent.mkdir(parents=True)
        config.write_text(json.dumps({"format": 1, "no_tests": ["*.md", ".agents/"],
                                      "full": ["python3", "-m", "unittest", "discover"]}))
        code, result, _ = self.select(repo)
        self.assertEqual((code, result["status"], result["tests"]), (0, "nothing", []))
        (repo / "pyproject.toml").write_text("[project]\nname = 'demo'\n")
        code, result, _ = self.select(repo)
        self.assertEqual((code, result["status"], result["full_reasons"]), (0, "full", ["pyproject.toml"]))
        self.assertEqual(result["fallback"][0]["argv"], ["python3", "-m", "unittest", "discover"])

    def test_a_config_map_and_changed_or_deleted_tests(self):
        files = dict(PYTHON_REPO, **{"data/words.csv": "a,b\n"})
        repo = self.make(files)
        config = repo / "selection.json"
        config.write_text(json.dumps({"format": 1, "map": [{"sources": ["data/*.csv"],
                                                            "tests": ["tests/test_words.py"]}]}))
        (repo / "data/words.csv").write_text("a,b,c\n")
        (repo / "tests/test_format.py").write_text(PYTHON_REPO["tests/test_format.py"] + "\n")
        subprocess.run(["git", "-C", str(repo), "rm", "-q", "tests/test_ops.py"], check=True)
        code, result, out = self.select(repo, "--config", str(config))
        by_path = {entry["path"]: entry for entry in result["files"]}
        self.assertEqual(by_path["data/words.csv"]["rules"], ["map"])
        self.assertEqual(by_path["tests/test_format.py"]["rules"], ["changed test"])
        self.assertEqual(by_path["tests/test_ops.py"]["rules"], ["deleted test"])
        self.assertEqual(result["tests"], ["tests/test_format.py", "tests/test_words.py"])

    def test_lint_and_typecheck_run_only_for_touched_packages(self):
        tool = "[tool.ruff]\nline-length = 100\n[tool.mypy]\nstrict = true\n[tool.pytest.ini_options]\n"
        repo = self.make({
            "pkg_a/pyproject.toml": tool, "pkg_a/a/core.py": "A = 1\n", "pkg_a/tests/test_core.py": "from a import core\n",
            "pkg_b/pyproject.toml": tool, "pkg_b/b/core.py": "B = 1\n", "pkg_b/tests/test_core.py": "from b import core\n",
        })
        (repo / "pkg_a/a/core.py").write_text("A = 2\n")
        code, result, out = self.select(repo)
        self.assertEqual(code, 0, out)
        self.assertEqual(result["tests"], ["pkg_a/tests/test_core.py"])
        self.assertEqual([(item["kind"], item["cwd"], item["argv"]) for item in result["commands"]], [
            ("lint", "pkg_a", ["ruff", "check", "a/core.py"]),
            ("typecheck", "pkg_a", ["mypy", "a/core.py"]),
            ("test", "pkg_a", ["python3", "-m", "pytest", "-q", "tests/test_core.py"]),
        ])
        self.assertEqual([(item["cwd"], item["argv"]) for item in result["fallback"]],
                         [("pkg_a", ["python3", "-m", "pytest", "-q"]), ("pkg_b", ["python3", "-m", "pytest", "-q"])])

    def test_typescript_and_go_conventions(self):
        manifest = json.dumps({"scripts": {"test": "vitest"}, "devDependencies": {"vitest": "1", "eslint": "9"}})
        repo = self.make({
            "web/package.json": manifest, "web/tsconfig.json": "{}",
            "web/src/button.ts": "export const b = 1\n", "web/src/button.test.ts": "import { b } from './button'\n",
            "web/src/util/format.ts": "export const f = 1\n",
            "web/test/format.spec.ts": "import { f } from '../src/util/format'\n",
            "web/src/other.test.ts": "import { o } from './other'\n", "web/src/other.ts": "export const o = 1\n",
            "go.mod": "module demo\n", "svc/handler.go": "package svc\n", "svc/handler_test.go": "package svc\n",
            "lib/x.go": "package lib\n", "lib/x_test.go": "package lib\n",
        })
        (repo / "web/src/button.ts").write_text("export const b = 2\n")
        (repo / "web/src/util/format.ts").write_text("export const f = 2\n")
        (repo / "svc/handler.go").write_text("package svc\n\nfunc H() {}\n")
        code, result, out = self.select(repo)
        self.assertEqual(code, 0, out)
        self.assertEqual(result["tests"], ["svc/handler_test.go", "web/src/button.test.ts", "web/test/format.spec.ts"])
        commands = {(item["kind"], item["cwd"]): item["argv"] for item in result["commands"]}
        self.assertEqual(commands[("test", "web")], ["npx", "vitest", "run", "src/button.test.ts", "test/format.spec.ts"])
        self.assertEqual(commands[("typecheck", "web")], ["npx", "tsc", "--noEmit", "-p", "."])
        self.assertEqual(commands[("lint", "web")], ["npx", "eslint", "src/button.ts", "src/util/format.ts"])
        self.assertEqual(commands[("test", ".")], ["go", "test", "./svc"])
        self.assertNotIn("lib/x_test.go", result["tests"])

    def test_explicit_files_and_no_changes(self):
        repo = self.make(PYTHON_REPO)
        code, result, _ = self.select(repo)
        self.assertEqual((code, result["status"]), (0, "no-changes"))
        code, result, _ = self.select(repo, "--files", "./textutil/words.py")
        self.assertEqual((code, result["tests"]), (0, ["tests/test_words.py"]))


if __name__ == "__main__":
    unittest.main()
