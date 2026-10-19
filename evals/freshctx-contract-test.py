#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("freshctx", ROOT / "skills" / "fresh-eyes" / "scripts" / "freshctx.py")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class CommandConstruction(unittest.TestCase):
    def test_completed_codex_edits_are_recorded_but_failed_edits_are_not(self):
        import json
        events = [{"type": "item.completed", "item": {"type": "file_change",
                   "status": status, "changes": [{"path": path, "kind": "update"}]}}
                  for status, path in (("completed", "greet/SKILL.md"), ("failed", "private.txt"))]
        parsed = MODULE.parse_codex_stream("\n".join(json.dumps(event) for event in events))
        self.assertEqual(["greet/SKILL.md"], MODULE.summarize_calls(parsed["tool_calls"])["writes"])

    def test_claude_prompt_precedes_variadic_tool_options(self):
        command = MODULE.claude_command("the prompt", "default", "low", "stream-json", "work", True)
        self.assertEqual(command[:3], ["claude", "-p", "the prompt"])
        self.assertIn("--safe-mode", command)
        self.assertNotIn("--setting-sources", command)
        self.assertLess(command.index("the prompt"), command.index("--allowedTools"))
        self.assertIn("--verbose", command)
        self.assertNotIn("--permission-mode", command)
        self.assertNotIn("--model", command)

    def test_read_tools_exclude_bash_and_writes(self):
        command = MODULE.claude_command("p", "opus", "medium", "text", "read")
        tools = command[command.index("--allowedTools") + 1:]
        self.assertNotIn("Bash", tools)
        self.assertNotIn("Write", tools)
        self.assertEqual(command[command.index("--model") + 1], "opus")

    def test_codex_default_model_is_never_named(self):
        command = MODULE.codex_command("p", "default", "low", Path("/x/last.txt"), "read-only", Path("/repo"), True)
        self.assertNotIn("--model", command)
        self.assertIn("--ephemeral", command)
        self.assertIn("--json", command)
        self.assertEqual(command[command.index("--cd") + 1], "/repo")
        self.assertEqual(command[-1], "p")

    def test_model_defaults_preserve_other_models_and_explicit_effort(self):
        command = MODULE.claude_command("p", "default")
        self.assertEqual(command[command.index("--effort") + 1], "medium")
        for model in ("opus", "example-model"):
            command = MODULE.claude_command("p", model, "high")
            self.assertEqual(command[command.index("--effort") + 1], "high")
            self.assertEqual(command[command.index("--model") + 1], model)
        self.assertEqual("medium", MODULE.default_effort("codex", "example-model", "medium"))
        self.assertIn('model_reasoning_effort="medium"', MODULE.codex_command("p", "example-model", "medium"))

    def test_unknown_effort_is_rejected_rather_than_passed_through(self):
        with self.assertRaises(ValueError):
            MODULE.claude_command("p", "default", "ultra", "text")
        with self.assertRaises(ValueError):
            MODULE.codex_command("p", "default", "max")


