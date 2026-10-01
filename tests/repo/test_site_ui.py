"""The site's Materials and front pages in a real browser, with and without
status.json, at desktop and phone width."""
import functools
import http.server
import json
import shutil
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "packages" / "api" / "tests"))
from fakes import FakeGitHub, FakeHub  # noqa: E402
from helpmate_server.contrib.registry import Registry  # noqa: E402
from helpmate_server.contrib.site_status import build_status  # noqa: E402

CLAIM = ("### Materials\n\nKQvkqbb\n\n### Hugging Face username\n\npop\n\n"
         "### Name to credit\n\n<i>pop</i>\n\n### Credit\n\n- [ ] Do not name me in the credits.\n")


def _status(tmp_path) -> dict:
    """What the Pages workflow deploys: real build_status output (fake Hub and GitHub),
    so the browser tests break when the Python side and the JS reader drift apart."""
    done = ("KRBvkqq", "KRBvkqr")
    manifest = {"schema": 1, "files": {f"{m}.hm": {"sha256": "a", "size": 1} for m in done}}
    hub = FakeHub({"manifest.json": json.dumps(manifest).encode()})
    gh = FakeGitHub([{"number": 40, "title": "claim: KQvkqbb", "body": CLAIM,
                      "user": {"login": "pop"}, "created_at": "2026-09-20T00:00:00Z",
                      "labels": [], "state": "open"}])
    table = {"hf_pr": 1, "claim": None, "merged": "x", "generator_version": "0.19.0", "verification": None}
    reg = Registry(tmp_path / "c.json", {
        "contributors": {"T31M": {"github": "T31M", "hf": "T31M", "display": "T31M"},
                         "bold": {"github": None, "hf": None, "display": "<b>bold</b>"}},
        "tables": {"KRBvkqq": {**table, "contributor": "T31M"}, "KRBvkqr": {**table, "contributor": "bold"}}})
    return build_status(hub, gh, reg, datetime(2026, 10, 1, 5, 17, tzinfo=timezone.utc))


def test_build_status_has_every_key_the_site_reads(tmp_path):
    s = _status(tmp_path)
    assert isinstance(s["generated_at"], str)
    assert set(s["counts"]["six"]) == {"done", "in review", "claimed", "open", "not needed"}
    assert all(isinstance(v, int) for v in s["counts"]["six"].values())
    for m in s["materials"].values():
        assert {"state", "contributor", "hf_pr", "claim"} <= set(m)
    for c in s["contributors"]:
        assert {"display", "hf", "github", "anonymous", "tables", "six"} <= set(c)
    assert s["materials"]["KQvkqbb"] == {"state": "claimed", "contributor": "<i>pop</i>",
                                         "hf_pr": None, "claim": 40}


def _serve(d: Path):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(d))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _copy_site(tmp_path) -> Path:
    if not (ROOT / "site" / "vendor").exists():
        pytest.skip("run `make site` first")
    d = tmp_path / "site"
    shutil.copytree(ROOT / "site", d)
    (d / "data" / "status.json").unlink(missing_ok=True)
    return d


@pytest.fixture(params=[True, False], ids=["with-status", "without-status"])
def site(request, tmp_path):
    d = _copy_site(tmp_path)
    if request.param:
        (d / "data" / "status.json").write_text(json.dumps(_status(tmp_path)))
    srv = _serve(d)
    yield f"http://127.0.0.1:{srv.server_port}/", request.param
    srv.shutdown()


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch(args=["--no-sandbox"])
        except Exception as exc:  # no browser installed on this machine
            pytest.skip(f"chromium unavailable: {exc}")
        yield b
        b.close()


NO_HSCROLL = "document.documentElement.scrollWidth <= window.innerWidth + 1"


@pytest.mark.parametrize("width", [1280, 390])
def test_materials_page(site, browser, width):
    url, has_status = site
    page = browser.new_page(viewport={"width": width, "height": 900})
    page.goto(url + "#/materials?state=open&prio=1")
    page.wait_for_selector("#materials-table tbody tr")
    assert page.is_visible("#screen-materials")
    assert page.input_value('[data-f="state"]') == "open"
    assert page.input_value('[data-f="prio"]') == "1"
    rows = page.locator("#materials-table tbody tr")
    assert rows.count() > 0
    assert all("P1" in t for t in rows.locator("td:nth-child(3)").all_inner_texts())
    assert ("as of" in page.inner_text("#materials-asof")) == has_status
    options = page.locator('#materials-controls [data-f="contributor"] option').count()
    page.select_option('[data-f="state"]', "all")
    page.fill('[data-f="q"]', "KQvk???")
    assert "q=KQvk" in page.url
    assert page.is_visible("#screen-materials")
    # changing a filter must not re-initialise the screen (that would append
    # the contributor options again)
    assert page.locator('#materials-controls [data-f="contributor"] option').count() == options
    page.select_option('[data-f="prio"]', "all")
    assert page.locator('#materials-controls [data-f="contributor"] option').count() == options
    assert page.locator("#materials-table tbody tr").count() == 35
    if has_status:
        # an HTML-looking name is shown literally and creates no element
        assert page.locator("#materials-table td", has_text="<i>pop</i>").count() == 1
        assert page.locator("#materials-table i").count() == 0
    assert page.evaluate(NO_HSCROLL)
    page.close()


@pytest.mark.parametrize("width", [1280, 390])
def test_front_contributors(site, browser, width):
    url, has_status = site
    page = browser.new_page(viewport={"width": width, "height": 900})
    page.goto(url + "#/")
    page.wait_for_selector("#contrib-progress:not(:empty)")
    assert ("T31M" in page.inner_text("#contrib-cards")) == has_status
    if has_status:
        assert "<b>bold</b>" in page.inner_text("#contrib-cards")
        assert page.locator("#contrib-cards b").count() == 0
    assert "of 645" in page.inner_text("#contrib-progress")
    assert page.evaluate(NO_HSCROLL)
    page.close()


def test_malformed_status_is_treated_as_missing(tmp_path, browser):
    d = _copy_site(tmp_path)
    (d / "data" / "status.json").write_text('{"materials": {}}')
    srv = _serve(d)
    page = browser.new_page()
    try:
        page.goto(f"http://127.0.0.1:{srv.server_port}/#/materials")
        page.wait_for_selector("#materials-table tbody tr")
        assert "State unavailable" in page.inner_text("#materials-asof")
        assert page.locator("#screen-materials .status.bad").count() == 0
        assert page.locator("#materials-table tbody tr").count() > 0
    finally:
        page.close()
        srv.shutdown()


def test_unknown_contributor_in_the_hash_shows_no_rows(site, browser):
    url, _ = site
    page = browser.new_page()
    page.goto(url + "#/materials?contributor=nobody")
    page.wait_for_selector("#materials-count:not(:empty)")
    assert page.input_value('[data-f="contributor"]') == "nobody"
    assert page.locator("#materials-table tbody tr").count() == 0
    assert page.inner_text("#materials-count").startswith("0 of ")
    assert "contributor=nobody" in page.url
    page.close()


def test_sorting_by_state_follows_the_state_order(site, browser):
    url, _ = site
    page = browser.new_page()
    page.goto(url + "#/materials")
    page.wait_for_selector("#materials-table tbody tr")
    page.click('#materials-table th[data-key="state"]')
    states = page.locator("#materials-table tbody td:nth-child(4)").all_inner_texts()
    order = ["open", "claimed", "in review", "done", "not needed"]
    ranks = [order.index(s) for s in states]
    assert ranks == sorted(ranks)
    page.close()
