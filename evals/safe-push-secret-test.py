#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCANNER = ROOT / "skills" / "safe-push" / "scripts" / "redact-secrets.py"
SPEC = importlib.util.spec_from_file_location("safe_push_redact_secrets", SCANNER)
assert SPEC and SPEC.loader
scanner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = scanner
SPEC.loader.exec_module(scanner)


class SecretScannerConfidenceTest(unittest.TestCase):
    def findings(self, text: str, path: str = "example.ts") -> list[str]:
        return [finding.kind for finding in scanner.findings_for(text, path)]

    def test_suppresses_equal_credentials_for_loopback_database(self) -> None:
        self.assertEqual(
            self.findings('const url = "postgresql://developer:developer@127.0.0.1:5432/app"'),
            [],
        )

    def test_flags_distinct_loopback_database_password(self) -> None:
        url = "postgresql://developer:" + "actual-secret@localhost/app"
        self.assertEqual(
            self.findings(f'const url = "{url}"'),
            ["credential-url"],
        )

    def test_flags_equal_credentials_for_remote_database(self) -> None:
        url = "postgresql://developer:" + "developer@db.example.com/app"
        self.assertEqual(
            self.findings(f'const url = "{url}"'),
            ["credential-url"],
        )

    def test_does_not_treat_autocomplete_values_as_password_assignments(self) -> None:
        source = 'autoComplete={mode === "register" ? "new-password" : "current-password"}'
        self.assertEqual(self.findings(source), [])

    def test_suppresses_one_character_generic_test_marker(self) -> None:
        self.assertEqual(self.findings('const token = "|"'), [])

    def test_flags_credential_like_generic_literal(self) -> None:
        value = "not-a-placeholder-" + "secret"
        self.assertEqual(
            self.findings(f'const token = "{value}"'),
            ["secret-assignment"],
        )

    def test_config_assignment_remains_strict_for_short_values(self) -> None:
        self.assertEqual(self.findings("PASSWORD=x", ".env"), ["secret-assignment"])

    def test_empty_config_assignment_never_reads_the_next_key_as_its_value(self) -> None:
        source = "PASSWORD=\nAPI_HOST=service.example.com\n"
        self.assertEqual(self.findings(source, ".env"), [])
        self.assertEqual(scanner.redact_text(source, ".env"), (source, 0))

    def test_redaction_uses_the_same_confidence_boundary(self) -> None:
        local_url = "postgresql://developer:" + "developer@localhost/app"
        remote_url = "postgresql://developer:" + "actual-secret@db.example.com/app"
        source = (
            f'const local = "{local_url}"\n'
            f'const remote = "{remote_url}"\n'
            'const token = "|"\n'
        )
        redacted, count = scanner.redact_text(source, "example.ts")
        self.assertEqual(count, 1)
        self.assertIn("[REDACTED]@db.example.com", redacted)
        self.assertIn("developer:developer@localhost", redacted)
        self.assertIn('token = "|"', redacted)


class TernaryKeyChoiceTest(unittest.TestCase):
    GENERIC = '"AbCdEf0123456789AbCdEf0123456789xyz"'

    def kinds(self, text: str) -> list[str]:
        return [finding.kind for finding in scanner.findings_for(text, "a.py")]

    def test_ternary_key_name_is_not_a_secret(self) -> None:
        self.assertEqual([], self.kinds('key = isProd ? "prod_name_value" : "dev_name_value"\n'))

    def test_second_ternary_branch_is_also_a_key_name(self) -> None:
        self.assertEqual([], self.kinds('key = isProd ? "a" : "dev_name_value_here"\n'))

    def test_secret_after_a_ternary_statement_is_still_flagged(self) -> None:
        self.assertIn(
            "secret-assignment",
            self.kinds(f"u = c ? a : b; secret = {self.GENERIC}\n"),
        )

    def test_secret_after_a_url_query_string_is_still_flagged(self) -> None:
        self.assertIn(
            "secret-assignment",
            self.kinds(f'API = "https://x/y?z"; secret = {self.GENERIC}\n'),
        )

    def test_secret_beside_a_query_string_in_a_dict_is_still_flagged(self) -> None:
        self.assertIn(
            "secret-assignment",
            self.kinds(f'cfg = {{"url": "x?y", "secret": {self.GENERIC}}}\n'),
        )


