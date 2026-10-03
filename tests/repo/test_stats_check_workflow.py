"""The published statistics are compared with the manifest every day and after
every Pages run; a failing run is the maintainer's notification."""
from pathlib import Path

import yaml

WF = Path(__file__).resolve().parents[2] / ".github" / "workflows"


def test_stats_check_runs_daily_and_after_pages():
    wf = yaml.safe_load((WF / "stats-check.yml").read_text())
    on = wf.get("on", wf.get(True))
    assert on["schedule"][0]["cron"]
    assert on["workflow_run"]["workflows"] == ["Pages"]
    assert "workflow_dispatch" in on
    steps = wf["jobs"]["check"]["steps"]
    assert any("stats-push --check" in s.get("run", "") for s in steps)
    assert wf["permissions"] == {"contents": "read"}
