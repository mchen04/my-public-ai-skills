from __future__ import annotations

import ast
import configparser
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

CONSTRAINT = re.compile(
    r"\b(do\s+not|don'?t|never)\s+(remove|delete|change|edit|modify|rename|reorder|move|touch|refactor|"
    r"inline|bump|upgrade|sort|reformat)\b"
    r"|\bmust\s+(stay|remain|match|not\s+change|be\s+kept)\b"
    r"|\bkeep\s+(?:\w+\s+){0,3}?(in\s+sync|in\s+order|sorted|stable|as\s+is|unchanged)\b"
    r"|\bin\s+sync\s+with\b"
    r"|\border\s+matters\b"
    r"|\b(talk|speak|check)\s+(to|with)\s+.{1,40}?\s+before\b"
    r"|\bask\s+.{1,40}?\s+before\b"
    r"|^\W*(important|warning|caution|danger)\b",
    re.IGNORECASE,
)
EXPLANATION = re.compile(
    r"\b(because|so\s+that|otherwise|workaround|hack|why|careful|tricky|gotcha|assum\w*|invariant|"
    r"in\s+order\s+to|to\s+avoid|to\s+prevent|needed\s+(for|by)|required\s+(for|by)|the\s+reason|magic|"
    r"off[-\s]by[-\s]one|intentional\w*|deliberate\w*|on\s+purpose|quirk|legacy|compat\w*)\b",
    re.IGNORECASE,
)
NUMBER = re.compile(r"(?<![\w.])(\d+\.\d+|\d+)(?![\w.])")
PLAIN_NUMBERS = {"0", "1", "2", "10", "100", "0.0", "0.5", "1.0"}
SHORT_NAME_OK = {"i", "j", "k", "n", "x", "y", "z", "_", "id", "ok", "db", "fs", "io", "os", "re"}
STRING = re.compile(r"(\"\"\"|'''|\"|'|`)(?:\\.|(?!\1).)*\1")
BOOLEAN_OPERATORS = re.compile(r"\band\b|\bor\b|&&|\|\|")
PY_TARGET = re.compile(r"^\s*(?:def|class)\s+([A-Za-z_]\w*)|^\s*([A-Za-z_][\w.]*)\s*(?::[^=]+)?=(?!=)")
JS_TARGET = re.compile(
    r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*([\w$]+)"
    r"|^\s*(?:export\s+)?(?:const|let|var)\s+([\w$]+)"
    r"|^\s*(?:export\s+)?(?:abstract\s+)?class\s+([\w$]+)"
    r"|^\s*(?:export\s+)?(?:type|interface|enum)\s+([\w$]+)"
    r"|^\s*(?:static\s+|async\s+|get\s+|set\s+|public\s+|private\s+|protected\s+|readonly\s+)*([\w$]+)\s*[(:=]"
)
JS_SCOPE = re.compile(
    r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*([\w$]+)"
    r"|^\s*(?:export\s+)?(?:abstract\s+)?class\s+([\w$]+)"
    r"|^\s*(?:export\s+)?(?:const|let|var)\s+([\w$]+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[\w$]+)\s*=>"
)
SH_TARGET = re.compile(
    r"^\s*(?:function\s+)?([A-Za-z_][\w-]*)\s*\(\)\s*\{?"
    r"|^\s*(?:export\s+|local\s+|readonly\s+|declare\s+(?:-\w+\s+)?)?([A-Za-z_]\w*)\+?="
)
JS_KEYWORDS = {"if", "for", "while", "switch", "catch", "return", "function", "else", "new", "typeof"}

