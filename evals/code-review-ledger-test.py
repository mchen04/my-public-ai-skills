#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1] / "skills" / "code-review"
REVIEWCTL = SKILL / "scripts" / "reviewctl.py"

SOURCE_FILE = "src/demo/form.ts"
LABEL_DEFECT = "form accepts an empty label"
FORMAT_DEFECT = "formatter omits its final newline"


class LedgerCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.log = Path(self.tmp.name) / "ledger.jsonl"

    def ctl(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(REVIEWCTL), *args], capture_output=True, text=True,
                              cwd=self.tmp.name)

    def ledger(self, action: str, **flags: object) -> subprocess.CompletedProcess:
        argv = ["ledger", action, "--log", str(self.log)]
        for name, value in flags.items():
            argv += [f"--{name.replace('_', '-')}", str(value)]
        return self.ctl(*argv)

    def ok(self, action: str, **flags: object) -> str:
        result = self.ledger(action, **flags)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def refused(self, action: str, needle: str, **flags: object) -> None:
        before = self.log.read_text(encoding="utf-8") if self.log.exists() else None
        result = self.ledger(action, **flags)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(needle, result.stderr)
        after = self.log.read_text(encoding="utf-8") if self.log.exists() else None
        self.assertEqual(before, after, "a refused command must not write the ledger")

    def record(self, **flags: object) -> str:
        row = {"dimension": "form", "file": f"{SOURCE_FILE}:12", "mechanism": LABEL_DEFECT, "severity": "material",
               "state": "survived", "hunter": "hunter-1", "refuter": "refuter-1",
               "evidence": "form.ts:12 stores an empty label"}
        row.update(flags)
        return self.ok("record", **{k: v for k, v in row.items() if v is not None})

    def verdict(self) -> list[str]:
        return self.ok("verdict").strip().splitlines()

    def approvable(self) -> None:
        self.ok("judge", by="judge-1")
        self.ok("ci", state="green", evidence="gh pr checks at head: 100 pass, 0 pending")


class RefuterRules(LedgerCase):
    def setUp(self) -> None:
        super().setUp()
        self.ok("init", head="aaa")

    def test_hunter_cannot_refute_its_own_candidate(self) -> None:
        self.refused("record", "different agent", dimension="ci", file="formatter.ts:8", mechanism=FORMAT_DEFECT,
                     severity="minor", state="refuted", hunter="hunter-2", refuter="hunter-2", evidence="x")
        self.refused("record", "needs --refuter", dimension="ci", file="formatter.ts:8", mechanism=FORMAT_DEFECT,
                     severity="minor", state="refuted", hunter="hunter-2", evidence="x")
        self.record(file="formatter.ts:8", mechanism=FORMAT_DEFECT, severity="minor", state="refuted",
                    hunter="hunter-2", refuter="refuter-2", evidence="spec accepts it")

    def test_material_refute_must_cite_the_code_that_kills_it(self) -> None:
        self.refused("record", "grounded --evidence", dimension="ci", file="formatter.ts:8", mechanism=FORMAT_DEFECT,
                     severity="material", state="refuted", hunter="hunter-2", refuter="refuter-2",
                     evidence="the spec accepts this coverage loss")
        self.record(file="formatter.ts:8", mechanism=FORMAT_DEFECT, state="refuted", hunter="hunter-2",
                    refuter="refuter-2", evidence="formatter.ts:8 always appends the final newline")

    def test_refuted_row_keeps_the_claimed_severity(self) -> None:
        self.refused("record", "claimed", dimension="ci", file="a.ts:1", mechanism="m", severity="none",
                     state="refuted", hunter="h", refuter="r", evidence="a.ts:1")

    def test_judge_must_not_have_hunted_or_refuted(self) -> None:
        self.record()
        self.refused("judge", "did neither", by="hunter-1")
        self.refused("judge", "did neither", by="refuter-1")
        self.ok("judge", by="judge-1")


