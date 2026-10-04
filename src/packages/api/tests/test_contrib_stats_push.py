# src/packages/api/tests/test_contrib_stats_push.py
import json

import pytest

pytest.importorskip("pyarrow")

from fakes import FakeHub  # noqa: E402
from helpmate_server.contrib.corpus_stats import (  # noqa: E402
    HISTOGRAM_PATH, MATERIALS_PATH, collect, parquet_files)
from helpmate_server.contrib.stats_push import StatsError, check, push  # noqa: E402
from test_contrib_corpus_stats import KQVK, MARKER, _put  # noqa: E402


def _manifest(*names):
    return json.dumps({"schema": 1, "files": {f"{n}.hm": {} for n in names}}).encode()


def test_refuses_an_incomplete_corpus(tmp_path):
    _put(tmp_path, KQVK)
    hub = FakeHub({"manifest.json": _manifest("KQvk", "Kvkq")})
    with pytest.raises(StatsError, match="Kvkq"):
        push(hub, tmp_path, None, b"card", dry_run=False)
    assert hub.commits == []


def test_uploads_parquet_and_card_when_missing_then_nothing_when_equal(tmp_path):
    _put(tmp_path, KQVK)
    _put(tmp_path, MARKER)
    hub = FakeHub({"manifest.json": _manifest("KQvk", "Kvkq")})
    assert "uploaded" in push(hub, tmp_path, None, b"card", dry_run=False)
    (msg, files), = hub.commits
    assert set(files) == {MATERIALS_PATH, HISTOGRAM_PATH, "README.md"}
    assert "unchanged" in push(hub, tmp_path, None, b"card", dry_run=False)
    assert len(hub.commits) == 1


def test_dry_run_uploads_nothing(tmp_path):
    _put(tmp_path, KQVK)
    hub = FakeHub({"manifest.json": _manifest("KQvk")})
    out = push(hub, tmp_path, None, b"card", dry_run=True)
    assert "would upload" in out and "1 tables" in out
    assert "1 materials rows" in out and "histogram rows" in out and hub.commits == []


def test_check_reports_missing_stale_and_fresh(tmp_path):
    _put(tmp_path, KQVK)
    hub = FakeHub({"manifest.json": _manifest("KQvk", "Kvkq")})
    assert check(hub) == [f"{MATERIALS_PATH} is not on the dataset yet"]
    hub.main[MATERIALS_PATH] = parquet_files(collect(tmp_path), None)[MATERIALS_PATH]
    assert check(hub) == ["statistics lack Kvkq"]
    _put(tmp_path, MARKER)
    hub.main[MATERIALS_PATH] = parquet_files(collect(tmp_path), None)[MATERIALS_PATH]
    assert check(hub) == []


def test_cli_check_exit_codes(tmp_path, capsys):
    from helpmate_server.contrib import cli
    import argparse
    hub = FakeHub({"manifest.json": _manifest("KQvk")})
    ns = argparse.Namespace(cmd="stats-push", check=True, tables=None, dry_run=False,
                            checkout=tmp_path, repo="x")
    assert cli.run(ns, hub_factory=lambda repo: hub) == 1
    assert "stats-push --tables" in capsys.readouterr().err


def test_cli_push_uploads_mains_card_and_registry_not_the_working_tree(tmp_path):
    from helpmate_server.contrib import cli
    import argparse
    (tmp_path / "tb").mkdir()
    _put(tmp_path / "tb", KQVK)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "hf-dataset-card.md").write_bytes(b"working tree card")
    reg = {"contributors": {"u": {"github": None, "hf": None, "display": "Main Person"}},
           "tables": {"KQvk": {"contributor": "u", "hf_pr": 7, "merged": "2026-01-02"}}}

    class FakeGit:
        calls: list = []

        def __init__(self, checkout): self.checkout = checkout

        def main_file(self, path):
            FakeGit.calls.append(path)
            return b"main card" if path.endswith(".md") else json.dumps(reg).encode()

    hub = FakeHub({"manifest.json": _manifest("KQvk")})
    ns = argparse.Namespace(cmd="stats-push", check=False, tables=str(tmp_path / "tb"), dry_run=False,
                            checkout=tmp_path, repo="x")
    assert cli.run(ns, hub_factory=lambda repo: hub, git_factory=FakeGit) == 0
    (msg, files), = hub.commits
    assert files["README.md"] == b"main card"
    import io
    import pyarrow.parquet as pq
    rows = pq.read_table(io.BytesIO(files[MATERIALS_PATH])).to_pylist()
    assert rows[0]["contributor"] == "Main Person" and rows[0]["hf_pr"] == 7


def test_cli_push_refuses_when_main_cannot_be_read(tmp_path, capsys):
    from helpmate_server.contrib import cli
    import argparse
    import subprocess

    class BadGit:
        def __init__(self, checkout): pass

        def main_file(self, path):
            raise subprocess.CalledProcessError(128, ["git"], stderr=b"not a git repository")

    hub = FakeHub({"manifest.json": _manifest("KQvk")})
    ns = argparse.Namespace(cmd="stats-push", check=False, tables=str(tmp_path), dry_run=False,
                            checkout=tmp_path, repo="x")
    assert cli.run(ns, hub_factory=lambda repo: hub, git_factory=BadGit) == 2
    assert "origin/main" in capsys.readouterr().err and hub.commits == []