SUPPRESSION_PATTERNS = [
    ("eslint", re.compile(r"eslint-disable(?P<scope>-next-line|-line)?(?![\w-])(?P<rules>[^\n*]*)")),
    ("typescript", re.compile(r"@ts-(?P<scope>ignore|expect-error|nocheck)\b")),
    ("ruff/flake8", re.compile(r"(?:(?P<scope>ruff|flake8):\s*)?\bnoqa\b(?::\s*(?P<rules>[A-Z]+[0-9]+(?:[\s,]+[A-Z]+[0-9]+)*))?",
                               re.IGNORECASE)),
    ("mypy", re.compile(r"\btype:\s*ignore(?:\[(?P<rules>[^\]]*)\])?")),
    ("pyright", re.compile(r"\bpyright:\s*ignore(?:\[(?P<rules>[^\]]*)\])?")),
    ("pylint", re.compile(r"\bpylint:\s*disable(?P<scope>-next)?=(?P<rules>[\w\-, ]+)")),
    ("shellcheck", re.compile(r"\bshellcheck\s+disable=(?P<rules>[\w,]+)")),
    ("bandit", re.compile(r"\bnosec\b(?:\s+(?P<rules>[A-Z]\d+(?:[\s,]+[A-Z]\d+)*))?")),
    ("biome", re.compile(r"\bbiome-ignore(?:-all|-start)?\s+(?P<rules>[\w/\-]+)")),
    ("deno", re.compile(r"\bdeno-lint-ignore(?P<scope>-file)?(?P<rules>(?:\s+[\w\-]+)*)")),
    ("formatter", re.compile(r"\bprettier-ignore\b|\bfmt:\s*(?:off|skip)\b|\bisort:\s*skip\w*|\bclang-format\s+off\b|\bdeno-fmt-ignore\b")),
    ("coverage", re.compile(r"\b(?:istanbul|c8|v8)\s+ignore\b|\bpragma:\s*no\s*cover\b")),
]

ESLINT_TYPES = {
    "problem": {
        "no-undef", "no-unused-vars", "no-unsafe-finally", "no-unreachable", "no-dupe-keys",
        "no-cond-assign", "no-fallthrough", "no-redeclare", "no-self-assign", "no-const-assign",
        "valid-typeof", "use-isnan", "no-sparse-arrays", "no-constant-condition", "no-async-promise-executor",
        "no-await-in-loop", "no-promise-executor-return", "no-unsafe-optional-chaining", "getter-return",
        "no-import-assign", "no-loss-of-precision", "array-callback-return", "no-dupe-else-if",
        "no-unsafe-negation", "no-setter-return", "no-unused-private-class-members", "no-use-before-define",
        "react-hooks/rules-of-hooks", "react-hooks/exhaustive-deps", "@typescript-eslint/no-floating-promises",
        "@typescript-eslint/no-misused-promises", "@typescript-eslint/no-unused-vars", "@typescript-eslint/ban-ts-comment",
        "@typescript-eslint/no-non-null-assertion", "@typescript-eslint/no-unsafe-assignment",
        "@typescript-eslint/no-unsafe-member-access", "@typescript-eslint/no-unsafe-call",
        "@typescript-eslint/no-unsafe-return", "@typescript-eslint/no-unsafe-argument",
    },
    "suggestion": {
        "eqeqeq", "no-console", "prefer-const", "no-var", "curly", "no-empty", "no-param-reassign", "no-shadow",
        "camelcase", "no-unused-expressions", "complexity", "max-lines", "max-depth", "no-restricted-syntax",
        "no-plusplus", "no-magic-numbers", "no-else-return", "no-useless-escape", "no-nested-ternary",
        "prefer-template", "no-underscore-dangle", "default-case", "no-continue", "no-alert",
        "@typescript-eslint/no-explicit-any", "@typescript-eslint/no-empty-function",
        "@typescript-eslint/explicit-module-boundary-types", "@typescript-eslint/no-require-imports",
    },
    "layout": {"max-len", "indent", "semi", "quotes", "comma-dangle", "linebreak-style", "eol-last", "no-tabs"},
}
SAFETY_RULES = {"no-eval", "no-implied-eval", "no-new-func", "no-script-url", "react/no-danger",
                "react/no-danger-with-children"}
MYPY_ENVIRONMENT = {"import", "import-untyped", "import-not-found"}
MYPY_HYGIENE = {"no-untyped-def", "no-untyped-call", "no-any-return", "no-any-unimported", "unused-ignore",
                "redundant-cast", "unused-awaitable", "truthy-bool", "possibly-undefined"}
PYRIGHT_ENVIRONMENT = {"reportMissingImports", "reportMissingModuleSource", "reportMissingTypeStubs"}
PYRIGHT_HYGIENE = {"reportUnusedImport", "reportUnusedVariable", "reportUnusedClass", "reportUnusedFunction",
                   "reportPrivateUsage", "reportUnnecessaryTypeIgnoreComment"}
