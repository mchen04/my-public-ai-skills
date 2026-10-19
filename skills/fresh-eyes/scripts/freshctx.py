#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "loop" / "scripts"))
try:
    import runctl
except ImportError:
    print("freshctx: the loop skill (runctl.py) must be installed beside fresh-eyes", file=sys.stderr)
    raise SystemExit(2)

FAMILIES = ("claude", "codex")
minimal_env = runctl.minimal_env
VERDICT_RE = re.compile(r"^\s*(?:VERDICT:\s*(APPROVE|BLOCK|PASS|FAIL)|SCORE:\s*(\d+(?:\.\d+)?))\s*$", re.I)
CROSS_FAMILY = "independently-verified (cross-family)"
SAME_FAMILY = "independently-verified (same-family fresh context)"
DEFAULT_TIMEOUT = 600
TOOL_SETS = {
    "read": ["Read", "Grep", "Glob"],
    "work": ["Bash", "Read", "Write", "Edit", "Grep", "Glob"],
}
CODEX_SANDBOX = {"read": "read-only", "work": "workspace-write"}
CLAUDE_EFFORTS = {"low", "medium", "high", "xhigh", "max"}
CODEX_EFFORTS = {"low", "medium", "high", "xhigh"}


def binary(family: str) -> str | None:
    found = shutil.which(family)
    if found:
        return found
    candidates = [Path.home() / ".local" / "bin" / family]
    try:
        prefix = subprocess.run(
            ["npm", "prefix", "-g"], capture_output=True, text=True, timeout=20, stdin=subprocess.DEVNULL
        ).stdout.strip()
        if prefix:
            candidates.append(Path(prefix) / "bin" / family)
    except (OSError, subprocess.SubprocessError):
        pass
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def version_of(exe: str) -> str:
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as error:
        return f"error: {error}"
    text = (out.stdout or out.stderr).strip().splitlines()
    for line in text:
        if not line.startswith("WARNING"):
            return line.strip()
    return "unknown"


def login_state(family: str, exe: str) -> tuple[bool, str]:
    try:
        if family == "claude":
            out = subprocess.run([exe, "auth", "status"], capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)
            try:
                data = json.loads(out.stdout or "{}")
            except json.JSONDecodeError:
                data = {}
            if data.get("loggedIn") is True:
                return True, str(data.get("authMethod", "logged in"))
            return False, (out.stdout or out.stderr).strip()[:120] or "not logged in"
        out = subprocess.run([exe, "login", "status"], capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)
        text = (out.stdout + out.stderr).strip()
        for line in text.splitlines():
            if line.lower().startswith("logged in"):
                return True, line.strip()
        return False, text.splitlines()[-1][:120] if text else "not logged in"
    except (OSError, subprocess.SubprocessError) as error:
        return False, f"error: {error}"


def current_family() -> str:
    claude = os.environ.get("CLAUDECODE") == "1" or bool(os.environ.get("CLAUDE_CODE_SESSION_ID"))
    codex = any(os.environ.get(name) for name in ("CODEX_THREAD_ID", "CODEX_SANDBOX", "CODEX_SANDBOX_NETWORK_DISABLED"))
    if claude and codex:
        return "unknown"
    if claude:
        return "claude"
    if codex:
        return "codex"
    return "unknown"


def detect() -> dict:
    families = {}
    for family in FAMILIES:
        exe = binary(family)
        if not exe:
            families[family] = {"available": False, "reason": f"no {family} executable on PATH"}
            continue
        logged_in, detail = login_state(family, exe)
        families[family] = {
            "available": logged_in,
            "path": exe,
            "version": version_of(exe),
            "login": detail,
            "model": "default",
        }
        if not logged_in:
            families[family]["reason"] = "not logged in"
    current = current_family()
    other = [f for f in FAMILIES if f != current and families[f]["available"]]
    same = [f for f in FAMILIES if f == current and families[f]["available"]]
    return {
        "current": current,
        "families": families,
        "cross_family": other[0] if other and current != "unknown" else None,
        "same_family": same[0] if same else None,
        "any": next((f for f in FAMILIES if families[f]["available"]), None),
    }