class CandidateIdentity(LedgerCase):
    def setUp(self) -> None:
        super().setUp()
        self.ok("init", head="aaa")

    def test_same_file_and_mechanism_reuse_the_id_across_rounds(self) -> None:
        self.assertIn("recorded C1", self.record(severity="minor"))
        self.ok("round", head="bbb")
        out = self.record(file=f"./{SOURCE_FILE}:14-16", mechanism="Form accepts -- an EMPTY label!",
                          evidence="form.ts:14 still accepts the empty label")
        self.assertIn("recorded C1 (round 2", out)
        self.assertTrue(self.verdict()[1].startswith("1 candidates,"))

    def test_refuted_defect_returns_only_with_new_evidence(self) -> None:
        self.record(state="refuted", evidence="form.ts:10 rejects blank labels")
        self.ok("round", head="bbb")
        self.refused("record", "new --evidence", dimension="form", file=f"{SOURCE_FILE}:12", mechanism=LABEL_DEFECT,
                     severity="material", state="survived", hunter="hunter-3", refuter="refuter-3",
                     evidence="form.ts:10 rejects blank labels")
        self.refused("record", "new --evidence", dimension="form", file=f"{SOURCE_FILE}:12", mechanism=LABEL_DEFECT,
                     severity="material", state="survived", hunter="hunter-3", refuter="refuter-3")
        out = self.record(hunter="hunter-3", refuter="refuter-3",
                          evidence="form.ts:16 accepts a space-only label")
        self.assertIn("recorded C1", out)

    def test_repeated_row_is_not_recorded_twice(self) -> None:
        self.record()
        self.assertIn("unchanged", self.record())
        lines = [l for l in self.log.read_text(encoding="utf-8").splitlines() if '"candidate"' in l]
        self.assertEqual(len(lines), 1)

    def test_unknown_id_is_refused(self) -> None:
        self.refused("record", "not in this ledger", id="C9", dimension="d", file="a.ts:1", mechanism="m",
                     severity="minor", state="survived", hunter="h")


class OpenFindings(LedgerCase):
    def setUp(self) -> None:
        super().setUp()
        self.ok("init", head="aaa")
        self.record()

    def test_finding_stays_open_into_the_next_round(self) -> None:
        out = self.ok("round", head="bbb")
        self.assertIn("C1", out)
        self.approvable()
        lines = self.verdict()
        self.assertIn(f"gating: C1 material {SOURCE_FILE}:12 {LABEL_DEFECT}", lines)
        self.assertEqual(lines[-1], "VERDICT: BLOCK")

    def test_fix_closes_only_when_grounded_by_another_agent(self) -> None:
        self.ok("round", head="bbb")
        self.refused("record", "grounded --evidence", id="C1", dimension="form", file=f"{SOURCE_FILE}:12",
                     mechanism=LABEL_DEFECT, severity="material", state="fixed", hunter="hunter-1", refuter="refuter-4",
                     evidence="fixed now")
        self.refused("record", "different agent", id="C1", dimension="form", file=f"{SOURCE_FILE}:12",
                     mechanism=LABEL_DEFECT, severity="material", state="fixed", hunter="hunter-1", refuter="hunter-1",
                     evidence="form.ts:14 calls validateLabel first")
        self.record(id="C1", state="fixed", refuter="refuter-4", evidence="form.ts:14 calls validateLabel first")
        self.approvable()
        lines = self.verdict()
        self.assertIn("1 candidates, 0 refuted, 0 survived (0 blocker, 0 material, 0 minor), 1 fixed", lines)
        self.assertEqual(lines[-1], "VERDICT: APPROVE")

    def test_fixed_needs_an_existing_finding(self) -> None:
        self.refused("record", "nothing open", dimension="x", file="b.ts:3", mechanism="other", severity="minor",
                     state="fixed", hunter="h", refuter="r", evidence="b.ts:3")


