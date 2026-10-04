"""The generated pages in a real browser.

Everything else about these pages is tested as strings; this is the check that
the strings are a page a browser can actually render -- the board draws, the
step control moves it, and the links between the pages resolve.

Playwright must launch with --no-sandbox here: user namespaces are restricted
on this machine, and chromium will not start without it.
"""

import http.server
import json
import os
import socketserver
import threading
from pathlib import Path

import pytest

playwright_api = pytest.importorskip("playwright.sync_api")
ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / "site"

# Set in CI. These tests skip when the generated pages are absent, which is
# right locally -- `site/material/` is git-ignored, so a fresh checkout has
# none. In CI that same skip is a trap: the job runs, four tests quietly do
# nothing, and pytest reports success. That is precisely the failure mode
# these tests exist to catch, since a material page whose boards draw no
# pieces still renders perfectly. With this set, a missing site is a failure.
REQUIRE_SITE = os.environ.get("HELPMATE_REQUIRE_SITE") == "1"


@pytest.fixture(scope="module")
def server():
    if not (SITE / "themes.html").exists():
        msg = "site not built -- run `make site` first"
        if REQUIRE_SITE:
            pytest.fail(f"HELPMATE_REQUIRE_SITE=1 but {msg}")
        pytest.skip(msg)

    def handler(*a, **k):
        return http.server.SimpleHTTPRequestHandler(*a, directory=str(SITE), **k)

    with socketserver.TCPServer(("127.0.0.1", 0), handler) as httpd:
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
        httpd.shutdown()


@pytest.fixture(scope="module")
def browser():
    with playwright_api.sync_playwright() as p:
        b = p.chromium.launch(args=["--no-sandbox"])
        yield b
        b.close()


def _new_page_failing_on_error_responses(browser):
    """A page that fails the test on any 4xx/5xx response.

    This is what catches a wrong assetsUrl: board.js resolves piece sprites
    relative to the document, and a material page one directory down with a
    wrong relative path 404s every sprite while the page still renders a
    perfectly normal-looking, piece-less board. Nothing else notices that.
    """
    page = browser.new_page()
    bad_responses = []

    def on_response(response):
        # status.json is optional (built at deploy time, never committed): only its 404 is expected
        optional = response.status == 404 and response.url.endswith("/data/status.json")
        if response.status >= 400 and not optional:
            bad_responses.append(f"{response.status} {response.url}")

    page.on("response", on_response)
    return page, bad_responses


def _first_material_with_problems():
    index = json.loads((SITE / "data/index.json").read_text())
    return next(r["material"] for r in index if r["unique"])


def test_material_page_draws_a_board_and_steps_it(server, browser):
    material = _first_material_with_problems()
    page, bad_responses = _new_page_failing_on_error_responses(browser)
    page.goto(f"{server}/material/{material}.html")
    page.wait_for_selector(".board")
    assert page.locator(".problem").count() >= 1
    # cm-chessboard draws squares into the container.
    page.wait_for_selector(".board svg, .board canvas", timeout=5000)
    # The most valuable assertion here: the board actually drew pieces, not
    # just an empty board. A wrong assetsUrl (resolved relative to the
    # document, and a material page lives one directory down from the site
    # root) makes every piece sprite 404 while the page still renders a
    # flawless, piece-less chessboard -- no error visible anywhere else.
    piece_count = page.locator(".board svg use, .board svg image").count()
    assert piece_count > 0, "board drew no pieces -- check assetsUrl in board.js"
    before = page.locator(".board-controls .ply").first.inner_text()
    page.locator('.board-controls button[data-step="1"]').first.click()
    assert page.locator(".board-controls .ply").first.inner_text() != before
    assert not bad_responses, f"4xx/5xx responses: {bad_responses}"
    page.close()