PYTHON_CODES = {
    "F401": ("hygiene", "unused import"), "F403": ("hygiene", "star import"), "F405": ("hygiene", "name may come from a star import"),
    "F841": ("hygiene", "unused local variable"), "F811": ("correctness", "redefinition of an unused name"),
    "F821": ("correctness", "undefined name"), "F632": ("correctness", "is-comparison with a literal"),
    "E711": ("correctness", "comparison to None with =="), "E712": ("correctness", "comparison to True/False with =="),
    "E722": ("correctness", "bare except also catches KeyboardInterrupt and SystemExit"),
    "E731": ("style", "lambda assigned to a name"), "E741": ("style", "ambiguous variable name"),
    "E501": ("style", "line too long"), "W605": ("correctness", "invalid escape sequence"),
    "B006": ("correctness", "mutable default argument"), "B008": ("correctness", "call in a default argument"),
    "B023": ("correctness", "loop variable captured by a closure"), "B904": ("correctness", "raise without from inside except"),
    "BLE001": ("correctness", "blind except Exception"), "T201": ("hygiene", "print found"),
    "C901": ("style", "function too complex"), "ERA001": ("hygiene", "commented-out code"),
}
PYTHON_PREFIXES = [
    ("PLE", "correctness"), ("PLW", "correctness"), ("PLR", "style"), ("PLC", "style"), ("ASYNC", "correctness"),
    ("BLE", "correctness"), ("DTZ", "correctness"), ("ANN", "style"), ("ARG", "hygiene"), ("ERA", "hygiene"),
    ("PERF", "hygiene"), ("RET", "hygiene"), ("SIM", "hygiene"), ("TRY", "hygiene"), ("RUF", "unknown"),
    ("C4", "style"), ("PT", "hygiene"), ("UP", "style"), ("COM", "style"), ("E9", "correctness"),
    ("E7", "correctness"), ("W6", "correctness"), ("F", "correctness"), ("E", "style"), ("W", "style"),
    ("B", "correctness"), ("S", "safety"), ("D", "style"), ("N", "style"), ("I", "style"), ("Q", "style"),
    ("A", "hygiene"),
]
PYLINT_NAMES = {
    "correctness": {"no-member", "undefined-variable", "used-before-assignment", "unsubscriptable-object",
                    "not-callable", "no-value-for-parameter", "too-many-function-args", "unexpected-keyword-arg",
                    "dangerous-default-value", "bare-except", "broad-except", "broad-exception-caught",
                    "possibly-used-before-assignment", "cell-var-from-loop"},
    "environment": {"import-error", "no-name-in-module"},
    "hygiene": {"protected-access", "unused-argument", "unused-import", "unused-variable", "fixme",
                "global-statement", "redefined-outer-name"},
    "style": {"invalid-name", "line-too-long", "missing-module-docstring", "missing-class-docstring",
              "missing-function-docstring", "missing-docstring", "consider-using-f-string", "no-else-return",
              "too-many-arguments", "too-many-locals", "too-many-branches", "too-many-statements",
              "too-few-public-methods", "too-many-instance-attributes", "too-many-return-statements"},
}
PYLINT_ID_PREFIX = {"C": "style", "R": "style", "W": "hygiene", "E": "correctness", "F": "correctness"}
SHELLCHECK = {
    "SC2086": ("correctness", "unquoted expansion splits words and globs"),
    "SC2046": ("correctness", "unquoted command substitution splits words"),
    "SC2068": ("correctness", "unquoted array expansion splits elements"),
    "SC2048": ("correctness", "unquoted $* splits words"),
    "SC2155": ("correctness", "declare and assign together masks the return value"),
    "SC2154": ("correctness", "variable referenced but not assigned"),
    "SC2015": ("correctness", "A && B || C is not if-then-else"),
    "SC2164": ("safety", "cd without a failure check continues in the wrong directory"),
    "SC2059": ("safety", "variable used as a printf format string"),
    "SC2115": ("safety", "rm on a path built from a possibly empty variable"),
    "SC2034": ("hygiene", "variable appears unused"), "SC2016": ("hygiene", "expression in single quotes does not expand"),
    "SC2181": ("style", "check exit code directly instead of $?"), "SC2001": ("style", "sed where parameter expansion works"),
    "SC2002": ("style", "useless cat"), "SC1090": ("environment", "cannot follow a non-constant source"),
    "SC1091": ("environment", "cannot follow the sourced file"),
}
BIOME_GROUPS = {"correctness": "correctness", "suspicious": "correctness", "security": "safety",
                "style": "style", "complexity": "hygiene", "performance": "hygiene", "a11y": "hygiene"}
