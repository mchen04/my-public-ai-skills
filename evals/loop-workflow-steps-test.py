#!/usr/bin/env python3

from __future__ import annotations

import json
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "loop"
RUNCTL = SKILL / "scripts" / "runctl.py"
SPEC = importlib.util.spec_from_file_location("loop_runctl", RUNCTL)
RUNCTL_MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(RUNCTL_MODULE)




class LoopWorkflowStepsTest(unittest.TestCase):

    def test_parser_excludes_numbered_lists_outside_workflow_sections(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = Path(folder) / "SKILL.md"
            fixture.write_text(
                """# Fixture

1. Introductory example, not a workflow step.

## Workflow

### Pre-flight

1. Establish the baseline.

```text
2. Code-fence example, not a workflow step.
```

### Notes

2. Numbered explanatory note, not a workflow step.

### One cycle

2. Run the check.

## Appendix

3. Appendix item, not a workflow step.
""",
                encoding="utf-8",
            )
            parsed = RUNCTL_MODULE.parse_steps(fixture)
        self.assertEqual(
            [("1", "Establish the baseline.", False), ("2", "Run the check.", False)],
            parsed,
        )

    def freeze(self, text: str):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        folder = Path(holder.name)
        source = folder / "workflow.md"
        source.write_text(text)
        environment = {**os.environ, "XDG_STATE_HOME": str(folder), "AI_SKILLS_STATE": str(folder)}
        common = ["--repo", str(ROOT), "--run", "synthetic-workflow"]
        init = subprocess.run([sys.executable, str(RUNCTL), "init", *common], env=environment,
                              text=True, capture_output=True)
        self.assertEqual(init.returncode, 0, init.stderr)
        return subprocess.run([sys.executable, str(RUNCTL), "steps", "freeze", *common,
                               "--from", str(source), "--name", "demo"], env=environment,
                              text=True, capture_output=True)

    def test_freeze_tracks_known_required_steps(self):
        result = self.freeze("# Demo\n\n## Workflow\n\n1. Create the sample output.\n2. Check the sample output.\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["required"], 2)

    def test_freeze_refuses_duplicate_step_numbers(self):
        result = self.freeze("# Demo\n\n## Workflow\n\n1. Create the sample output.\n1. Check the sample output.\n")
        self.assertEqual(result.returncode, 2)
        self.assertIn("duplicate workflow step numbers", result.stderr)


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=1).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(LoopWorkflowStepsTest)
    )
    raise SystemExit(0 if result.wasSuccessful() else 1)