class IndependenceLabel(unittest.TestCase):
    def test_cross_family_only_when_both_known_and_different(self):
        self.assertEqual(MODULE.independence_label("claude", "codex"), MODULE.CROSS_FAMILY)
        self.assertEqual(MODULE.independence_label("codex", "claude"), MODULE.CROSS_FAMILY)
        self.assertEqual(MODULE.independence_label("claude", "claude"), MODULE.SAME_FAMILY)
        self.assertEqual(MODULE.independence_label("unknown", "codex"), MODULE.SAME_FAMILY)

    def test_choose_family_falls_back_visibly(self):
        info = {"current": "claude", "cross_family": None, "same_family": "claude", "any": "claude",
                "families": {"claude": {"available": True}, "codex": {"available": False, "reason": "not logged in"}}}
        family, note = MODULE.choose_family("other", info)
        self.assertEqual(family, "claude")
        self.assertIn("only one family", note)
        family, note = MODULE.choose_family("codex", info)
        self.assertIsNone(family)
        self.assertIn("unavailable", note)

    def test_current_family_reads_only_the_environment(self):
        import os
        saved = {k: os.environ.pop(k) for k in ("CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID", "CODEX_SANDBOX", "CODEX_SANDBOX_NETWORK_DISABLED") if k in os.environ}
        try:
            self.assertEqual(MODULE.current_family(), "unknown")
            os.environ["CODEX_THREAD_ID"] = "t"
            self.assertEqual(MODULE.current_family(), "codex")
            del os.environ["CODEX_THREAD_ID"]
            os.environ["CLAUDECODE"] = "1"
            self.assertEqual(MODULE.current_family(), "claude")
            os.environ["CODEX_THREAD_ID"] = "t"
            self.assertEqual(MODULE.current_family(), "unknown")
            del os.environ["CODEX_THREAD_ID"]
        finally:
            os.environ.pop("CLAUDECODE", None)
            os.environ.update(saved)
        import inspect
        self.assertNotIn("explicit", inspect.signature(MODULE.current_family).parameters)

    def test_a_proxy_shaped_string_inside_an_event_line_does_not_drop_the_event(self):
        url = "http://" + "a:b" + "@c"
        line = '{"type":"result","result":"see ' + url + ' and mail x@y","total_cost_usd":0.1}'
        parsed = MODULE.parse_claude_stream(line)
        self.assertEqual(parsed["final"], "see " + url + " and mail x@y")
        record = MODULE.redact_record(parsed)
        self.assertIn("://[REDACTED]@", record["final"])

    def test_codex_last_message_is_redacted(self):
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            last = Path(tmp) / "last.txt"
            last.write_text("found AKIA" + "E" * 16 + " in the repo\n", encoding="utf-8")
            text = MODULE.final_text("codex", {"stdout": ""}, last)
            self.assertNotIn("AKIA", text)
            self.assertIn("[REDACTED]", text)


class VerdictParsing(unittest.TestCase):
    def test_only_the_last_line_counts(self):
        self.assertEqual(MODULE.parse_verdict("findings...\nVERDICT: BLOCK\n"), "VERDICT: BLOCK")
        self.assertEqual(MODULE.parse_verdict("SCORE: 7"), "SCORE: 7")
        self.assertIsNone(MODULE.parse_verdict("VERDICT: BLOCK\nbut also some prose"))
        self.assertIsNone(MODULE.parse_verdict("REQUEST CHANGES"))
        self.assertIsNone(MODULE.parse_verdict(""))




class RecordingParsers(unittest.TestCase):
    def test_worker_receipt_records_resolved_requested_effort_even_on_failure(self):
        for family, model, default in (("claude", "default", "medium"),
                                       ("claude", "example-model", "low"),
                                       ("codex", "default", "low"),
                                       ("codex", "example-model", "low")):
            for effort in (None, "low"):
                for code in (0, 1):
                    with patch.object(MODULE, "resolve_command", side_effect=lambda command: command), \
                         patch.object(MODULE, "execute", return_value={"exit": code, "stdout": "", "stderr": "fixture"}) as execute:
                        record = MODULE.run_worker(family, "fixture", Path("/tmp"), model=model, effort=effort,
                                                   allow_unsandboxed_claude=(family == "claude"))
                    expected = default if effort is None else effort
                    self.assertEqual(record["requested_effort"], expected)
                    self.assertNotIn("effective_effort", record)
                    command = execute.call_args.args[0]
                    if family == "claude":
                        self.assertEqual(command[command.index("--effort") + 1], expected)
                    else:
                        self.assertIn(f'model_reasoning_effort="{expected}"', command)

    def test_record_json_persists_requested_effort_without_inference_claim(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); prompt = root / "prompt"; receipt = root / "record.json"
            prompt.write_text("fixture")
            stream = json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "fixture"}})
            with patch.object(MODULE, "resolve_command", side_effect=lambda command: command), \
                 patch.object(MODULE, "execute", return_value={"exit": 0, "stdout": stream, "stderr": ""}), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(MODULE.main(["run", "--family", "codex", "--model", "example-model",
                                              "--cwd", str(root), "--prompt-file", str(prompt), "--record", str(receipt)]), 0)
            record = json.loads(receipt.read_text())
            self.assertEqual(record["requested_effort"], "low")
            self.assertNotIn("effective_effort", record)

    def test_claude_stream_records_tool_calls_and_result(self):
        stream = "\n".join([
            '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Bash","input":{"command":"make check"}}]}}',
            '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Read","input":{"file_path":"README.md"}}]}}',
            '{"type":"result","result":"DONE","total_cost_usd":0.01}',
        ])
        parsed = MODULE.parse_claude_stream(stream)
        summary = MODULE.summarize_calls(parsed["tool_calls"])
        self.assertEqual(parsed["final"], "DONE")
        self.assertEqual(summary["commands"], ["make check"])
        self.assertEqual(summary["reads"], ["README.md"])

    def test_codex_stream_records_commands(self):
        stream = "\n".join([
            '{"type":"item.completed","item":{"type":"command_execution","command":"ls","aggregated_output":"a\\n"}}',
            '{"type":"item.completed","item":{"type":"agent_message","text":"done"}}',
        ])
        parsed = MODULE.parse_codex_stream(stream)
        self.assertEqual(parsed["final"], "done")
        self.assertEqual(parsed["tool_calls"][0]["input"]["command"], "ls")


