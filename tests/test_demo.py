import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_demo.py"


def test_demo_builds_fixture_site_without_overwriting(tmp_path):
    out = tmp_path / "demo"
    cmd = [sys.executable, str(SCRIPT), "--out", str(out)]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    latest = json.loads((out / "data" / "latest.json").read_text())
    assert latest["meta"]["data_label"] == "fixture"
    assert len(latest["articles"]) == 3
    assert latest["articles"][0]["severity"] == "HIGH"
    assert latest["articles"][0]["reason"]
    assert subprocess.run(cmd, capture_output=True).returncode != 0
    assert json.loads((out / "data" / "latest.json").read_text()) == latest
