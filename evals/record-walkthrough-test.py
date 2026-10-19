#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

WALKCTL = Path(__file__).resolve().parents[1] / "skills/record-walkthrough/scripts/walkctl.py"
GOOD = [
    {"t": 0.0, "title": "", "text": ""},
    {"t": 1.0, "title": "Projects", "text": "Each project shows its owner, status and next action."},
    {"t": 6.5, "title": "Task details", "text": "Owner, due date and remaining work for this task."},
]


def walkctl(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(WALKCTL), *args], cwd=cwd, capture_output=True, text=True)


def write_log(folder: Path, name: str, captions: list, end: float, viewport: list) -> str:
    (folder / name).write_text(json.dumps({"captions": captions, "end": end, "viewport": viewport}))
    return name


def expect(condition: bool, detail) -> None:
    if not condition:
        raise AssertionError(detail)


def lint_cases(tmp: Path) -> None:
    ok = walkctl("lint", write_log(tmp, "good.json", GOOD, 12.0, [640, 288]), cwd=tmp)
    expect(ok.returncode == 0 and "VERDICT: PASS" in ok.stdout, ok.stdout + ok.stderr)
    rushed = [GOOD[0], GOOD[1], {**GOOD[2], "t": 2.0}]
    bad = walkctl("lint", write_log(tmp, "rushed.json", rushed, 12.0, [640, 288]), cwd=tmp)
    expect(bad.returncode == 1 and "needs" in bad.stdout and "VERDICT: FAIL" in bad.stdout, bad.stdout)
    repeat = [GOOD[0], GOOD[1], {**GOOD[2], "text": GOOD[1]["text"]}]
    bad = walkctl("lint", write_log(tmp, "repeat.json", repeat, 12.0, [640, 288]), cwd=tmp)
    expect(bad.returncode == 1 and "same body" in bad.stdout, bad.stdout)
    long = [GOOD[0], {**GOOD[1], "text": " ".join(["word"] * 40)}]
    bad = walkctl("lint", write_log(tmp, "long.json", long, 30.0, [640, 288]), cwd=tmp)
    expect(bad.returncode == 1 and "words; cut" in bad.stdout, bad.stdout)


def video_tools() -> bool:
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        return False
    filters = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True).stdout
    encoders = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
    return any(line.split()[1:2] == ["ass"] for line in filters.splitlines() if line.strip()) and "libx264" in encoders


def video_cases(tmp: Path) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc=size=640x288:rate=10:duration=12.5", "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", str(tmp / "raw.mp4")], check=True)

    stretched = walkctl("burn", "raw.mp4", write_log(tmp, "tall.json", GOOD, 12.0, [640, 360]), "s.mp4", cwd=tmp)
    expect(stretched.returncode == 1 and "stretched" in stretched.stderr, stretched.stderr)
    expect(not (tmp / "s.mp4").exists(), "a stretched recording must not be burned")

    other_run = walkctl("burn", "raw.mp4", write_log(tmp, "other.json", GOOD, 40.0, [640, 288]), "o.mp4", cwd=tmp)
    expect(other_run.returncode == 1 and "does not belong" in other_run.stderr, other_run.stderr)

    burned = walkctl("burn", "raw.mp4", "good.json", "out.mp4", cwd=tmp)
    expect(burned.returncode == 0, burned.stderr)
    result = json.loads(burned.stdout)
    expect(result["captions"] == 2 and abs(result["offset"] - 0.5) < 0.05, result)
    chapters = (tmp / "out.chapters.md").read_text()
    expect("**Projects**" in chapters and "**Task details**" in chapters, chapters)

    gate = walkctl("check", "out.mp4", cwd=tmp)
    expect(gate.returncode == 0 and "640x408" in gate.stdout and "VERDICT: PASS" in gate.stdout, gate.stdout)

    timeline = json.loads((tmp / "out.timeline.json").read_text())
    timeline["captions"][1]["start"] = timeline["captions"][1]["end"] - 1.0
    (tmp / "out.timeline.json").write_text(json.dumps(timeline))
    gate = walkctl("check", "out.mp4", cwd=tmp)
    expect(gate.returncode == 1 and "VERDICT: FAIL" in gate.stdout, gate.stdout)


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        lint_cases(Path(tmp))
        if not video_tools():
            print("walkctl_ok (lint only: ffmpeg with libass and libx264 not found, burn and check skipped)")
            return 0
        video_cases(Path(tmp))
    print("walkctl_ok (lint, burn, stretched and mismatched recordings refused, check)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
