#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path, PurePosixPath

CONFIG = ".agents/skills/verify-project/tests.json"
JS_EXT = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts")
PY_TEST = re.compile(r"(^|/)(test_[^/]*|[^/]*_test)\.py$")
JS_TEST = re.compile(r"(^|/)(__tests__/[^/]+|[^/]+\.(test|spec)\.(js|jsx|ts|tsx|mjs|cjs|mts|cts))$")
GO_TEST = re.compile(r"_test\.go$")
RUST_TEST = re.compile(r"(^|/)tests/[^/]+\.rs$")
FULL_TRIGGERS = ("pyproject.toml", "setup.py", "setup.cfg", "requirements*.txt", "tox.ini", "pytest.ini", "noxfile.py",
                 "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "tsconfig*.json",
                 "jest.config.*", "vitest.config.*", "go.mod", "go.sum", "Cargo.toml", "Cargo.lock")
MANIFESTS = (("pyproject.toml", "python"), ("setup.py", "python"), ("setup.cfg", "python"),
             ("package.json", "node"), ("go.mod", "go"), ("Cargo.toml", "rust"))
PY_IMPORT = re.compile(r"^\s*(?:from\s+([\w.]+)\s+import\s+\(?([\w\s,*]+)|import\s+([\w.\s,]+?)(?:\s+as\s+\w+)?\s*$)", re.M)
JS_IMPORT = re.compile(r"""(?:from\s+|require\(\s*|import\(\s*|import\s+)['"](\.{1,2}/[^'"]+)['"]""")
LANGUAGE = {".py": "python", ".go": "go", ".rs": "rust", **{ext: "node" for ext in JS_EXT}}


class SelectError(Exception):
    pass


def git_lines(repo: Path, *args: str) -> list[str]:
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=60)
    if done.returncode != 0:
        raise SelectError(f"git {' '.join(args)} failed: {done.stderr.strip()}")
    return [line for line in done.stdout.splitlines() if line]


def default_base(repo: Path) -> str:
    result = subprocess.run(["git", "-C", str(repo), "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"],
                            capture_output=True, text=True, timeout=60)
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    for ref in ("origin/main", "origin/master"):
        result = subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify", ref + "^{commit}"],
                                capture_output=True, text=True, timeout=60)
        if result.returncode == 0:
            return ref
    return "HEAD"


def matches(path: str, pattern: str) -> bool:
    if pattern.endswith("/"):
        return path.startswith(pattern)
    if any(char in pattern for char in "*?["):
        return fnmatch.fnmatchcase(path, pattern) or fnmatch.fnmatchcase(PurePosixPath(path).name, pattern)
    return path == pattern or path.startswith(pattern + "/")


def load_config(repo: Path, path: str | None) -> tuple[dict, str | None]:
    location = Path(path).expanduser().resolve() if path else repo / CONFIG
    if not location.is_file():
        if path:
            raise SelectError(f"config not found: {location}")
        return {}, None
    try:
        config = json.loads(location.read_text(encoding="utf-8"))
    except ValueError as error:
        raise SelectError(f"config {location} is not JSON: {error}")
    if not isinstance(config, dict) or config.get("format") != 1:
        raise SelectError(f"config {location} needs \"format\": 1")
    for key in ("map", "packages", "no_tests", "test_patterns", "full_triggers"):
        if key in config and not isinstance(config[key], list):
            raise SelectError(f"config {key} must be a list")
    for entry in config.get("map", []):
        if not isinstance(entry, dict) or not isinstance(entry.get("sources"), list) or not isinstance(entry.get("tests"), list):
            raise SelectError("each map entry needs sources and tests lists")
    for package in config.get("packages", []):
        if not isinstance(package, dict) or not isinstance(package.get("root"), str):
            raise SelectError("each package needs a root")
    return config, str(location)


def is_test(path: str, config: dict) -> bool:
    patterns = config.get("test_patterns")
    if patterns:
        return any(matches(path, pattern) for pattern in patterns)
    return bool(PY_TEST.search(path) or JS_TEST.search(path) or GO_TEST.search(path) or RUST_TEST.search(path))