class TimeoutAndEnvironment(unittest.TestCase):
    def private_dir(self) -> str:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        return folder.name

    def test_timeout_kills_the_whole_process_group(self):
        import os
        import time
        pid_file = Path(self.private_dir()) / "worker.pid"
        result = MODULE._execute_once(["bash", "-c", "sleep 30 & echo $! > \"$OUT\"; wait"], None, 1, {**MODULE.minimal_env(), "OUT": str(pid_file)})
        self.assertEqual(result["exit"], -1)
        self.assertIn("killed", result["stderr"])
        pid = int(pid_file.read_text().strip())
        time.sleep(0.2)
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    def test_a_backgrounded_child_dies_after_a_normal_exit(self):
        import os
        import time
        pid_file = Path(self.private_dir()) / "background.pid"
        result = MODULE._execute_once(["bash", "-c", "sleep 30 >/dev/null 2>&1 & echo $! > \"$OUT\"; exit 0"], None, 10, {**MODULE.minimal_env(), "OUT": str(pid_file)})
        self.assertEqual(result["exit"], 0)
        pid = int(pid_file.read_text().strip())
        time.sleep(0.2)
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    def test_minimal_env_never_carries_the_session_and_refuses_a_credential(self):
        import os
        probe = "FRESHCTX_TEST_PROBE"
        os.environ[probe] = "sk-" + "a" * 24
        try:
            env = MODULE.minimal_env()
            self.assertNotIn(probe, env)
            with self.assertRaises(ValueError):
                MODULE.minimal_env({"PROBE": "AKIA" + "B" * 16})
        finally:
            del os.environ[probe]

    def test_records_are_redacted(self):
        record = MODULE.redact_record({"final": "key AKIA" + "C" * 16, "tool_calls": [{"output": "ghp_" + "d" * 30}]})
        self.assertNotIn("AKIA", record["final"])
        self.assertIn("[REDACTED]", record["tool_calls"][0]["output"])


class PermissionBoundaries(unittest.TestCase):
    def test_claude_write_worker_requires_explicit_permission(self):
        with patch.object(MODULE, "resolve_command", side_effect=AssertionError("must not start a process")):
            with self.assertRaisesRegex(ValueError, "allow-unsandboxed-claude"):
                MODULE.run_worker("claude", "fixture", Path("/tmp"))

    def test_prompt_only_claude_has_no_tools(self):
        command = MODULE.claude_command("fixture")
        self.assertEqual(command[command.index("--tools") + 1], "")
        self.assertNotIn("--permission-mode", command)

    def test_codex_keeps_operator_config_and_execution_rules(self):
        command = MODULE.codex_command("fixture")
        self.assertNotIn("--ignore-user-config", command)
        self.assertNotIn("--ignore-rules", command)
        self.assertEqual(command[command.index("--sandbox") + 1], "read-only")

    def test_initialization_failure_does_not_switch_profiles(self):
        with tempfile.TemporaryDirectory() as folder:
            profile = Path(folder) / "profile"
            profile.mkdir()
            (profile / "auth.json").write_text("{}")
            failure = {"exit": 1, "stdout": "", "stderr": "failed to initialize in-process app-server client"}
            success = {"exit": 0, "stdout": "different profile", "stderr": ""}
            with patch.object(MODULE, "_execute_once", side_effect=[failure, success]), \
                 patch.dict(os.environ, {"CODEX_HOME": str(profile)}):
                result = MODULE.execute(["/x/bin/codex", "exec"], None, 10, {"CODEX_HOME": str(profile)})
            self.assertEqual(result, failure)
            self.assertNotIn("home", result)


if __name__ == "__main__":
    unittest.main()