ACTIONS = {
    "correctness": "actionable: fix the cause, delete the suppression, rerun the tool",
    "safety": "actionable: fix the cause, delete the suppression, rerun the tool",
    "unscoped": "actionable: name the exact rule or fix the cause; a blanket switch hides every rule",
    "environment": "keep while the missing module or stubs stay missing",
    "hygiene": "keep or fix by project preference; no correctness risk named by the rule",
    "style": "keep or fix by project preference; style only",
    "formatter": "functional formatting directive; keep",
    "coverage": "coverage exclusion; keep or drop by project policy",
    "unknown": "read the rule's documentation and classify it before acting",
}
ESLINT_CATEGORY = {"problem": "correctness", "suggestion": "hygiene", "layout": "style"}
ESLINT_CONFIGS = (".eslintrc.json", ".eslintrc")
FLAT_ESLINT = ("eslint.config.js", "eslint.config.mjs", "eslint.config.cjs", "eslint.config.ts",
               ".eslintrc.js", ".eslintrc.cjs", ".eslintrc.yml", ".eslintrc.yaml")


def strip_strings(line: str) -> str:
    return STRING.sub('""', line)


def code_signals(code: str) -> list:
    plain = strip_strings(code)
    signals = []
    for number in NUMBER.findall(plain):
        if number not in PLAIN_NUMBERS:
            signals.append(f"name the number {number}")
            break
    for match in (PY_TARGET.match(plain), JS_TARGET.match(plain), SH_TARGET.match(plain)):
        if match:
            name = next((group for group in match.groups() if group), "")
            short = name.split(".")[-1]
            if short and len(short) <= 2 and short not in SHORT_NAME_OK and short not in JS_KEYWORDS:
                signals.append(f"rename `{short}`")
            break
    if len(BOOLEAN_OPERATORS.findall(plain)) >= 2:
        signals.append("extract the condition into a named predicate")
    return signals


def clarity_flag(note: str, code: str, symbol: str) -> Optional[str]:
    signals = code_signals(code) if code else []
    explains = bool(EXPLANATION.search(note))
    if not signals and not explains:
        return None
    if not signals:
        return f"the note explained intent; make `{symbol}` say it (rename or extract)"
    return "; ".join(signals)


def is_constraint(note: str) -> bool:
    return bool(CONSTRAINT.search(note))


