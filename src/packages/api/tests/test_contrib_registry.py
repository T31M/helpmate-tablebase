import json
from pathlib import Path

from helpmate_server.contrib.hf import PullRequest
from helpmate_server.contrib.registry import Contributor, Registry, resolve_contributor

REPO_ROOT = Path(__file__).resolve().parents[4]


def _reg(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"schema": 1, "contributors": {
        "T31M": {"github": "T31M", "hf": "T31M", "display": "T31M"}}, "tables": {}}))
    return Registry.load(p)


def _pr(author="popeye37", description=""):
    return PullRequest(2, "Add", author, "open", description, ["KRRvkqq.hm"], "h", "u")


def test_resolution_order(tmp_path):
    reg = _reg(tmp_path)
    # 1. explicit override wins
    assert resolve_contributor(reg, _pr(), _claim("x"), "someone").github == "someone"
    # 2. GitHub: line in the description
    assert resolve_contributor(reg, _pr(description="GitHub: @pop"), _claim("x"), None).github == "pop"
    # 3. claim issue author
    c = resolve_contributor(reg, _pr(), _claim("popeye37"), None)
    assert (c.github, c.hf) == ("popeye37", "popeye37")
    # 4. registry by HF user
    assert resolve_contributor(reg, _pr(author="T31M"), None, None).key == "T31M"
    # 5. nothing
    assert resolve_contributor(reg, _pr(author="stranger"), None, None) is None


def _claim(author, hf=None, credit=None, anonymous=False):
    from helpmate_server.contrib.claims import Claim
    return Claim(50, author, "2026-09-20T00:00:00Z", ["KRRvkqq"], hf=hf, credit=credit,
                 anonymous=anonymous)


def test_new_contributor_takes_the_claim_form_fields(tmp_path):
    reg = _reg(tmp_path)
    c = resolve_contributor(reg, _pr(author="hf-name"),
                            _claim("gh-login", hf="form-hf", credit="Credit Name", anonymous=True), None)
    assert (c.key, c.github, c.hf, c.display, c.anonymous) == \
        ("gh-login", "gh-login", "form-hf", "Credit Name", True)
    c = resolve_contributor(reg, _pr(author="hf-name"), _claim("gh-login"), None)   # legacy claim
    assert (c.hf, c.display, c.anonymous) == ("hf-name", "gh-login", False)
    # the form speaks for the claim's author only, not for someone named by --contributor
    c = resolve_contributor(reg, _pr(author="hf-name"), _claim("gh-login", credit="X", anonymous=True),
                            "other")
    assert (c.display, c.anonymous) == ("other", False)


def test_record_and_save_roundtrip(tmp_path):
    reg = _reg(tmp_path)
    reg.add_contributor(Contributor("popeye37", "popeye37", "popeye37", "popeye37"))
    reg.record_table("KRRvkqq", contributor="popeye37", hf_pr=2, claim=39, merged="2026-10-01",
                     generator_version="0.20.0", verification={"result": "pass"})
    reg.save()
    again = Registry.load(reg.path)
    assert again.tables_of("popeye37") == ["KRRvkqq"]
    assert again.by_hf("popeye37").key == "popeye37"


def test_seeded_registry_credits_t31m_with_fifteen_tables():
    reg = Registry.load(REPO_ROOT / "data" / "contributions.json")
    # the seeded record: T31M's KRB set from dataset PR #1 (later contributions add more)
    seeded = [m for m in reg.tables_of("T31M") if reg.tables[m]["hf_pr"] == 1]
    assert sorted(seeded) == sorted(f"KRBvk{b}" for b in
                                    "qq qr qb qn rr rb rn bb bn nn qp rp bp np pp".split())
    assert all(reg.tables[m]["claim"] == 41 for m in seeded)
