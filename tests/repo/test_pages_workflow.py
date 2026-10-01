"""The Pages workflow rebuilds site/data/status.json after every Claims run,
so a new claim shows on the site within minutes, not at the next daily build."""
from pathlib import Path

import yaml

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"


def _load(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text())


def test_pages_runs_after_every_claims_run():
    pages, claims = _load("pages.yml"), _load("claims.yml")
    # PyYAML reads the bare key `on` as the boolean True.
    trigger = pages.get("on", pages.get(True))["workflow_run"]
    assert trigger["workflows"] == ["Claims"] == [claims["name"]]
    assert trigger["types"] == ["completed"]


def test_build_skips_only_a_skipped_claims_run():
    jobs = _load("pages.yml")["jobs"]
    expr = jobs["build"]["if"]
    assert expr == ("github.event_name != 'workflow_run' || "
                    "github.event.workflow_run.conclusion != 'skipped'")
    assert "if" not in jobs["deploy"] and jobs["deploy"]["needs"] == "build"