def default_effort(family: str, model: str, fallback: str = "low") -> str:
    if family == "claude" and model == "default":
        return "medium"
    return fallback


def claude_command(
    prompt: str,
    model: str = "default",
    effort: str | None = None,
    output: str = "text",
    tools: str | None = None,
    allow_unsandboxed_claude: bool = False,
) -> list[str]:
    if tools == "work" and not allow_unsandboxed_claude:
        raise ValueError("Claude write workers require --allow-unsandboxed-claude; use Codex for a workspace sandbox")
    effort = effort if effort is not None else default_effort("claude", model)
    if effort not in CLAUDE_EFFORTS:
        raise ValueError(f"claude effort must be one of {sorted(CLAUDE_EFFORTS)}")
    command = ["claude", "-p", prompt, "--no-session-persistence", "--safe-mode", "--output-format", output, "--effort", effort]
    if output == "stream-json":
        command.append("--verbose")
    if model != "default":
        command.extend(["--model", model])
    if tools:
        command.extend(["--tools", ",".join(TOOL_SETS[tools]), "--allowedTools", *TOOL_SETS[tools]])
    else:
        command.extend(["--tools", ""])
    return command


def codex_command(
    prompt: str,
    model: str = "default",
    effort: str | None = None,
    output_path: Path | None = None,
    sandbox: str = "read-only",
    cwd: Path | None = None,
    json_events: bool = False,
) -> list[str]:
    effort = effort if effort is not None else default_effort("codex", model)
    if effort not in CODEX_EFFORTS:
        raise ValueError(f"codex effort must be one of {sorted(CODEX_EFFORTS)}")
    command = [
        "codex", "exec", "--ephemeral",
        "--config", f'model_reasoning_effort="{effort}"',
        "--skip-git-repo-check", "--sandbox", sandbox, "--color", "never",
    ]
    if cwd is not None:
        command.extend(["--cd", str(cwd)])
    if json_events:
        command.append("--json")
    if model != "default":
        command.extend(["--model", model])
    if output_path is not None:
        command.extend(["--output-last-message", str(output_path)])
    command.append(prompt)
    return command


def resolve_command(command: list[str]) -> list[str]:
    exe = binary(command[0])
    if not exe:
        raise FileNotFoundError(f"{command[0]} is not installed or not on PATH")
    return [exe, *command[1:]]


def execute(command: list[str], cwd: Path | None, timeout: int, env: dict | None = None) -> dict:
    return _execute_once(command, cwd, timeout, env)