def py_names(path: str) -> list[str]:
    parts = list(PurePosixPath(path).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return [".".join(parts[index:]) for index in range(len(parts))]


def py_imports(text: str) -> set[str]:
    found: set[str] = set()
    for source, names, plain in PY_IMPORT.findall(text):
        if source:
            found.add(source)
            found |= {f"{source}.{name.split()[0]}" for name in names.replace("(", " ").split(",")
                      if name.strip() and name.split()[0] != "*"}
        for item in (plain or "").split(","):
            name = item.strip().split(" ")[0]
            if name:
                found.add(name)
    return found


def js_targets(test: str, text: str) -> set[str]:
    folder = PurePosixPath(test).parent
    found = set()
    for spec in JS_IMPORT.findall(text):
        base = os.path.normpath(str(folder / spec)).replace(os.sep, "/")
        found.add(base)
        found |= {base + ext for ext in JS_EXT} | {f"{base}/index{ext}" for ext in JS_EXT}
    return found


def shared_depth(one: str, two: str) -> int:
    depth = 0
    for left, right in zip(PurePosixPath(one).parent.parts, PurePosixPath(two).parent.parts):
        if left != right:
            break
        depth += 1
    return depth


def nearest(source: str, candidates: list[str]) -> list[str]:
    if not candidates:
        return []
    best = max(shared_depth(source, item) for item in candidates)
    return sorted(item for item in candidates if shared_depth(source, item) == best)


def test_stem(path: str) -> str:
    name = PurePosixPath(path).name
    for suffix in (".test", ".spec"):
        for ext in JS_EXT:
            if name.endswith(suffix + ext):
                return name[: -len(suffix + ext)]
    if name.endswith(".py"):
        stem = name[:-3]
        return stem[5:] if stem.startswith("test_") else stem[:-5] if stem.endswith("_test") else stem
    return PurePosixPath(name).stem


class Repo:
    def __init__(self, root: Path, config: dict):
        self.root = root
        self.config = config
        self.files = sorted(set(git_lines(root, "ls-files")) | set(git_lines(root, "ls-files", "--others",
                                                                              "--exclude-standard")))
        self.tests = [path for path in self.files if is_test(path, config) and (root / path).is_file()]
        self.texts: dict[str, str] = {}
        stems: dict[str, int] = {}
        for path in self.files:
            if path.endswith(".py"):
                stem = py_names(path)[-1] if py_names(path) else ""
                stems[stem] = stems.get(stem, 0) + 1
        self.py_stems = stems
        self.basenames: dict[str, int] = {}
        for path in self.files:
            name = PurePosixPath(path).name
            self.basenames[name] = self.basenames.get(name, 0) + 1

    def text(self, path: str) -> str:
        if path not in self.texts:
            try:
                self.texts[path] = (self.root / path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                self.texts[path] = ""
        return self.texts[path]

    def package_of(self, path: str) -> dict:
        configured = [package for package in self.config.get("packages", [])
                      if matches(path, package["root"].rstrip("/") + "/") or package["root"] in (".", "")]
        if configured:
            package = max(configured, key=lambda item: len(item["root"].strip("./")))
            return {"root": package["root"].strip("/") or ".", "kind": package.get("kind", "configured"),
                    "name": package.get("name") or package["root"], "config": package}
        folder = PurePosixPath(path).parent
        while True:
            for manifest, kind in MANIFESTS:
                if (self.root / folder / manifest).is_file():
                    root = str(folder) if str(folder) != "." else "."
                    return {"root": root, "kind": kind, "name": root, "manifest": str(folder / manifest)}
            if str(folder) in (".", ""):
                break
            folder = folder.parent
        kind = LANGUAGE.get(PurePosixPath(path).suffix, "unknown")
        return {"root": ".", "kind": kind, "name": ".", "manifest": None}


def related(repo: Repo, path: str) -> tuple[list[str], list[str]]:
    tests: set[str] = set()
    rules: list[str] = []
    suffix = PurePosixPath(path).suffix
    for entry in repo.config.get("map", []):
        if any(matches(path, pattern) for pattern in entry["sources"]):
            hits = [test for test in repo.tests if any(matches(test, pattern) for pattern in entry["tests"])]
            if hits:
                tests |= set(hits)
                rules.append("map")
    stem = PurePosixPath(path).stem if suffix != ".py" or PurePosixPath(path).name != "__init__.py" \
        else PurePosixPath(path).parent.name
    if suffix in (".py",) + JS_EXT:
        same = [test for test in repo.tests if test_stem(test) == stem
                and PurePosixPath(test).suffix in ((".py",) if suffix == ".py" else JS_EXT)]
        hits = nearest(path, same)
        if hits:
            tests |= set(hits)
            rules.append("name")
    if suffix == ".py":
        names = {name for name in py_names(path) if "." in name or repo.py_stems.get(name, 0) == 1}
        package = PurePosixPath(path).name == "__init__.py"
        hits = [test for test in repo.tests if test.endswith(".py") and any(
            imported in names or (package and any(imported.startswith(name + ".") for name in names))
            for imported in py_imports(repo.text(test)))]
        if hits:
            tests |= set(hits)
            rules.append("imports")
    if suffix in JS_EXT:
        hits = [test for test in repo.tests if PurePosixPath(test).suffix in JS_EXT and path in js_targets(test, repo.text(test))]
        if hits:
            tests |= set(hits)
            rules.append("imports")
    if suffix == ".go":
        folder = str(PurePosixPath(path).parent)
        hits = [test for test in repo.tests if test.endswith("_test.go") and str(PurePosixPath(test).parent) == folder]
        if hits:
            tests |= set(hits)
            rules.append("go-package")
    if suffix == ".rs":
        package = repo.package_of(path)
        if package["kind"] == "rust":
            tests.add(f"crate:{package['root']}")
            rules.append("rust-crate")
    name = PurePosixPath(path).name
    mention = path if repo.basenames.get(name, 0) > 1 else name
    hits = [test for test in repo.tests if test != path and mention in repo.text(test)]
    if hits:
        tests |= set(hits)
        rules.append("names-file")
    return sorted(tests), rules


def detect_python(repo: Path, root: str) -> dict:
    folder = repo / root
    pyproject = (folder / "pyproject.toml").read_text(errors="replace") if (folder / "pyproject.toml").is_file() else ""
    requirements = " ".join(path.read_text(errors="replace") for path in folder.glob("requirements*.txt"))
    pytest = ("[tool.pytest" in pyproject or (folder / "pytest.ini").is_file() or (folder / "conftest.py").is_file()
              or re.search(r"\bpytest\b", pyproject + requirements) is not None)
    found = {"test": ["python3", "-m", "pytest", "-q", "{tests}"] if pytest else ["python3", "-m", "unittest", "{tests}"],
             "full": ["python3", "-m", "pytest", "-q"] if pytest else ["python3", "-m", "unittest", "discover", "-p", "*test*.py"]}
    if "[tool.ruff" in pyproject or (folder / "ruff.toml").is_file() or (folder / ".ruff.toml").is_file():
        found["lint"] = ["ruff", "check", "{files}"]
    elif (folder / ".flake8").is_file():
        found["lint"] = ["flake8", "{files}"]
    if "[tool.mypy" in pyproject or (folder / "mypy.ini").is_file():
        found["typecheck"] = ["mypy", "{files}"]
    elif "[tool.pyright" in pyproject or (folder / "pyrightconfig.json").is_file():
        found["typecheck"] = ["pyright", "{files}"]
    return found


def detect_node(repo: Path, root: str) -> dict:
    folder = repo / root
    try:
        manifest = json.loads((folder / "package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        manifest = {}
    deps = {**manifest.get("dependencies", {}), **manifest.get("devDependencies", {})}
    script = (manifest.get("scripts") or {}).get("test", "")
    found: dict = {"full": ["npm", "test"]} if script else {}
    if "vitest" in deps or "vitest" in script:
        found["test"] = ["npx", "--no-install", "vitest", "run", "{tests}"]
    elif "jest" in deps or "jest" in script:
        found["test"] = ["npx", "--no-install", "jest", "{tests}"]
    elif script.startswith("node --test"):
        found["test"] = ["node", "--test", "{tests}"]
    if "eslint" in deps:
        found["lint"] = ["npx", "--no-install", "eslint", "{files}"]
    if (folder / "tsconfig.json").is_file():
        found["typecheck"] = ["npx", "--no-install", "tsc", "--noEmit", "-p", "."]
    return found


def detect_commands(repo: Path, package: dict, go_dirs: list[str]) -> dict:
    if "config" in package:
        return {key: package["config"][key] for key in ("test", "lint", "typecheck", "full") if key in package["config"]}
    kind = package["kind"]
    if kind == "python":
        return detect_python(repo, package["root"])
    if kind == "node":
        return detect_node(repo, package["root"])
    if kind == "go":
        targets = ["./" + folder if folder != "." else "." for folder in go_dirs] or ["./..."]
        return {"test": ["go", "test", *targets], "lint": ["go", "vet", *targets], "full": ["go", "test", "./..."]}
    if kind == "rust":
        name = package["root"]
        try:
            text = (repo / package["root"] / "Cargo.toml").read_text(errors="replace")
            name = re.search(r'^\s*name\s*=\s*"([^"]+)"', text, re.M).group(1)
        except (OSError, AttributeError):
            pass
        return {"test": ["cargo", "test", "-p", name], "lint": ["cargo", "clippy", "-p", name],
                "typecheck": ["cargo", "check", "-p", name], "full": ["cargo", "test"]}
    return {}


def relative(path: str, root: str) -> str:
    return path if root in (".", "") else str(PurePosixPath(path).relative_to(root))


def expand(argv: list[str], tests: list[str], files: list[str], root: str) -> list[str]:
    out: list[str] = []
    for item in argv:
        if item == "{tests}":
            out += tests
        elif item == "{files}":
            out += files
        else:
            out.append(item.replace("{root}", root))
    return out


def select(repo_path: Path, changed: list[str], config: dict) -> dict:
    repo = Repo(repo_path, config)
    triggers = config.get("full_triggers", list(FULL_TRIGGERS))
    files, unmapped, full_reasons = [], [], []
    packages: dict[str, dict] = {}
    for path in changed:
        exists = (repo_path / path).is_file()
        entry: dict = {"path": path, "tests": [], "rules": []}
        if any(matches(path, pattern) for pattern in config.get("no_tests", [])):
            entry["rules"] = ["declared no_tests"]
        elif any(fnmatch.fnmatchcase(PurePosixPath(path).name, pattern) for pattern in triggers) \
                or (PurePosixPath(path).name == "conftest.py" and PurePosixPath(path).parent == PurePosixPath(".")):
            entry["rules"] = ["full-suite trigger"]
            full_reasons.append(path)
        elif is_test(path, config):
            entry["rules"] = ["changed test" if exists else "deleted test"]
            entry["tests"] = [path] if exists else []
        elif PurePosixPath(path).name == "conftest.py":
            folder = str(PurePosixPath(path).parent) + "/"
            entry["tests"] = [test for test in repo.tests if test.startswith(folder)]
            entry["rules"] = ["conftest"] if entry["tests"] else ["unmapped"]
        else:
            entry["tests"], entry["rules"] = related(repo, path)
            if not entry["tests"]:
                entry["rules"] = ["unmapped"]
        if entry["rules"] == ["unmapped"]:
            unmapped.append(path)
        files.append(entry)
        if entry["rules"] in (["declared no_tests"], ["full-suite trigger"]):
            continue
        for item in entry["tests"] + ([path] if exists and LANGUAGE.get(PurePosixPath(path).suffix) else []):
            target = item[len("crate:"):] + "/Cargo.toml" if item.startswith("crate:") else item
            package = repo.package_of(target)
            slot = packages.setdefault(package["root"], {**package, "tests": set(), "files": set(), "crates": set()})
            if item.startswith("crate:"):
                slot["crates"].add(item)
            elif item in entry["tests"]:
                slot["tests"].add(item)
            if item == path:
                slot["files"].add(path)
    commands, missing, views = [], [], []
    for root, package in sorted(packages.items()):
        go_dirs = sorted({str(PurePosixPath(relative(test, root)).parent) for test in package["tests"]}) \
            if package["kind"] == "go" else []
        found = detect_commands(repo_path, package, go_dirs)
        tests = sorted(relative(test, root) for test in package["tests"])
        code = sorted(relative(path, root) for path in package["files"])
        view = {"root": root, "kind": package["kind"], "name": package["name"], "tests": tests, "files": code,
                "commands": {}, "not_configured": []}
        steps = (("lint", code), ("typecheck", code), ("test", tests or sorted(package["crates"])))
        for kind, needed in steps:
            if not needed:
                continue
            if kind not in found:
                view["not_configured"].append(kind)
                if kind == "test":
                    missing.append(f"no test command for package {root} ({package['kind']})")
                continue
            suffixes = (".py",) if package["kind"] == "python" else JS_EXT if package["kind"] == "node" else None
            code_for = [item for item in code if suffixes is None or item.endswith(suffixes)]
            if kind != "test" and not code_for and "{files}" in found[kind]:
                continue
            argv = expand(found[kind], tests, code_for, root)
            view["commands"][kind] = argv
            commands.append({"kind": kind, "package": root, "cwd": root, "argv": argv})
        views.append(view)
    selected = sorted({test for entry in files for test in entry["tests"]})
    full = full_suite(repo, config)
    if not changed:
        status = "no-changes"
    elif full_reasons:
        status = "full"
    elif unmapped or missing:
        status = "unknown"
    elif not commands:
        status = "nothing"
    else:
        status = "selected"
    result = {"status": status, "changed": changed, "files": files, "tests": selected,
              "not_selected": [test for test in repo.tests if test not in selected],
              "packages": views, "commands": commands, "unmapped": unmapped, "problems": missing,
              "full_reasons": full_reasons, "fallback": full}
    return result


def full_suite(repo: Repo, config: dict) -> list[dict]:
    if config.get("full"):
        return [{"package": ".", "cwd": ".", "argv": config["full"]}]
    configured = [package for package in config.get("packages", []) if package.get("full")]
    if configured:
        return [{"package": package["root"].strip("/") or ".", "cwd": package["root"].strip("/") or ".",
                 "argv": package["full"]} for package in configured]
    names = {manifest for manifest, _ in MANIFESTS}
    roots = sorted({str(PurePosixPath(path).parent) for path in repo.files if PurePosixPath(path).name in names})
    probes = ["_" if root == "." else f"{root}/_" for root in roots]
    kinds = [LANGUAGE[PurePosixPath(path).suffix] for path in repo.files if PurePosixPath(path).suffix in LANGUAGE]
    if not probes and kinds:
        common = max(sorted(set(kinds)), key=kinds.count)
        probes = [next(path for path in repo.files if LANGUAGE.get(PurePosixPath(path).suffix) == common)]
    steps, seen = [], set()
    for probe in probes:
        package = repo.package_of(probe)
        guess = detect_commands(repo.root, package, []).get("full")
        if guess and package["root"] not in seen:
            seen.add(package["root"])
            steps.append({"package": package["root"], "cwd": package["root"], "argv": guess})
    return steps


def changed_files(repo: Path, base: str) -> list[str]:
    paths: set[str] = set()
    paths.update(git_lines(repo, "diff", "--name-only", "--no-renames", f"{base}...HEAD"))
    paths.update(git_lines(repo, "diff", "--name-only", "--no-renames", "HEAD"))
    paths.update(git_lines(repo, "ls-files", "--others", "--exclude-standard"))
    return sorted(paths)


def execute(repo: Path, steps: list[dict], timeout: float) -> list[dict]:
    results = []
    for step in steps:
        started = time.time()
        try:
            done = subprocess.run(step["argv"], cwd=repo / step["cwd"], capture_output=True, text=True, timeout=timeout,
                                  env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"), stdin=subprocess.DEVNULL)
            outcome = "pass" if done.returncode == 0 else "fail"
            code, tail = done.returncode, (done.stdout + done.stderr).strip().splitlines()[-40:]
        except FileNotFoundError:
            outcome, code, tail = "missing-tool", None, [f"{step['argv'][0]} is not installed"]
        except subprocess.TimeoutExpired:
            outcome, code, tail = "timeout", None, [f"no result after {timeout}s"]
        seconds = round(time.time() - started, 2)
        results.append({**step, "outcome": outcome, "exit_code": code, "seconds": seconds, "output_tail": tail})
        print(f"{outcome.upper()} {step.get('kind', 'full')} ({seconds}s) [{step['cwd']}] {' '.join(step['argv'])}",
              file=sys.stderr)
        if outcome != "pass":
            print("\n".join("    " + line for line in tail[-15:]), file=sys.stderr)
    return results


def write_log(repo: Path, record: dict, target: str | None) -> str | None:
    if target == "-":
        return None
    path = Path(target).expanduser() if target else (
        Path.home() / ".cache" / "project-verification" / repo.name / "testselect"
        / f"{time.strftime('%Y%m%dT%H%M%S')}-{os.getpid()}.json")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8")
    except OSError as error:
        print(f"testselect: could not write the audit log {path}: {error}", file=sys.stderr)
        return None
    return str(path)


def print_text(result: dict) -> None:
    status = result["status"]
    print(f"testselect: {status}; {len(result['tests'])} test target(s) for {len(result['changed'])} changed file(s); "
          f"{len(result['not_selected'])} other test file(s) not selected")
    for entry in result["files"]:
        target = ", ".join(entry["tests"]) or "no tests"
        print(f"  {entry['path']} -> {target} ({', '.join(entry['rules'])})")
    for package in result["packages"]:
        for kind, argv in package["commands"].items():
            print(f"  {kind} [{package['root']}]: {' '.join(argv)}")
        if package["not_configured"]:
            print(f"  [{package['root']}] not configured: {', '.join(package['not_configured'])}")
    for problem in result["problems"]:
        print(f"  problem: {problem}")
    if status == "unknown":
        print("  UNKNOWN is not a pass: map the unmapped files in the config, or run the full suite (--full).")
    if status in ("unknown", "full"):
        for step in result["fallback"]:
            print(f"  full suite [{step['cwd']}]: {' '.join(step['argv'])}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Pick the tests, lint and type checks that cover a change, and say so when it cannot.",
        epilog=f"Rules, in order: declared no_tests, full-suite triggers (manifests, lockfiles, root conftest), "
               "changed tests, config map, name convention, imports, Go package, Rust crate, test files that "
               "name the file. A changed file no rule covers is unmapped: status unknown, exit 3, never a pass. "
               f"Config (optional): {CONFIG} with format 1, map, no_tests, packages (root, test, lint, typecheck, "
               "full argv lists using {tests}, {files}, {root}), full, test_patterns, full_triggers. "
               "Exit 0 = selected (or run passed); 1 = a run step failed; 2 = bad request; 3 = unknown mapping.")
    parser.add_argument("--repo", default=".", help="checkout to inspect (default: current folder)")
    parser.add_argument("--base", help="comparison ref; defaults to origin/HEAD, an existing primary remote branch, or HEAD")
    parser.add_argument("--files", nargs="+", help="use these changed paths instead of the Git diff")
    parser.add_argument("--config", help=f"selection config (default: <repo>/{CONFIG} when present)")
    parser.add_argument("--run", action="store_true", help="run the selected lint, type check and test commands")
    parser.add_argument("--full", action="store_true", help="run the full suite instead; use once before merge")
    parser.add_argument("--fallback-full", action="store_true",
                        help="with --run, run the full suite when the mapping is unknown")
    parser.add_argument("--timeout", type=float, default=1800, help="seconds per command (default 1800)")
    parser.add_argument("--log", help="audit log path; - writes none (default ~/.cache/project-verification/...)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        repo = Path(git_lines(Path(args.repo).expanduser(), "rev-parse", "--show-toplevel")[0]).resolve()
        args.base = args.base or default_base(repo)
        config, config_path = load_config(repo, args.config)
        changed = sorted({str(PurePosixPath(item)) for item in args.files}) if args.files \
            else changed_files(repo, args.base)
        result = select(repo, changed, config)
        head = git_lines(repo, "rev-parse", "HEAD")[0]
    except SelectError as error:
        print(f"testselect: {error}", file=sys.stderr)
        return 2
    result.update({"repo": str(repo), "head": head, "base": None if args.files else args.base, "config": config_path})
    code = 3 if result["status"] == "unknown" else 0
    if args.full:
        steps = [{**step, "kind": "full"} for step in result["fallback"]]
        if not steps:
            print("testselect: no full-suite command is known; set full in the config", file=sys.stderr)
            return 3
        result["runs"] = execute(repo, steps, args.timeout)
        result["ran"] = "full"
        code = 0 if all(item["outcome"] == "pass" for item in result["runs"]) else 1
    elif args.run:
        steps = list(result["commands"])
        fallback = result["status"] == "full" or (result["status"] == "unknown" and args.fallback_full)
        if fallback:
            steps = [{**step, "kind": "full"} for step in result["fallback"]]
        result["runs"] = execute(repo, steps, args.timeout)
        result["ran"] = "full" if fallback else "selected"
        passed = all(item["outcome"] == "pass" for item in result["runs"])
        if fallback and not steps:
            passed = False
            result["problems"].append("the full suite is needed but no command is known; set full in the config")
        code = 1 if not passed else 3 if result["status"] == "unknown" and not fallback else 0
    result["log"] = write_log(repo, result, args.log)
    if args.json:
        print(json.dumps(result, indent=1))
    else:
        print_text(result)
        if "runs" in result:
            failed = [item for item in result["runs"] if item["outcome"] != "pass"]
            verdict = ("FAIL" if failed else "UNKNOWN (selected part passed)" if code == 3
                       else f"NOTHING TO RUN ({result['status']})" if not result["runs"] else "PASS")
            print(f"testselect: {verdict}: {len(result['runs']) - len(failed)} of {len(result['runs'])} "
                  f"{result['ran']} command(s) passed")
        if result["log"]:
            print(f"testselect: audit log {result['log']}")
    return code


if __name__ == "__main__":
    sys.exit(main())
