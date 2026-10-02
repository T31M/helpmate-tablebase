"""tools/stamp_site.py: every deploy must fetch a fresh set of files.

Without it, a browser pairs a cached old js/materials.js with the new
index.html (GitHub Pages sends max-age=600) and the Materials screen crashes.
"""
import http.server
import re
import shutil
import socketserver
import subprocess
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "stamp_site.py"
SITE = ROOT / "site"


VENDOR = ROOT / "src" / "packages" / "web" / "helpmate_web" / "static" / "vendor"


@pytest.fixture
def site(tmp_path):
    """The site as `make site` builds it, from committed files only: CI runs on a
    fresh checkout, where the generated vendor copy, themes.html and material
    pages (all git-ignored) do not exist."""
    dst = tmp_path / "site"
    generated = {"material", "vendor", "themes.html", "tests"}   # top level only: data/material/ is committed

    def ignore(d, names):
        top = Path(d) == SITE
        return [n for n in names if (top and n in generated) or n in ("__pycache__", "status.json")]

    shutil.copytree(SITE, dst, ignore=ignore)
    shutil.copytree(VENDOR / "cm-chessboard", dst / "vendor" / "cm-chessboard")
    subprocess.run([sys.executable, str(ROOT / "tools" / "render_site.py"),
                    "--data", str(dst / "data"), "--out", str(dst)],
                   check=True, capture_output=True, text=True)
    return dst


def run(site, version):
    return subprocess.run([sys.executable, str(SCRIPT), str(site), version],
                          capture_output=True, text=True)


def snapshot(site):
    return {str(p.relative_to(site)): p.read_bytes() for p in site.rglob("*") if p.is_file()}


REL_IMPORT = re.compile(r"""\b(?:from|import)\s*\(?\s*["'](\.{1,2}/[^"']+)["']""")
REL_ATTR = re.compile(r"""(?:src|href)=["']((?![a-zA-Z][a-zA-Z0-9+.-]*:|//|/|#)[^"']+\.(?:js|css)[^"']*)["']""")


def test_every_relative_import_and_asset_is_stamped(site):
    r = run(site, "abc123")
    assert r.returncode == 0, r.stderr
    seen = 0
    for p in list(site.joinpath("js").rglob("*.js")) + list(site.joinpath("vendor").rglob("*.js")):
        for url in REL_IMPORT.findall(p.read_text()):
            seen += 1
            assert url.endswith("?v=abc123"), f"{p}: {url}"
    assert seen > 10
    pages = list(site.glob("*.html")) + list((site / "material").glob("*.html"))
    assert len(pages) >= 3
    for p in pages:
        urls = REL_ATTR.findall(p.read_text())
        assert urls, p
        for url in urls:
            assert url.endswith("?v=abc123"), f"{p}: {url}"
    assert 'const V = "?v=abc123";' in (site / "js" / "app.js").read_text()
    assert "data/${name}.json${V}" in (site / "js" / "app.js").read_text()


def test_stamping_twice_changes_nothing_and_a_new_version_replaces(site):
    assert run(site, "abc123").returncode == 0
    once = snapshot(site)
    assert run(site, "abc123").returncode == 0
    assert snapshot(site) == once
    assert run(site, "def456").returncode == 0
    twice = snapshot(site)
    assert all(b"abc123" not in v for v in twice.values())
    assert b'const V = "?v=def456";' in twice["js/app.js"]


@pytest.mark.parametrize("bad", ["a b", "x/y", "v?1", "", "a;b", "é"])
def test_bad_version_is_refused_and_touches_nothing(site, bad):
    before = snapshot(site)
    r = run(site, bad)
    assert r.returncode != 0
    assert snapshot(site) == before


def test_missing_v_line_fails_loudly(site):
    app = site / "js" / "app.js"
    app.write_text(app.read_text().replace('const V = "";', ""))
    r = run(site, "abc123")
    assert r.returncode == 1
    assert "const V" in r.stderr


def test_unstamped_sources_are_committed_unstamped():
    assert 'const V = "";' in (SITE / "js" / "app.js").read_text()
    assert "?v=" not in (SITE / "index.html").read_text()


def test_stamped_site_renders_materials_in_a_browser(site):
    sync_api = pytest.importorskip("playwright.sync_api")
    if not (site / "data" / "materials.json").exists():
        pytest.skip("site/data/materials.json missing")
    assert run(site, "abc123").returncode == 0

    def handler(*a, **k):
        return http.server.SimpleHTTPRequestHandler(*a, directory=str(site), **k)

    class Quiet(socketserver.TCPServer):
        allow_reuse_address = True

    with Quiet(("127.0.0.1", 0), handler) as httpd:
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{httpd.server_address[1]}/index.html#/materials"
        try:
            with sync_api.sync_playwright() as pw:
                try:
                    browser = pw.chromium.launch(args=["--no-sandbox"])
                except Exception as e:  # no chromium installed
                    pytest.skip(f"chromium unavailable: {e}")
                page = browser.new_page()
                errors, requested = [], []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.on("console", lambda m: m.type == "error" and errors.append(m.text))
                page.on("request", lambda r: requested.append(r.url))
                page.goto(url)
                page.wait_for_selector("#materials-lede")
                page.wait_for_function(
                    "document.querySelectorAll('#materials-table tbody tr, table tbody tr').length > 0")
                browser.close()
        finally:
            httpd.shutdown()
    # status.json is not committed, so its 404 is expected (the page copes)
    errors = [e for e in errors if "status.json" not in e and "404" not in e]
    assert errors == []
    assert any("js/materials.js?v=abc123" in u for u in requested)
    assert any("data/materials.json?v=abc123" in u for u in requested)