def test_theme_index_links_reach_a_material_page(server, browser):
    """The real flow: themes are collapsed, so a reader expands one first."""
    page, bad_responses = _new_page_failing_on_error_responses(browser)
    page.goto(f"{server}/themes.html")
    page.wait_for_selector("details.theme-block")
    assert page.locator("details.theme-block[open]").count() == 0, \
        "themes should start collapsed"

    page.locator("details.theme-block > summary").first.click()
    link = page.locator(".theme-problems a").first
    href = link.get_attribute("href")
    link.click()
    page.wait_for_load_state()
    assert href.replace("material/", "") in page.url
    assert not bad_responses, f"4xx/5xx responses: {bad_responses}"
    page.close()


def test_a_problem_theme_link_opens_that_theme_on_the_index(server, browser):
    """Linking into a collapsed <details> is the risk the collapse creates.

    A problem page links to `themes.html#<theme>`; if the target stays shut
    the reader lands on a closed box and the link looks broken. Browsers
    differ on whether fragment navigation opens it, so theme-open.js does,
    and this pins that it works -- including for a theme whose id contains a
    colon, which is not a usable CSS selector."""
    page, bad_responses = _new_page_failing_on_error_responses(browser)
    material = _first_material_with_problems()
    page.goto(f"{server}/material/{material}.html")
    link = page.locator(".problem .themes a").first
    theme = link.inner_text()
    link.click()
    page.wait_for_load_state()
    page.wait_for_timeout(300)

    state = page.evaluate(
        "() => {const el = document.getElementById("
        "decodeURIComponent(location.hash.slice(1)));"
        " return el && {open: el.open, tag: el.tagName};}")
    assert state, f"no element for theme {theme!r} at {page.url}"
    assert state["tag"] == "DETAILS"
    assert state["open"], f"theme {theme!r} did not open when linked to"
    assert not bad_responses, f"4xx/5xx responses: {bad_responses}"
    page.close()


def test_open_all_expands_every_theme_so_find_in_page_works(server, browser):
    """Closed <details> are invisible to find-in-page outside Chrome, so the
    control that restores Ctrl+F over the whole index has to actually work."""
    page, bad_responses = _new_page_failing_on_error_responses(browser)
    page.goto(f"{server}/themes.html")
    page.wait_for_selector("details.theme-block")
    total = page.locator("details.theme-block").count()

    page.click("#open-all")
    page.wait_for_timeout(200)
    assert page.locator("details.theme-block[open]").count() == total
    assert "Close" in page.locator("#open-all").inner_text()

    page.click("#open-all")
    page.wait_for_timeout(200)
    assert page.locator("details.theme-block[open]").count() == 0
    assert not bad_responses, f"4xx/5xx responses: {bad_responses}"
    page.close()


def test_a_marker_material_says_no_helpmate_exists(server, browser):
    index = json.loads((SITE / "data/index.json").read_text())
    marker = next((r["material"] for r in index if not r["has_helpmate"]), None)
    if marker is None:
        pytest.skip("no marker material in the index")
    page, bad_responses = _new_page_failing_on_error_responses(browser)
    page.goto(f"{server}/material/{marker}.html")
    assert "No helpmate exists" in page.content()
    assert not bad_responses, f"4xx/5xx responses: {bad_responses}"
    page.close()


def test_the_spa_still_routes_after_the_nav_change(server, browser):
    page, bad_responses = _new_page_failing_on_error_responses(browser)
    page.goto(f"{server}/index.html#/materials")
    page.wait_for_selector("#materials-table tbody tr")
    assert page.locator("#screen-materials").is_visible()
    assert not bad_responses, f"4xx/5xx responses: {bad_responses}"
    page.close()


def test_statistics_screen_renders(server, browser):
    page = browser.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{server}/index.html#/stats")
    page.wait_for_selector("#screen-stats svg rect.bar")
    assert page.locator("#screen-stats svg").count() >= 3
    page.goto(f"{server}/index.html#/stats/KQvk")
    page.wait_for_selector("#stats-material svg rect.bar")
    page.goto(f"{server}/index.html#/stats/Nonsense")
    page.wait_for_selector("#stats-material :text('unknown material')")
    page.goto(f"{server}/index.html#/stats/%E0%A4%A")
    page.wait_for_selector("#stats-material :text('unknown material')")
    page.close()
    assert errors == []