class Rounds(LedgerCase):
    def test_three_round_cap(self) -> None:
        self.ok("init", head="h1")
        self.ok("round", head="h2")
        self.ok("round", head="h3")
        self.refused("round", "3-round cap", head="h4")

    def test_operator_round_cap_persists_across_rounds(self) -> None:
        self.assertIn("round 1 of 5", self.ok("init", head="h1", round_cap=5))
        for number in range(2, 6):
            self.ok("round", head=f"h{number}")
        self.refused("round", "5-round cap", head="h6")

    def test_round_cap_must_be_positive(self) -> None:
        self.refused("init", "--round-cap must be positive", head="h1", round_cap=0)

    def test_zero_open_gates_a_minor_finding_in_later_rounds(self) -> None:
        result = self.ctl("ledger", "init", "--log", str(self.log), "--head", "h1", "--zero-open")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.ok("round", head="h2")
        self.record(severity="minor")
        self.approvable()
        lines = self.verdict()
        self.assertNotIn("gating: none", lines)
        self.assertEqual(lines[-1], "VERDICT: BLOCK")

    def test_init_does_not_overwrite_a_ledger(self) -> None:
        self.ok("init", head="h1")
        self.refused("init", "ledger round", head="h2")
        self.ctl("ledger", "init", "--log", str(self.log), "--head", "h2", "--fresh")
        self.assertIn('"head": "h2"', self.log.read_text(encoding="utf-8"))

    def test_old_markdown_ledger_is_rejected_with_the_fix(self) -> None:
        self.log.write_text("# Review ledger\n\n| # | dimension |\n", encoding="utf-8")
        self.refused("status", "--fresh")


class Verdict(LedgerCase):
    def setUp(self) -> None:
        super().setUp()
        self.ok("init", head="abc123")
        self.record(severity="minor")
        self.record(dimension="ci", file="formatter.ts:8", mechanism=FORMAT_DEFECT, state="refuted", hunter="hunter-2",
                    refuter="refuter-2", evidence="formatter.ts:8 appends the final newline")
        self.record(dimension="ui", file="page.vue:10", mechanism="loading state missing", severity="nit",
                    hunter="hunter-3", refuter=None)

    def test_counts_and_verdict_footer(self) -> None:
        self.approvable()
        self.assertEqual(self.verdict(), [
            "round 1 of 3, head abc123",
            "3 candidates, 1 refuted, 2 survived (0 blocker, 0 material, 1 minor, 1 nit)",
            "gating: none",
            "publish: approve",
            "VERDICT: APPROVE",
        ])

    def test_low_judge_score_publishes_a_comment(self) -> None:
        self.ok("judge", by="judge-1", score=3)
        self.ok("ci", state="green", evidence="all green")
        lines = self.verdict()
        self.assertIn("comment only: judge score 3 is below 4", lines)
        self.assertEqual(lines[-2:], ["publish: comment", "VERDICT: APPROVE"])
        self.refused("judge", "1 to 5", by="judge-2", score=7)

    def test_no_approve_without_judge_pass(self) -> None:
        self.ok("ci", state="green", evidence="all green")
        lines = self.verdict()
        self.assertIn("not approvable: judge missed-defect pass not recorded for round 1", lines)
        self.assertEqual(lines[-2:], ["publish: comment", "VERDICT: BLOCK"])

    def test_no_approve_without_green_ci(self) -> None:
        self.ok("judge", by="judge-1")
        self.assertIn("not approvable: CI not recorded green for round 1", self.verdict())
        self.ok("ci", state="red", evidence="tests failed")
        lines = self.verdict()
        self.assertIn("not approvable: CI not recorded green for round 1 (red)", lines)
        self.assertEqual(lines[-1], "VERDICT: BLOCK")

    def test_judge_and_ci_belong_to_the_current_round(self) -> None:
        self.approvable()
        self.ok("round", head="def456")
        lines = self.verdict()
        self.assertIn("not approvable: judge missed-defect pass not recorded for round 2", lines)
        self.assertIn("not approvable: CI not recorded green for round 2", lines)

    def test_no_approve_when_a_material_candidate_lacks_an_independent_refuter(self) -> None:
        self.approvable()
        self.record(dimension="auth", file="auth.ts:5", mechanism="label exceeds chosen length", severity="material",
                    hunter="hunter-4", refuter=None)
        self.record(dimension="auth", file="auth.ts:5", mechanism="label exceeds chosen length", severity="minor",
                    hunter="hunter-4", refuter=None, evidence="judged minor")
        lines = self.verdict()
        self.assertIn("not approvable: C4 (material) has no independent refuter", lines)
        self.assertEqual(lines[-1], "VERDICT: BLOCK")

    def test_judge_found_defect_turns_approve_into_block(self) -> None:
        self.approvable()
        self.assertEqual(self.verdict()[-1], "VERDICT: APPROVE")
        self.record(dimension="judge", file="form.ts:18", mechanism="missing label length check",
                    hunter="judge-1", refuter="refuter-9", evidence="form.ts:18 accepts an overlong label")
        lines = self.verdict()
        self.assertEqual(lines[-2:], ["publish: request changes", "VERDICT: BLOCK"])

    def test_unverified_material_blocks_as_comment(self) -> None:
        self.approvable()
        self.record(dimension="parser", file="parser.ts:9", mechanism="empty input skips a rule", state="unverified",
                    hunter="hunter-5", refuter="refuter-5", evidence="needs an isolated parser fixture")
        lines = self.verdict()
        self.assertIn("unsettled: C4 material parser.ts:9 empty input skips a rule", lines)
        self.assertEqual(lines[-2:], ["publish: comment", "VERDICT: BLOCK"])