def _execute_once(command: list[str], cwd: Path | None, timeout: int, env: dict | None) -> dict:
    anchor = None
    try:
        anchor = subprocess.Popen(
            [sys.executable, "-c", "import signal; signal.pause()"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=os.setpgrp,
        )
        process = subprocess.Popen(
            command, cwd=str(cwd) if cwd else None, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, stdin=subprocess.DEVNULL, env=env if env is not None else minimal_env(),
            preexec_fn=lambda: os.setpgid(0, anchor.pid),
        )
    except OSError as error:
        if anchor is not None:
            _reap_group(anchor.pid)
            anchor.wait(timeout=5)
        return {"exit": -1, "stdout": "", "stderr": str(error)}
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _reap_group(anchor.pid)
        process.communicate(timeout=5)
        anchor.wait(timeout=5)
        return {"exit": -1, "stdout": "", "stderr": f"timed out after {timeout}s; process group {anchor.pid} killed"}
    _reap_group(anchor.pid)
    anchor.wait(timeout=5)
    return {"exit": process.returncode, "stdout": stdout, "stderr": runctl.redact(stderr)}


def _reap_group(pgid: int) -> None:
    import time
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(pgid, sig)
        except (ProcessLookupError, PermissionError):
            return
        deadline = time.time() + 2
        while time.time() < deadline:
            try:
                os.waitpid(pgid, os.WNOHANG)
            except ChildProcessError:
                pass
            try:
                os.killpg(pgid, 0)
            except (ProcessLookupError, PermissionError):
                return
            time.sleep(0.05)


def reviewer_prompt(charter: str, artifacts: list[tuple[str, str]], scored: bool) -> str:
    closing = (
        "Your LAST LINE must be exactly 'SCORE: <n>' on a 1-10 scale."
        if scored
        else "Your LAST LINE must be exactly one of 'VERDICT: APPROVE' or 'VERDICT: BLOCK'."
    )
    parts = [
        "You are an independent reviewer. You did not write this and have no stake in it.",
        "Review only the artifact and charter below. Do not consider who wrote it or any",
        "previous review. Do not read ledgers, reports, or commit messages that narrate",
        "prior findings. Cite a concrete location for every finding.",
        "",
        "CHARTER",
        charter.strip(),
        "",
    ]
    for name, body in artifacts:
        parts.extend([f"ARTIFACT: {name}", body.rstrip(), ""])
    parts.append(closing + " No other closing format is legal.")
    return "\n".join(parts)


def final_text(family: str, result: dict, output_path: Path | None) -> str:
    if family == "codex" and output_path is not None and output_path.exists():
        return runctl.redact(output_path.read_text(encoding="utf-8"))
    return runctl.redact(result["stdout"])


def parse_verdict(text: str) -> str | None:
    lines = [line for line in text.strip().splitlines() if line.strip()]
    if not lines:
        return None
    match = VERDICT_RE.match(lines[-1])
    if not match:
        return None
    return f"VERDICT: {match.group(1).upper()}" if match.group(1) else f"SCORE: {match.group(2)}"


def independence_label(current: str, used: str) -> str:
    if current in FAMILIES and used in FAMILIES and current != used:
        return CROSS_FAMILY
    return SAME_FAMILY


def choose_family(requested: str, info: dict) -> tuple[str | None, str]:
    if requested in FAMILIES:
        if info["families"][requested]["available"]:
            return requested, ""
        return None, f"{requested} is unavailable: {info['families'][requested].get('reason', 'unknown')}"
    if requested == "other":
        if info["cross_family"]:
            return info["cross_family"], ""
        fallback = info["same_family"] or info["any"]
        if fallback:
            why = "current family unknown" if info["current"] == "unknown" else "only one family is available"
            return fallback, f"no cross-family verifier ({why}); using a fresh {fallback} context"
        return None, "no model family is available"
    if requested == "same":
        fallback = info["same_family"] or info["any"]
        return (fallback, "") if fallback else (None, "no model family is available")
    return None, f"unknown family request {requested!r}"


def apply_role(args: argparse.Namespace) -> None:
    if not getattr(args, "role", None):
        return
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import roles
    spec = roles.role(args.role)
    if args.family in ("other", None):
        args.family = spec["family"]
    if args.model == "default":
        args.model = spec["model"]
    if args.effort is None:
        args.effort = spec["effort"]


def cmd_dispatch(args: argparse.Namespace) -> int:
    apply_role(args)
    info = detect()
    family, note = choose_family(args.family, info)
    if family is None:
        print(json.dumps({"error": note, "detect": info}, indent=2))
        return 2
    effort = args.effort if args.effort is not None else default_effort(family, args.model, "medium")
    charter = runctl.redact(Path(args.charter).read_text(encoding="utf-8"))
    artifacts = [(Path(p).name, runctl.redact(Path(p).read_text(encoding="utf-8", errors="replace"))) for p in args.artifact]
    prompt = reviewer_prompt(charter, artifacts, args.scored)
    out_dir = Path(args.out) if args.out else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "prompt.txt").write_text(prompt, encoding="utf-8")

    verdict = None
    attempts = 0
    record: dict = {}
    while verdict is None and attempts < 1 + args.retries:
        attempts += 1
        with tempfile.TemporaryDirectory(prefix="freshctx-") as tmp:
            last = Path(tmp) / "last.txt"
            if family == "claude":
                command = claude_command(prompt, args.model, effort, "text", "read" if args.repo else None)
            else:
                command = codex_command(prompt, args.model, effort, last, "read-only", Path(args.repo) if args.repo else None)
            result = execute(resolve_command(command), Path(args.repo) if args.repo else None, args.timeout)
            text = final_text(family, result, last)
        record = {"attempt": attempts, "exit": result["exit"], "stderr": result["stderr"][-400:], "home": result.get("home")}
        if out_dir:
            (out_dir / f"response-{attempts}.txt").write_text(text, encoding="utf-8")
        if result["exit"] == 0:
            verdict = parse_verdict(text)
    summary = {
        "family": family,
        "model": args.model,
        "current": info["current"],
        "independence": independence_label(info["current"], family),
        "note": note,
        "verdict": verdict,
        "attempts": attempts,
        "indeterminate": verdict is None,
        "last_run": record,
        "out": str(out_dir) if out_dir else None,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    if verdict is None:
        return 3
    return 0


def parse_claude_stream(stdout: str) -> dict:
    calls: list[dict] = []
    final = ""
    cost = None
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind = event.get("type")
        if kind == "assistant":
            for block in event.get("message", {}).get("content", []):
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    calls.append({"tool": block.get("name", ""), "input": block.get("input", {})})
        elif kind == "result":
            final = str(event.get("result") or "")
            cost = event.get("total_cost_usd")
    return {"final": final, "tool_calls": calls, "cost_usd": cost}


def parse_codex_stream(stdout: str) -> dict:
    calls: list[dict] = []
    final = ""
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "item.completed":
            continue
        item = event.get("item", {})
        if item.get("type") == "command_execution":
            calls.append({"tool": "Bash", "input": {"command": item.get("command", "")}, "output": (item.get("aggregated_output") or "")[:2000], "exit_code": item.get("exit_code")})
        elif item.get("type") == "file_change" and item.get("status") == "completed":
            for change in item.get("changes", []):
                if isinstance(change, dict) and isinstance(change.get("path"), str):
                    calls.append({"tool": "Edit", "input": {"file_path": change["path"], "kind": change.get("kind")}})
        elif item.get("type") == "agent_message":
            final = item.get("text", "")
    return {"final": final, "tool_calls": calls, "cost_usd": None}


def summarize_calls(calls: list[dict]) -> dict:
    commands = [c["input"].get("command", "") for c in calls if c["tool"] == "Bash"]
    reads = [c["input"].get("file_path", "") for c in calls if c["tool"] == "Read"]
    writes = [c["input"].get("file_path", "") for c in calls if c["tool"] in {"Write", "Edit"}]
    return {"commands": commands, "reads": reads, "writes": writes}


def run_worker(
    family: str,
    prompt: str,
    cwd: Path,
    tools: str = "work",
    model: str = "default",
    effort: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    env: dict | None = None,
    allow_unsandboxed_claude: bool = False,
) -> dict:
    effort = effort if effort is not None else default_effort(family, model)
    if family == "claude":
        command = claude_command(prompt, model, effort, "stream-json", tools, allow_unsandboxed_claude)
    elif family == "codex":
        command = codex_command(prompt, model, effort, None, CODEX_SANDBOX[tools], cwd, json_events=True)
    else:
        raise ValueError(f"unknown family {family!r}")
    result = execute(resolve_command(command), cwd, timeout, env)
    parsed = parse_claude_stream(result["stdout"]) if family == "claude" else parse_codex_stream(result["stdout"])
    record = {
        "family": family,
        "model": model,
        "requested_effort": effort,
        "cwd": str(cwd),
        "exit": result["exit"],
        "error": "" if result["exit"] == 0 else result["stderr"][-400:],
        "home": result.get("home"),
        **parsed,
        **summarize_calls(parsed["tool_calls"]),
    }
    if result["exit"] == 0 and not record["final"]:
        record["error"] = "worker returned no final answer"
    return redact_record(record)


def redact_record(value):
    if isinstance(value, str):
        return runctl.redact(value)
    if isinstance(value, list):
        return [redact_record(v) for v in value]
    if isinstance(value, dict):
        return {k: redact_record(v) for k, v in value.items()}
    return value


def cmd_run(args: argparse.Namespace) -> int:
    prompt = Path(args.prompt_file).read_text(encoding="utf-8")
    extra = {}
    for item in args.env:
        key, sep, value = item.partition("=")
        if not sep:
            print(f"--env needs KEY=VALUE, got {item!r}", file=sys.stderr)
            return 2
        extra[key] = value
    try:
        env = minimal_env(extra)
    except ValueError as error:
        print(f"run: {error}", file=sys.stderr)
        return 2
    try:
        record = run_worker(args.family, prompt, Path(args.cwd).resolve(), args.tools, args.model, args.effort, args.timeout, env,
                            args.allow_unsandboxed_claude)
    except ValueError as error:
        print(f"run: {error}", file=sys.stderr)
        return 2
    text = json.dumps(record, indent=2, sort_keys=True)
    if args.record:
        Path(args.record).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if record["exit"] == 0 and not record["error"] else 1


def cmd_detect(args: argparse.Namespace) -> int:
    info = detect()
    if args.json:
        print(json.dumps(info, indent=2, sort_keys=True))
    else:
        for family, state in info["families"].items():
            mark = "available" if state["available"] else f"unavailable ({state.get('reason', 'unknown')})"
            extra = f" {state.get('version', '')} {state.get('login', '')}".rstrip() if state["available"] else ""
            print(f"{family}: {mark}{extra}")
        print(f"current: {info['current']}")
        print(f"cross-family verifier: {info['cross_family'] or 'none'}")
    return 0 if info["any"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fresh-context dispatch through the installed CLIs.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    det = sub.add_parser("detect", help="which model families can run here")
    det.add_argument("--json", action="store_true")
    det.set_defaults(func=cmd_detect)

    disp = sub.add_parser("dispatch", help="one blinded reviewer in an ephemeral context")
    disp.add_argument("--family", default="other", help="other | same | claude | codex (default: other)")
    disp.add_argument("--charter", required=True, help="file holding the exact standard, pasted verbatim")
    disp.add_argument("--artifact", action="append", default=[], help="file to review; repeatable")
    disp.add_argument("--repo", help="directory the reviewer may read; omit for a prompt-only review")
    disp.add_argument("--model", default="default", help="explicit model id; never guessed")
    disp.add_argument("--role", help="take family, model and effort from assets/roles.json (review, review-claude, ...)")
    disp.add_argument("--effort")
    disp.add_argument("--scored", action="store_true", help="ask for SCORE: n instead of a verdict")
    disp.add_argument("--retries", type=int, default=2, help="re-dispatch on a missing token (default 2)")
    disp.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    disp.add_argument("--out", help="directory for the prompt and raw responses")
    disp.set_defaults(func=cmd_dispatch)

    run = sub.add_parser("run", help="one recorded worker in an ephemeral context")
    run.add_argument("--family", required=True, choices=FAMILIES)
    run.add_argument("--prompt-file", required=True)
    run.add_argument("--cwd", required=True)
    run.add_argument("--tools", default="work", choices=sorted(TOOL_SETS))
    run.add_argument("--model", default="default")
    run.add_argument("--effort")
    run.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    run.add_argument("--env", action="append", default=[], help="KEY=VALUE for the worker; repeatable")
    run.add_argument("--record", help="write the JSON recording here")
    run.add_argument("--allow-unsandboxed-claude", action="store_true",
                     help="explicitly allow Claude write tools with host file access; operator permission rules still apply")
    run.set_defaults(func=cmd_run)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