class SafePushSecretTest(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.repo = Path(self.scratch.name)
        self.git("init", "-q")
        self.git("config", "user.email", "safe-push-test@example.com")
        self.git("config", "user.name", "Safe Push Test")
        (self.repo / "README.md").write_text("fixture\n")
        self.git("add", "README.md")
        self.git("commit", "-qm", "base")

    def git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=self.repo,
            text=True,
            capture_output=True,
            check=True,
        )

    def scan(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCANNER), *args],
            cwd=self.repo,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_worktree_check_reports_location_without_echoing_secret(self) -> None:
        db_pass = "correct-" + "horse-battery"
        url = "postgres://agent:" + db_pass + "@db.internal/app"
        (self.repo / "notes.md").write_text(f"Temporary access: {url}\n")

        result = self.scan("check-working-tree")

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("credential-url", result.stdout)
        self.assertIn("notes.md", result.stdout)
        self.assertNotIn(db_pass, result.stdout + result.stderr)

    def test_redact_removes_url_token_and_private_key_values(self) -> None:
        db_pass = "moonlight-" + "river-93"
        provider_value = "ghp_" + "A" * 36
        key_body = "cHJpdmF0ZS1rZXkt" + "Zml4dHVyZQ=="
        database_name = "DATABASE_" + "URL"
        database_prefix = database_name + "=" + "postgres://worker:"
        key_name = "api_" + "key"
        private_key_begin = "-----BEGIN " + "PRIVATE KEY-----"
        private_key_end = "-----END " + "PRIVATE KEY-----"
        content = (
            f"{database_prefix}{db_pass}@db.internal/jobs\n"
            f'{key_name} = "{provider_value}"\n'
            f"{private_key_begin}\n"
            f"{key_body}\n"
            f"{private_key_end}\n"
        )
        target = self.repo / "config.txt"
        target.write_text(content)

        result = self.scan("redact", "--", "config.txt")

        self.assertEqual(result.returncode, 0, result.stderr)
        redacted = target.read_text()
        self.assertNotIn(db_pass, redacted)
        self.assertNotIn(provider_value, redacted)
        self.assertNotIn(key_body, redacted)
        self.assertGreaterEqual(redacted.count("[REDACTED]"), 3)
        self.assertEqual(self.scan("check-working-tree").returncode, 0)

    def test_placeholders_and_environment_references_are_left_alone(self) -> None:
        config = self.repo / "config.py"
        config.write_text(
            'api_key = os.environ["API_KEY"]\n'
            'password = "<read-from-keychain>"\n'
            'not_password = "literal-value"\n'
        )
        example = self.repo / ".env.example"
        example.write_text("API_KEY=your_api_key_here\nPASSWORD=${APP_PASSWORD}\n")

        before = config.read_text() + example.read_text()
        result = self.scan("check-working-tree")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(before, config.read_text() + example.read_text())

    def test_redact_refuses_symlinks_instead_of_editing_the_target(self) -> None:
        db_pass = "linked-" + "credential"
        real_file = self.repo / "real.md"
        real_file.write_text(
            "Database: postgres://link:" + db_pass + "@db.internal/link\n"
        )
        link = self.repo / "linked.md"
        link.symlink_to(real_file.name)

        result = self.scan("redact", "--", "linked.md")

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(db_pass, real_file.read_text())
        self.assertNotIn(db_pass, result.stdout + result.stderr)

    def test_staged_secret_is_found_when_worktree_copy_is_clean(self) -> None:
        db_pass = "staged-" + "value-only"
        target = self.repo / "partial.md"
        target.write_text(
            "Database: postgres://stage:" + db_pass + "@db.internal/staged\n"
        )
        self.git("add", "partial.md")
        target.write_text(
            "Database: postgres://stage:[REDACTED]@db.internal/staged\n"
        )

        result = self.scan("check-working-tree")

        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("staged:partial.md", result.stdout)
        self.assertNotIn(db_pass, result.stdout + result.stderr)

    def test_followup_redaction_commit_does_not_clean_outgoing_history(self) -> None:
        db_pass = "first-" + "commit-secret"
        target = self.repo / "deploy.md"
        target.write_text(
            "Database: postgres://release:" + db_pass + "@db.internal/release\n"
        )
        self.git("add", "deploy.md")
        self.git("commit", "-qm", "add deployment note")

        first_scan = self.scan("check-range", "HEAD~1..HEAD")
        self.assertEqual(first_scan.returncode, 2, first_scan.stderr)
        self.assertNotIn(db_pass, first_scan.stdout + first_scan.stderr)

        redact = self.scan("redact", "--", "deploy.md")
        self.assertEqual(redact.returncode, 0, redact.stderr)
        self.git("add", "deploy.md")
        self.git("commit", "-qm", "redact deployment note")

        range_scan = self.scan("check-range", "HEAD~2..HEAD")
        self.assertEqual(range_scan.returncode, 2, range_scan.stderr)
        self.assertIn("credential-url", range_scan.stdout)
        self.assertNotIn(db_pass, range_scan.stdout + range_scan.stderr)


if __name__ == "__main__":
    unittest.main()