def python_symbols(tree) -> tuple:
    scopes = []
    targets = {}

    def visit(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = f"{prefix}{child.name}"
                scopes.append((child.lineno, child.end_lineno, name))
                visit(child, name + ".")
            else:
                if isinstance(child, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                    nodes = child.targets if isinstance(child, ast.Assign) else [child.target]
                    for target in nodes:
                        for leaf in ast.walk(target):
                            if isinstance(leaf, ast.Name):
                                targets.setdefault(child.lineno, leaf.id)
                            elif isinstance(leaf, ast.Attribute):
                                targets.setdefault(child.lineno, leaf.attr)
                visit(child, prefix)

    visit(tree, "")
    return scopes, targets


def python_symbol(scopes: list, targets: dict, row: int) -> str:
    enclosing = ""
    for start, end, name in scopes:
        if start == row:
            return name
        if start <= row <= end and len(name) > len(enclosing):
            enclosing = name
    if row in targets:
        return f"{targets[row]} in {enclosing}" if enclosing else targets[row]
    return enclosing or f"line {row}"


def text_symbol(lines: list, row: int, language: str) -> str:
    target = JS_TARGET if language in ("javascript", "typescript") else SH_TARGET
    scope = JS_SCOPE if language in ("javascript", "typescript") else SH_TARGET
    line = strip_strings(lines[row - 1]) if 0 < row <= len(lines) else ""
    own = ""
    match = target.match(line)
    if match:
        own = next((group for group in match.groups() if group), "")
        if own in JS_KEYWORDS:
            own = ""
    indent = len(line) - len(line.lstrip())
    enclosing = ""
    for index in range(row - 1, 0, -1):
        candidate = lines[index - 1]
        if not candidate.strip():
            continue
        depth = len(candidate) - len(candidate.lstrip())
        if depth < indent:
            found = scope.match(strip_strings(candidate))
            if found and (language in ("javascript", "typescript") or candidate.rstrip().endswith(("{", ")"))):
                enclosing = next((group for group in found.groups() if group), "")
                break
    if own and enclosing and own != enclosing:
        return f"{own} in {enclosing}"
    return own or enclosing or f"line {row}"


def next_code_row(lines: list, row: int, prefixes: tuple) -> int:
    for index in range(row + 1, len(lines) + 1):
        stripped = lines[index - 1].strip()
        if stripped and not stripped.startswith(prefixes):
            return index
    return row


def find_suppressions(text: str, language: str) -> list:
    found = []
    for tool, pattern in SUPPRESSION_PATTERNS:
        if tool in ("typescript", "eslint", "biome", "deno") and language not in ("javascript", "typescript"):
            continue
        if tool in ("mypy", "pyright", "pylint", "ruff/flake8", "bandit") and language != "python":
            continue
        if tool == "shellcheck" and language != "shell":
            continue
        for match in pattern.finditer(text):
            groups = match.groupdict()
            raw = (groups.get("rules") or "").split("--")[0]
            rules = [rule for rule in re.split(r"[\s,]+", raw.strip()) if rule]
            scope = groups.get("scope") or ""
            found.append({"tool": tool, "directive": match.group(0).strip(), "rules": rules, "scope": scope})
    return found


def eslint_rule_meta(rule: str, start: Path, root: Path) -> Optional[dict]:
    if "/" in rule:
        plugin, name = rule.rsplit("/", 1)
        packages = [f"{plugin}/eslint-plugin"] if plugin.startswith("@") else [f"eslint-plugin-{plugin}"]
    else:
        name, packages = rule, ["eslint"]
    directory = start if start.is_dir() else start.parent
    while True:
        for package in packages:
            for sub in ("lib/rules", "dist/rules"):
                for suffix in (".js", ".cjs", ".mjs"):
                    path = directory / "node_modules" / package / sub / (name + suffix)
                    if path.is_file():
                        source = path.read_text(errors="replace")
                        kind = re.search(r"\btype:\s*[\"'](problem|suggestion|layout)[\"']", source)
                        description = re.search(r"\bdescription:\s*([\"'`])((?:\\.|(?!\1).)*)\1", source)
                        if kind:
                            return {"type": kind.group(1), "description": description.group(2) if description else "",
                                    "source": str(path.relative_to(directory))}
        if directory == root or directory.parent == directory:
            return None
        directory = directory.parent


def ruff_rule(code: str) -> Optional[dict]:
    ruff = shutil.which("ruff")
    if not ruff:
        return None
    try:
        done = subprocess.run([ruff, "rule", code, "--output-format", "json"], capture_output=True, text=True,
                              timeout=30)
        data = json.loads(done.stdout) if done.returncode == 0 else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    if not isinstance(data, dict):
        return None
    return {"name": data.get("name", ""), "linter": data.get("linter", "")}


def python_code_category(code: str) -> tuple:
    if code in PYTHON_CODES:
        return PYTHON_CODES[code]
    for prefix, category in PYTHON_PREFIXES:
        if code.startswith(prefix) and code[len(prefix):][:1].isdigit():
            return category, f"{prefix} rule family"
    return "unknown", ""


def classify(entry: dict, path: Path, root: Path, lookups: dict) -> list:
    tool, rules = entry["tool"], entry["rules"]
    results = []

    def add(rule, category, description, source):
        results.append({"tool": tool, "rule": rule, "category": category, "description": description,
                        "source": source, "action": ACTIONS[category]})

    if tool in ("formatter", "coverage"):
        add(entry["directive"], tool, "", "directive")
    elif tool == "typescript":
        scope = entry["scope"]
        if scope == "nocheck":
            add("@ts-nocheck", "unscoped", "turns off type checking for the whole file", "TypeScript")
        elif scope == "ignore":
            add("@ts-ignore", "unscoped", "hides any type error on the next line", "TypeScript")
        else:
            add("@ts-expect-error", "correctness", "hides an expected type error on the next line", "TypeScript")
    elif not rules and tool in ("eslint", "ruff/flake8", "mypy", "pyright", "deno"):
        add("(all rules)", "unscoped", f"{tool} switch with no rule list", tool)
    elif tool == "bandit":
        for rule in rules or ["(all tests)"]:
            add(rule, "safety", "bandit security finding", "bandit")
    else:
        for rule in rules:
            if tool == "eslint":
                key = ("eslint", rule)
                if key not in lookups:
                    lookups[key] = eslint_rule_meta(rule, path, root)
                meta = lookups[key]
                if rule in SAFETY_RULES:
                    add(rule, "safety", meta["description"] if meta else "", meta["source"] if meta else "built-in table")
                elif meta:
                    add(rule, ESLINT_CATEGORY[meta["type"]], meta["description"], f"{meta['source']} (meta.type {meta['type']})")
                else:
                    kind = next((name for name, members in ESLINT_TYPES.items() if rule in members), "")
                    if kind:
                        add(rule, ESLINT_CATEGORY[kind], "", f"built-in table (ESLint meta.type {kind})")
                    else:
                        add(rule, "unknown", "", "not found in node_modules or the built-in table")
            elif tool == "ruff/flake8":
                key = ("ruff", rule)
                if key not in lookups:
                    lookups[key] = ruff_rule(rule)
                meta = lookups[key]
                category, description = python_code_category(rule)
                if meta:
                    add(rule, category, meta["name"], f"ruff rule ({meta['linter']})")
                else:
                    add(rule, category, description, "built-in table" if description else "none")
            elif tool == "mypy":
                if rule in MYPY_ENVIRONMENT:
                    add(rule, "environment", "missing module or stubs", "mypy error code")
                elif rule in MYPY_HYGIENE:
                    add(rule, "hygiene", "strictness check", "mypy error code")
                else:
                    add(rule, "correctness", "type error", "mypy error code")
            elif tool == "pyright":
                if rule in PYRIGHT_ENVIRONMENT:
                    add(rule, "environment", "missing module or stubs", "pyright rule")
                elif rule in PYRIGHT_HYGIENE:
                    add(rule, "hygiene", "unused or private symbol", "pyright rule")
                elif rule.startswith("report"):
                    add(rule, "correctness", "type error", "pyright rule")
                else:
                    add(rule, "unknown", "", "none")
            elif tool == "pylint":
                category = next((name for name, members in PYLINT_NAMES.items() if rule in members), "")
                if not category and re.fullmatch(r"[CRWEF]\d{4}", rule):
                    category = PYLINT_ID_PREFIX[rule[0]]
                add(rule, category or "unknown", "", "pylint message" if category else "none")
            elif tool == "shellcheck":
                category, description = SHELLCHECK.get(rule, ("unknown", ""))
                add(rule, category, description, f"https://www.shellcheck.net/wiki/{rule}")
            elif tool == "biome":
                parts = rule.split("/")
                category = BIOME_GROUPS.get(parts[1], "unknown") if len(parts) >= 3 else "unknown"
                add(rule, category, "", "biome rule group")
            else:
                add(rule, "unknown", "", "none")
    return results


def lint_configs(root: Path) -> dict:
    found = {}
    eslint_rules = {}
    for name in ESLINT_CONFIGS:
        path = root / name
        if path.is_file():
            try:
                eslint_rules.update(json.loads(path.read_text()).get("rules", {}))
                found.setdefault("eslint", []).append(name)
            except ValueError:
                found.setdefault("eslint", []).append(f"{name} (not parsed)")
    package = root / "package.json"
    if package.is_file():
        try:
            config = json.loads(package.read_text()).get("eslintConfig")
        except ValueError:
            config = None
        if isinstance(config, dict):
            eslint_rules.update(config.get("rules", {}))
            found.setdefault("eslint", []).append("package.json")
    for name in FLAT_ESLINT:
        path = root / name
        if path.is_file():
            text = path.read_text(errors="replace")
            for rule, level in re.findall(r"[\"']([@\w/\-]+)[\"']\s*:\s*\[?\s*[\"']?(error|warn|off|[012])\b", text):
                eslint_rules.setdefault(rule, level)
            found.setdefault("eslint", []).append(f"{name} (read as text, not run)")
    ruff_lists = {}
    for name in ("ruff.toml", ".ruff.toml", "pyproject.toml"):
        path = root / name
        if not path.is_file():
            continue
        text = path.read_text(errors="replace")
        if name == "pyproject.toml" and "[tool.ruff" not in text:
            continue
        found.setdefault("ruff", []).append(name)
        for key in ("select", "extend-select", "ignore", "extend-ignore"):
            match = re.search(rf"^\s*{key}\s*=\s*\[([^\]]*)\]", text, re.MULTILINE)
            if match:
                ruff_lists[key] = re.findall(r"[\"']([A-Z]+[0-9]*)[\"']", match.group(1))
    for name in ("setup.cfg", ".flake8", "tox.ini"):
        path = root / name
        if path.is_file():
            parser = configparser.ConfigParser()
            try:
                parser.read(path)
            except configparser.Error:
                continue
            if parser.has_section("flake8"):
                found.setdefault("flake8", []).append(name)
            if parser.has_section("mypy"):
                found.setdefault("mypy", []).append(name)
    for name in ("mypy.ini", ".mypy.ini"):
        if (root / name).is_file():
            found.setdefault("mypy", []).append(name)
    pyproject = root / "pyproject.toml"
    if pyproject.is_file() and "[tool.mypy" in pyproject.read_text(errors="replace"):
        found.setdefault("mypy", []).append("pyproject.toml")
    for name in ("tsconfig.json", "jsconfig.json"):
        if (root / name).is_file():
            found.setdefault("typescript", []).append(name)
    if (root / ".shellcheckrc").is_file():
        found.setdefault("shellcheck", []).append(".shellcheckrc")
    return {"files": found, "eslint_rules": eslint_rules, "ruff": ruff_lists}


def nearest_configs(path: Path, root: Path, cache: dict) -> dict:
    merged = {"files": {}, "eslint_rules": {}, "ruff": {}}
    directory = path.parent
    while True:
        if directory not in cache:
            cache[directory] = lint_configs(directory)
        local = cache[directory]
        prefix = "" if directory == root else str(directory.relative_to(root)) + "/"
        for tool, names in local["files"].items():
            merged["files"].setdefault(tool, []).extend(prefix + name for name in names)
        for rule, level in local["eslint_rules"].items():
            merged["eslint_rules"].setdefault(rule, level)
        for key, codes in local["ruff"].items():
            merged["ruff"].setdefault(key, codes)
        if directory == root or root not in directory.parents:
            return merged
        directory = directory.parent


def configured(tool: str, rule: str, configs: dict) -> str:
    files = configs["files"]
    if tool == "eslint":
        if rule in configs["eslint_rules"]:
            setting = configs["eslint_rules"][rule]
            level = setting[0] if isinstance(setting, list) and setting else setting
            return f"configured: {level}"
        return "config: " + ", ".join(files["eslint"]) if "eslint" in files else "no ESLint config found"
    if tool == "ruff/flake8":
        lists = configs["ruff"]
        for key in ("ignore", "extend-ignore"):
            if any(rule.startswith(code) for code in lists.get(key, [])):
                return f"ruff {key} lists it"
        for key in ("select", "extend-select"):
            if any(rule.startswith(code) for code in lists.get(key, [])):
                return f"ruff {key} lists it"
        selected = lists.get("select", []) + lists.get("extend-select", [])
        if selected:
            return f"not selected by the ruff config (select: {', '.join(selected)})"
        names = files.get("ruff", []) + files.get("flake8", [])
        return "config: " + ", ".join(names) if names else "no ruff or flake8 config found"
    key = {"mypy": "mypy", "typescript": "typescript", "shellcheck": "shellcheck"}.get(tool)
    if key:
        return "config: " + ", ".join(files[key]) if key in files else f"no {key} config found"
    return ""
