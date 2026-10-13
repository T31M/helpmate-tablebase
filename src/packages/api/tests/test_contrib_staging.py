import json

from fakes import FakeHub
from helpmate_server.contrib.verify import _is_staged_for, _stage


def _hub(files, head="h1"):
    hub = FakeHub({"manifest.json": b'{"schema":1,"files":{}}'})
    hub.add_pr(2, files, head=head)
    return hub


def test_first_stage_downloads_everything_and_records_shas(tmp_path):
    hub = _hub({"KQvk.hm": b"table-1", "KQvk.stats.json": b"{}"})
    got = _stage(hub, hub.pull_request(2), tmp_path / "files")
    assert sorted(got) == ["KQvk.hm", "KQvk.stats.json"]
    rec = json.loads((tmp_path / "files" / ".files.json").read_text())
    assert rec["head"] == "h1" and set(rec["files"]) == {"KQvk.hm", "KQvk.stats.json"}
    assert _is_staged_for(tmp_path / "files", "h1")


def test_new_head_downloads_only_changed_files_and_drops_removed(tmp_path):
    hub = _hub({"KQvk.hm": b"table-1", "KQvk.stats.json": b"{}", "KRvk.hm": b"r", "KRvk.stats.json": b"{}"})
    _stage(hub, hub.pull_request(2), tmp_path / "files")
    hub.add_pr(2, {"KQvk.hm": b"table-2", "KQvk.stats.json": b"{}"}, head="h2")   # KQvk changed, KRvk removed
    got = _stage(hub, hub.pull_request(2), tmp_path / "files")
    assert got == ["KQvk.hm"]
    assert (tmp_path / "files" / "KQvk.hm").read_bytes() == b"table-2"
    assert not (tmp_path / "files" / "KRvk.hm").exists()
    assert _is_staged_for(tmp_path / "files", "h2")


def test_partial_file_is_downloaded_again(tmp_path):
    hub = _hub({"KQvk.hm": b"table-1", "KQvk.stats.json": b"{}"})
    _stage(hub, hub.pull_request(2), tmp_path / "files")
    (tmp_path / "files" / "KQvk.hm").write_bytes(b"tab")             # truncated
    assert _stage(hub, hub.pull_request(2), tmp_path / "files") == ["KQvk.hm"]


def test_legacy_head_marker_is_migrated_without_redownloading_identical_files(tmp_path):
    hub = _hub({"KQvk.hm": b"table-1", "KQvk.stats.json": b"{}"}, head="h2")
    d = tmp_path / "files"
    d.mkdir()
    (d / ".head").write_text("h1")
    (d / "KQvk.hm").write_bytes(b"table-1")
    (d / "KQvk.stats.json").write_bytes(b"{}")
    assert _stage(hub, hub.pull_request(2), d) == []
    assert not (d / ".head").exists() and _is_staged_for(d, "h2")