class Risk(unittest.TestCase):
    def test_remote_default_branch_with_slashes_excludes_older_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            def git(*args: str) -> None:
                subprocess.run(["git", "-C", tmp, "-c", "user.email=test@example.com", "-c", "user.name=Fixture", *args],
                               check=True, capture_output=True)
            git("init", "-q")
            git("commit", "-q", "--allow-empty", "-m", "base")
            git("update-ref", "refs/remotes/origin/main", "HEAD")
            (Path(tmp) / "inherited.txt").write_text("existing behavior\n")
            git("add", ".")
            git("commit", "-q", "-m", "inherited change")
            git("update-ref", "refs/remotes/origin/release/stable", "HEAD")
            git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/release/stable")
            (Path(tmp) / "changed.txt").write_text("new behavior\n")
            git("add", ".")
            git("commit", "-q", "-m", "feature change")
            result = subprocess.run([sys.executable, str(REVIEWCTL), "scope"], cwd=tmp,
                                    capture_output=True, text=True, check=True)
            self.assertIn("surface   1 files, +1/-0, 1 commits", result.stdout)
            self.assertNotIn("inherited change", result.stdout)

    def test_a_risk_class_outranks_a_large_unclassified_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            def git(*args: str) -> None:
                subprocess.run(["git", "-C", tmp, *args], check=True, capture_output=True)
            git("init", "-q")
            git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "base")
            (Path(tmp) / "db" / "migrations").mkdir(parents=True)
            (Path(tmp) / "db" / "migrations" / "001.sql").write_text("ALTER TABLE t ADD c int;\n")
            (Path(tmp) / "blob.txt").write_text("x\n" * 5000)
            git("add", ".")
            git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "change")
            out = subprocess.run([sys.executable, str(REVIEWCTL), "risk", "--base", "HEAD~1"], cwd=tmp,
                                 capture_output=True, text=True, check=True).stdout
            ranked = [line.split()[1] for line in out.splitlines() if line.startswith("  ") and "[" in line]
            self.assertEqual(ranked[0], "db/migrations/001.sql")


if __name__ == "__main__":
    unittest.main()
