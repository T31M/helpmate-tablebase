# Batch Processing of Dataset PRs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the 39-PR wave cheap and fair: verify reuses unchanged downloads and results, identical duplicates become credited confirmations, and material pages are built later in parallel.

**Architecture:** All changes live in `helpmate_server/contrib` (verify, checks, tablefile, report, accept, registry, site_status, docs_sync, corpus_stats, cli) plus the site's `materials.js`/`lib/materials.js`. A payload hash computed during V4 identifies content independent of embedded metadata; verify and accept use it to turn duplicates of published tables into `confirmed_by` registry entries. A new `pages` command builds missing material pages in isolated parallel jobs and merges their index/theme files sequentially.

**Tech Stack:** Python 3.11/3.12, huggingface_hub, zstandard, numpy, pytest with the existing fakes (`src/packages/api/tests/fakes.py`) and the `compressed_tables` fixture (`src/packages/api/tests/conftest.py`); vanilla ES modules with `node --test`.

**Spec:** `docs/superpowers/specs/2026-10-09-batch-processing-design.md`

## Global Constraints

- Branch `feat/batch-processing` (exists; holds the spec). Never push; never touch the real Hugging Face dataset or GitHub from tests (fakes only).
- `helpmate-tables` stays importable without heavy dependencies (`numpy`, `zstandard`, `pyarrow` imported inside functions, as today).
- V1–V7 keep their meaning. New check id: **V8 "identical to the published table"**.
- Payload hash definition (used everywhere): `payload_sha256 = sha256(d0 + d1 + d2 + d3)` where `d_i` is the lowercase hex SHA-256 of decompressed plane `i` (planes 0..3 = dtm_wtm, dtm_btm, cnt_wtm, cnt_btm, as `BlockReader.plane_chunks(i)` yields them). For a marker table: `sha256(json.dumps(sidecar["cells"], sort_keys=True, separators=(",", ":")))`, prefixed `"marker:"`.
- A duplicate (material already published) is verified with V2, V3, V4 and V8 only; V5–V7 are recorded as `skip` with detail `confirmed: identical to the published table`.
- "First accepted gets published": `accept` never replaces a published file; later identical files become `confirmed_by` entries.
- Both authors are named wherever credits appear (site, status.json, README/CONTRIBUTING/card credit table, CHANGELOG, Parquet).
- `accept` still requires a passing report whose `head` equals the PR's current head.
- Report settings compared for reuse: `samples`, `oracle_samples`, `oracle_plies` (not `date`).
- Test commands: `cd /home/os/development/8pieces-helpmate && PYTHONPATH=$PWD/src/packages/api:$PWD/src/packages/api/tests python3 -m pytest <files> -q`; final: `... -m pytest src/packages/api/tests tests/repo -q --deselect tests/repo/test_deepest_render.py::test_booklet_compiles`, `ruff check src/packages/api tools`, `mypy src/packages/api/helpmate_server/contrib`, `make test-site`.
- Commit messages: subject, blank line, then `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` on its own line (use several `-m` arguments).

## Review Focus

1. **A PR revised after a passed verify where only the sidecar changed** (same `.hm`): the table must be re-verified (both shas are part of the reuse key), not reused. → test in Task 4.
2. **A duplicate whose published table is a marker** (e.g. a six-piece marker re-delivered as a real table, or two markers): marker vs marker compares the marker hash; real vs marker is "content differs" (fail). → test in Task 2.
3. **Accept run with two PRs that both contain the same unpublished material** (e.g. #19 and #31 in one run): today accept stops ("in both PR …"); keep that error, with the hint "accept them in separate runs; the second becomes a confirmation". → test in Task 5.
4. **Contributor with only confirmations** (no published table): appears in status.json contributors, credit table, `.all-contributorsrc`, and the site cards with "0 tables, N confirmations" rendered as "N independent confirmations". → tests in Task 6.
5. **`pages` interrupted after some jobs finished**: rerun resumes from its state file without rebuilding finished jobs' materials. → test in Task 7.

---

### Task 1: Payload hash

**Files:**
- Modify: `src/packages/api/helpmate_server/contrib/tablefile.py` (add `payload_sha256`)
- Modify: `src/packages/api/helpmate_server/contrib/checks.py` (`recompute_stats` returns the plane digests; `check_sidecar` exposes the payload hash)
- Modify: `src/packages/api/helpmate_server/contrib/checks.py` (`TableReport` gets `payload_sha256: str | None = None`)
- Test: `src/packages/api/tests/test_contrib_payload.py` (new)

**Interfaces:**
- Produces:
  - `tablefile.payload_sha256(path: Path, sidecar: dict | None = None) -> str` — streams all four planes; for a marker header requires `sidecar` and returns the marker form.
  - `checks.recompute_stats(reader) -> dict` additionally returns key `"plane_sha256": [hex0, hex1, hex2, hex3]` (computed from the same chunks it already reads — no extra read).
  - `checks.payload_from_planes(digests: list[str]) -> str` — `sha256("".join(digests))` hex.
  - `checks.check_sidecar(path) -> tuple[Check, str | None]` — the V4 check and the payload hash (None if V4 could not decode). Update its one caller in `verify.verify_table` to unpack the tuple and set `rep.payload_sha256`.

- [ ] **Step 1: Write the failing tests**

```python
# src/packages/api/tests/test_contrib_payload.py
import json
import shutil

from helpmate_server.contrib.checks import check_sidecar, payload_from_planes
from helpmate_server.contrib.tablefile import BlockReader, payload_sha256, read_header


def _patch_version(src, dst):
    """Same payload, different embedded generator version (same length, so offsets stay)."""
    data = bytearray(src.read_bytes())
    meta = json.loads(src.with_name(src.stem + ".stats.json").read_text())
    old = json.dumps(meta["generator_version"]).encode()
    new = old[:-2] + (b"9" if old[-2:-1] != b"9" else b"8") + old[-1:]
    i = data.find(old)
    assert i > 0
    data[i:i + len(old)] = new
    dst.write_bytes(bytes(data))


def test_payload_hash_ignores_embedded_metadata(tmp_path, compressed_tables):
    a = compressed_tables / "KQvk.hm"
    b = tmp_path / "KQvk.hm"
    _patch_version(a, b)
    assert a.read_bytes() != b.read_bytes()
    assert payload_sha256(a) == payload_sha256(b)


def test_payload_hash_differs_between_materials(compressed_tables):
    assert payload_sha256(compressed_tables / "KQvk.hm") != payload_sha256(compressed_tables / "KRvk.hm")


def test_v4_yields_the_same_payload_hash_without_an_extra_read(table_copy):
    path = table_copy / "KQvk.hm"
    check, payload = check_sidecar(path)
    assert check.status == "pass"
    assert payload == payload_sha256(path)


def test_payload_from_planes_is_sha_of_concatenated_digests():
    import hashlib
    d = ["a" * 64, "b" * 64, "c" * 64, "d" * 64]
    assert payload_from_planes(d) == hashlib.sha256("".join(d).encode()).hexdigest()


def test_marker_payload_hash_uses_the_sidecar_cells(tmp_path):
    sc = {"cells": {"invalid": {"wtm": 0, "btm": 0}, "unsolvable": {"wtm": 5, "btm": 5}}}
    from helpmate_server.contrib.tablefile import marker_payload_sha256
    h = marker_payload_sha256(sc)
    assert h.startswith("marker:") and h == marker_payload_sha256(json.loads(json.dumps(sc)))
```

If `KRvk.hm` is not in the `compressed_tables` fixture, use any second material the fixture provides (read `conftest.py`). `table_copy` is the existing fixture copying `compressed_tables` into `tmp_path`.

- [ ] **Step 2: Run to verify they fail**

Run: `PYTHONPATH=$PWD/src/packages/api:$PWD/src/packages/api/tests python3 -m pytest src/packages/api/tests/test_contrib_payload.py -q`
Expected: FAIL — `ImportError: cannot import name 'payload_sha256'`

- [ ] **Step 3: Implement**

In `tablefile.py`:

```python
def marker_payload_sha256(sidecar: dict) -> str:
    import hashlib
    cells = json.dumps(sidecar.get("cells", {}), sort_keys=True, separators=(",", ":"))
    return "marker:" + hashlib.sha256(cells.encode()).hexdigest()


def payload_sha256(path: Path | str, sidecar: dict | None = None) -> str:
    """Content identity of a table, independent of its header and embedded metadata:
    sha256 over the four planes' hex digests (planes 0..3 in file order)."""
    import hashlib
    path = Path(path)
    if read_header(path).marker:
        if sidecar is None:
            sidecar = json.loads(path.with_name(path.name[: -len(".hm")] + ".stats.json").read_text())
        return marker_payload_sha256(sidecar)
    digests = []
    with BlockReader(path) as r:
        for plane in range(4):
            h = hashlib.sha256()
            for chunk in r.plane_chunks(plane):
                h.update(chunk)
            digests.append(h.hexdigest())
    return hashlib.sha256("".join(digests).encode()).hexdigest()
```

(Import `json` at the top of `tablefile.py` if it is not imported.)

In `checks.py`: add

```python
def payload_from_planes(digests: list[str]) -> str:
    import hashlib
    return hashlib.sha256("".join(digests).encode()).hexdigest()
```

and in `recompute_stats`, keep one `hashlib.sha256()` per plane (index `s` for the dtm plane, `2 + s` for the count plane), `update` each with the chunk bytes inside the existing loop, and add `out["plane_sha256"] = [h.hexdigest() for h in hashers]` (list ordered by plane 0..3). Change `check_sidecar` to return `(Check, payload)` where payload is `payload_from_planes(got["plane_sha256"])` on every path where `recompute_stats` ran, `None` otherwise; for a marker it returns `(Check(... "skip" ...), marker_payload_sha256(sc))` when the sidecar loaded. Update `verify.verify_table`:

```python
    v4, payload = check_sidecar(path)
    rep.checks.append(v4)
    rep.payload_sha256 = payload
```

and add the field to `TableReport` in `checks.py`: `payload_sha256: str | None = None`. Update any test that calls `check_sidecar` directly to unpack the tuple (grep `check_sidecar(` in `src/packages/api/tests`).

- [ ] **Step 4: Run to verify they pass**

Run: `PYTHONPATH=$PWD/src/packages/api:$PWD/src/packages/api/tests python3 -m pytest src/packages/api/tests/test_contrib_payload.py src/packages/api/tests/test_contrib_checks.py src/packages/api/tests/test_contrib_verify_pr.py -q`
Expected: all pass

- [ ] **Step 5: Lint, type-check, commit**

```bash
ruff check src/packages/api && mypy src/packages/api/helpmate_server/contrib
git add -A src/packages/api && git commit -m "verify: payload hash of a table's planes, computed in V4" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Duplicates in verify — V1 classification and V8

**Files:**
- Modify: `src/packages/api/helpmate_server/contrib/verify.py` (`check_pr_hygiene`, `verify_table`, `verify_prs`)
- Modify: `src/packages/api/helpmate_server/contrib/checks.py` (add `check_identical`)
- Test: `src/packages/api/tests/test_contrib_duplicates.py` (new); adjust `test_contrib_verify_pr.py::test_v1_hygiene`

**Interfaces:**
- Consumes: `payload_sha256`, `TableReport.payload_sha256` (Task 1).
- Produces:
  - `check_pr_hygiene(pr, manifest_files) -> tuple[Check, set[str]]` — the V1 check and the set of duplicate materials (published `.hm`). A published `.hm` no longer fails V1; it is named in V1's detail as `duplicates of published tables: KQvkqqq, …`. Other V1 rules unchanged. Update every caller (verify_prs; tests).
  - `PublishedHashes(tables: Path, manifest_files: dict)` with method `get(material: str) -> str` — payload hash of the published table, cached in `tables / ".payload-sha256.json"` as `{material: {"hm_sha256": <manifest sha>, "payload": <hash>}}`; recomputed when the manifest sha differs; raises `MissingPublished(material)` (new exception in checks.py) if `tables/<material>.hm` is absent.
  - `check_identical(payload: str | None, published: str) -> Check` — V8: pass `"identical to the published table (payload <hash12>…)"`, fail `"content differs from the published table"`, fail `"payload unknown (V4 did not decode)"` when payload is None.
  - `verify_table(material, tables, opts, installed_version, *, published: str | None = None) -> TableReport` — when `published` is given: run V2, V3, V4 (stop early on failure as today), then V8 via `check_identical(rep.payload_sha256, published)`, then append V5, V6, V7 as `skip` with detail `confirmed: identical to the published table` (or `an earlier check failed` if V8 failed).
  - In `verify_prs`: build `PublishedHashes` once; for each duplicate material call `verify_table(..., published=hashes.get(m))`; `MissingPublished` → `UsageError(f"{m} is published but not in {tables}; sync the corpus first")`.

- [ ] **Step 1: Write the failing tests**

```python
# src/packages/api/tests/test_contrib_duplicates.py
import json
import shutil

import pytest

from helpmate_server.contrib.checks import MissingPublished, check_identical
from helpmate_server.contrib.tablefile import payload_sha256
from helpmate_server.contrib.verify import PublishedHashes, VerifyOptions, check_pr_hygiene, verify_table
from test_contrib_verify_pr import _pr


def test_v1_names_duplicates_instead_of_failing():
    check, dups = check_pr_hygiene(_pr(["KQvk.hm", "KQvk.stats.json", "KRvk.hm", "KRvk.stats.json"]),
                                   {"KQvk.hm": {"sha256": "ab", "size": 1}})
    assert check.status in ("pass", "warn") and dups == {"KQvk"}
    assert "duplicates of published tables: KQvk" in check.detail


def test_v8_pass_fail_and_unknown():
    assert check_identical("a" * 64, "a" * 64).status == "pass"
    assert check_identical("a" * 64, "b" * 64).status == "fail"
    assert check_identical(None, "b" * 64).status == "fail"
    assert check_identical("marker:x", "a" * 64).status == "fail"     # real vs marker


def test_published_hashes_cache_and_invalidation(tmp_path, compressed_tables):
    shutil.copy(compressed_tables / "KQvk.hm", tmp_path)
    shutil.copy(compressed_tables / "KQvk.stats.json", tmp_path)
    ph = PublishedHashes(tmp_path, {"KQvk.hm": {"sha256": "s1", "size": 1}})
    h = ph.get("KQvk")
    assert h == payload_sha256(tmp_path / "KQvk.hm")
    cache = json.loads((tmp_path / ".payload-sha256.json").read_text())
    assert cache["KQvk"] == {"hm_sha256": "s1", "payload": h}
    cache["KQvk"]["payload"] = "stale"
    (tmp_path / ".payload-sha256.json").write_text(json.dumps(cache))
    assert PublishedHashes(tmp_path, {"KQvk.hm": {"sha256": "s1", "size": 1}}).get("KQvk") == "stale"  # cache hit
    assert PublishedHashes(tmp_path, {"KQvk.hm": {"sha256": "s2", "size": 1}}).get("KQvk") == h        # sha changed
    with pytest.raises(MissingPublished):
        PublishedHashes(tmp_path, {"KRvk.hm": {"sha256": "x", "size": 1}}).get("KRvk")


def test_duplicate_runs_v2_to_v4_and_v8_and_skips_v5_to_v7(table_copy):
    published = payload_sha256(table_copy / "KQvk.hm")
    rep = verify_table("KQvk", table_copy, VerifyOptions(samples=10, oracle_samples=1, oracle_plies=1, seed=1),
                       "99.0.0", published=published)
    ids = {c.id: c for c in rep.checks}
    assert [ids[k].status for k in ("V2", "V3", "V4", "V8")] == ["pass"] * 4
    assert all(ids[k].status == "skip" and "confirmed" in ids[k].detail for k in ("V5", "V6", "V7"))
    assert rep.passed


def test_duplicate_with_different_content_fails(table_copy):
    rep = verify_table("KQvk", table_copy, VerifyOptions(seed=1), "99.0.0", published="f" * 64)
    assert not rep.passed and any(c.id == "V8" and c.status == "fail" for c in rep.checks)
```

Also add, in the same file, a `verify_prs` test with a `FakeHub` whose manifest lists `KQvk.hm` and whose PR #2 contains `KQvk.hm`+sidecar (reuse `_hub_with_kqvk_pr` / `_tables_without_kqvk` helpers from `test_contrib_verify_pr.py`, but keep KQvk in `--tables` this time): the run passes, the report's KQvk checks contain V8 pass and V5–V7 skip; and a variant where `--tables` lacks the published KQvk → the run exits 2 with "sync the corpus first". Check `VerifyOptions`' constructor fields in `verify.py` and use them.

- [ ] **Step 2: Run to verify they fail**

Run: `PYTHONPATH=$PWD/src/packages/api:$PWD/src/packages/api/tests python3 -m pytest src/packages/api/tests/test_contrib_duplicates.py -q`
Expected: FAIL — `ImportError: cannot import name 'MissingPublished'`

- [ ] **Step 3: Implement**

In `checks.py`:

```python
class MissingPublished(Exception):
    def __init__(self, material: str):
        super().__init__(material)
        self.material = material


def check_identical(payload: str | None, published: str) -> Check:
    title = "identical to the published table"
    if payload is None:
        return Check("V8", title, "fail", "payload unknown (V4 did not decode)")
    if payload != published:
        return Check("V8", title, "fail", "content differs from the published table")
    return Check("V8", title, "pass", f"identical to the published table (payload {payload[:12]}…)")
```

In `verify.py`:

```python
class PublishedHashes:
    """Payload hashes of published tables, from the local corpus copy, cached per manifest sha."""

    def __init__(self, tables: Path, manifest_files: dict):
        self.tables, self.files = Path(tables), manifest_files
        self.path = self.tables / ".payload-sha256.json"
        try:
            self.cache: dict = json.loads(self.path.read_text())
        except (OSError, ValueError):
            self.cache = {}

    def get(self, material: str) -> str:
        from .checks import MissingPublished
        from .tablefile import payload_sha256
        sha = self.files.get(f"{material}.hm", {}).get("sha256")
        hit = self.cache.get(material)
        if hit and hit.get("hm_sha256") == sha:
            return hit["payload"]
        hm = self.tables / f"{material}.hm"
        if not hm.exists():
            raise MissingPublished(material)
        payload = payload_sha256(hm)
        self.cache[material] = {"hm_sha256": sha, "payload": payload}
        self.path.write_text(json.dumps(self.cache, indent=1, sort_keys=True))
        return payload
```

Change `check_pr_hygiene` to collect `dups = {f[:-3] for f in pr.files if f.endswith(".hm") and f in manifest_files}`, drop the "already published" problem for `.hm` files of `dups` and their sidecars, and append `f"; duplicates of published tables: {', '.join(sorted(dups))}"` to the pass/warn detail when `dups`; return `(check, dups)`. In `verify_table`, after V4 (and only when `published is not None`):

```python
    if published is not None:
        rep.checks.append(check_identical(rep.payload_sha256, published))
        why = ("confirmed: identical to the published table" if rep.passed
               else "an earlier check failed")
        for cid, title in (("V5", "deepest positions probe as recorded"),
                           ("V6", "local consistency"), ("V7", "independent solver")):
            rep.checks.append(Check(cid, title, "skip", why))
        return rep
```

(insert it right after the V4 append; V5 `check_deepest` must not run for duplicates). In `verify_prs`: `v1, dups = check_pr_hygiene(pr, manifest_files)`; create `hashes = PublishedHashes(tables, manifest_files)` once before the loop; build reports with `published=hashes.get(m) if m in dups else None`; catch `MissingPublished` next to `MissingSubtable` and raise `UsageError(f"{exc.material} is published but not in {tables}; sync the corpus first")`. Update `test_v1_hygiene` for the tuple return and for the published-file case (now `dups == {"KRRvkqq"}`, status not fail).

- [ ] **Step 4: Run to verify they pass**

Run: `PYTHONPATH=$PWD/src/packages/api:$PWD/src/packages/api/tests python3 -m pytest src/packages/api/tests/test_contrib_duplicates.py src/packages/api/tests/test_contrib_verify_pr.py src/packages/api/tests/test_contrib_payload.py -q`
Expected: all pass

- [ ] **Step 5: Lint, type-check, commit**

```bash
ruff check src/packages/api && mypy src/packages/api/helpmate_server/contrib
git add -A src/packages/api && git commit -m "verify: a table identical to a published one is a confirmation (V8), not a V1 failure" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Per-file staging

**Files:**
- Modify: `src/packages/api/helpmate_server/contrib/verify.py` (`_staged_ok`, `_stage`, the plan in `verify_prs`, `_verified_files`)
- Modify: `src/packages/api/helpmate_server/contrib/accept.py` (`_missing_staged` unchanged in behaviour — keep; nothing else)
- Modify: `src/packages/api/tests/fakes.py` (FakeHub: expose `_tree(revision)` returning `{path: (size, sha256)}` for a PR head or main, if not present)
- Test: `src/packages/api/tests/test_contrib_staging.py` (new)

**Interfaces:**
- Consumes: `Hub._tree(revision) -> {path: (size, sha)}` (real hub, `hf.py`).
- Produces:
  - `staging/pr-N/files/.files.json`: `{"head": <sha>, "files": {name: {"sha256": str, "size": int}}}`.
  - `_staged_ok(files_dir: Path, name: str, want: tuple[int, str]) -> bool` — file exists, size equals `want[0]`, and `.files.json` records `want[1]` for it.
  - `_stage(hub, pr, files_dir) -> list[str]` — returns the names actually downloaded. Keeps unchanged files across heads, re-downloads changed or partial ones, deletes files no longer in the PR (except `.files.json`), writes `.files.json` (head + per-file sha/size) after each file so an interrupted run resumes. A legacy `.head` marker without `.files.json`: hash each existing file once (sha256 of bytes), record it, then compare with the head's sha; delete `.head`.
  - `_is_staged_for(files_dir, head) -> bool` — `.files.json` head equals `head` (used by `_verified_files` in place of the `.head` comparison).

- [ ] **Step 1: Write the failing tests**

```python
# src/packages/api/tests/test_contrib_staging.py
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
```

For these tests, `FakeHub` must answer `_tree(head)` with `{path: (len(bytes), sha256(bytes))}` for the PR's files at that head, and `download(f, revision, dest)` must write the bytes of that revision (check how `FakeHub.download` and `add_pr` store files; a re-`add_pr` with a new head replaces the PR's files — extend the fake minimally if it does not). Keep existing verify tests green (`test_verify_pr_rerun_skips_downloaded_files` etc.).

- [ ] **Step 2: Run to verify they fail**

Run: `PYTHONPATH=$PWD/src/packages/api:$PWD/src/packages/api/tests python3 -m pytest src/packages/api/tests/test_contrib_staging.py -q`
Expected: FAIL — `ImportError: cannot import name '_is_staged_for'`

- [ ] **Step 3: Implement**

```python
def _files_record(files_dir: Path) -> dict:
    try:
        return json.loads((files_dir / ".files.json").read_text())
    except (OSError, ValueError):
        return {"head": None, "files": {}}


def _is_staged_for(files_dir: Path, head: str | None) -> bool:
    return head is not None and _files_record(files_dir).get("head") == head


def _staged_ok(files_dir: Path, name: str, want: tuple[int, str]) -> bool:
    p = files_dir / name
    rec = _files_record(files_dir)["files"].get(name)
    return p.exists() and p.stat().st_size == want[0] and rec is not None and rec.get("sha256") == want[1]


def _sha256_file(p: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 24), b""):
            h.update(chunk)
    return h.hexdigest()


def _stage(hub, pr, files_dir: Path) -> list[str]:
    """Download what is missing or changed at the PR's head; keep unchanged files."""
    files_dir.mkdir(parents=True, exist_ok=True)
    revision = pr.head or f"refs/pr/{pr.num}"
    tree = hub._tree(revision)
    want = {f: tree[f] for f in pr.files}
    rec = _files_record(files_dir)
    legacy = files_dir / ".head"
    if legacy.exists() and not (files_dir / ".files.json").exists():
        rec = {"head": None, "files": {f.name: {"sha256": _sha256_file(f), "size": f.stat().st_size}
                                       for f in files_dir.iterdir()
                                       if f.is_file() and not f.name.startswith(".")}}
        legacy.unlink()
    for f in files_dir.iterdir():
        if f.is_file() and not f.name.startswith(".") and f.name not in want:
            f.unlink()
            rec["files"].pop(f.name, None)
    rec["head"] = pr.head

    def save() -> None:
        (files_dir / ".files.json").write_text(json.dumps(rec, indent=1, sort_keys=True))

    save()
    fetched = []
    for name, (size, sha) in sorted(want.items()):
        p = files_dir / name
        known = rec["files"].get(name, {})
        if p.exists() and p.stat().st_size == size and known.get("sha256") == sha:
            continue
        p.unlink(missing_ok=True)
        hub.download(name, revision, files_dir)
        rec["files"][name] = {"sha256": sha, "size": size}
        save()
        fetched.append(name)
    return fetched
```

In `verify_prs`, build the download plan from `tree = hub._tree(pr.head or f"refs/pr/{num}")` and `_staged_ok(have, f, tree[f])` (sizes from the tree; drop the separate `file_sizes` call). Replace the `.head` comparison in `_verified_files` with `_is_staged_for(d / "files", head)`. Remove `marker`/`.head` writing.

- [ ] **Step 4: Run to verify they pass**

Run: `PYTHONPATH=$PWD/src/packages/api:$PWD/src/packages/api/tests python3 -m pytest src/packages/api/tests/test_contrib_staging.py src/packages/api/tests/test_contrib_verify_pr.py src/packages/api/tests/test_contrib_accept.py -q`
Expected: all pass

- [ ] **Step 5: Lint, type-check, commit**

```bash
ruff check src/packages/api && mypy src/packages/api/helpmate_server/contrib
git add -A src/packages/api && git commit -m "verify: staging keeps unchanged files across PR revisions" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Delta verify and progress lines

**Files:**
- Modify: `src/packages/api/helpmate_server/contrib/report.py` (`report_json` table entries carry `hm_sha256`, `stats_sha256`, `payload_sha256`, `seed`; checks carry optional `reused_from`; markdown marks reused results)
- Modify: `src/packages/api/helpmate_server/contrib/verify.py` (reuse logic, `report.prev.json`, progress output)
- Modify: `src/packages/api/helpmate_server/contrib/checks.py` (`Check` gets `reused_from: str | None = None`)
- Modify: `src/packages/api/helpmate_server/contrib/cli.py` (`verify --full`)
- Test: `src/packages/api/tests/test_contrib_delta.py` (new)

**Interfaces:**
- Consumes: `.files.json` shas (Task 3), `TableReport.payload_sha256` (Task 1).
- Produces:
  - `reusable(prev: dict | None, material: str, shas: tuple[str, str], tool: str, settings: dict) -> dict | None` — the previous table entry if it may be reused: `prev` exists, `prev["tool"] == tool`, `prev[k] == settings[k]` for `samples`, `oracle_samples`, `oracle_plies`, the table entry exists with `passed` true and `(hm_sha256, stats_sha256) == shas`; else None.
  - `TableReport.from_json(material, entry, reused_from: str) -> TableReport` — rebuilds checks with `reused_from` set (and copies `payload_sha256`).
  - Report table entry keys: `passed`, `checks`, `hm_sha256`, `stats_sha256`, `payload_sha256`, `seed`.
  - Progress: `verify_table(..., progress: Callable[[str], None] | None = None)`; `verify_prs` passes a printer producing lines `[i/n] <material> <check id> <title> … <status> (<elapsed>)`, `[i/n] <material> reused from <head7>`, flushed immediately.
  - CLI: `verify --pr N --full` disables reuse.

- [ ] **Step 1: Write the failing tests**

```python
# src/packages/api/tests/test_contrib_delta.py
from helpmate_server.contrib.verify import reusable

SETTINGS = {"samples": 2000, "oracle_samples": 20, "oracle_plies": 3, "date": "2026-10-09"}
PREV = {"tool": "helpmate-tables 0.21.0", "head": "h1", "samples": 2000, "oracle_samples": 20,
        "oracle_plies": 3, "date": "2026-10-01",
        "tables": {"KQvk": {"passed": True, "checks": [], "hm_sha256": "a", "stats_sha256": "b",
                            "payload_sha256": "p", "seed": 7},
                   "KRvk": {"passed": False, "checks": [], "hm_sha256": "c", "stats_sha256": "d",
                            "payload_sha256": "q", "seed": 7}}}


def test_reuse_when_everything_matches_even_on_another_date():
    assert reusable(PREV, "KQvk", ("a", "b"), "helpmate-tables 0.21.0", SETTINGS) is PREV["tables"]["KQvk"]


def test_no_reuse_when_the_sidecar_changed():
    assert reusable(PREV, "KQvk", ("a", "X"), "helpmate-tables 0.21.0", SETTINGS) is None


def test_no_reuse_for_failed_tables_other_tools_settings_or_no_report():
    assert reusable(PREV, "KRvk", ("c", "d"), "helpmate-tables 0.21.0", SETTINGS) is None
    assert reusable(PREV, "KQvk", ("a", "b"), "helpmate-tables 0.22.0", SETTINGS) is None
    assert reusable(PREV, "KQvk", ("a", "b"), "helpmate-tables 0.21.0", dict(SETTINGS, samples=10)) is None
    assert reusable(None, "KQvk", ("a", "b"), "helpmate-tables 0.21.0", SETTINGS) is None
```

Plus integration tests (same file) with the `compressed_tables` fixture and `FakeHub`, modelled on `test_contrib_verify_pr.py::test_verify_pr_passes_and_posts`:
1. verify PR #2 (KQvk) → pass; push a new head where only an unrelated file changed is impossible with one table, so: PR with KQvk and KRvk (or any two fixture materials); run verify; re-`add_pr` with a new head where only KRvk's sidecar bytes changed (e.g. reformatted JSON with same content — must still pass V2's sidecar==metadata check, so instead change KRvk.hm to a copy of the same file and its sidecar unchanged but give the fake a different sha for KRvk.hm); run verify again → report head is the new head, KQvk checks all carry `reused_from == "h1"`, KRvk fresh; stdout contains `KQvk reused from h1`.
2. Same with `--full` (namespace attribute `full=True`) → nothing reused.
3. `report.prev.json` exists after the second run and holds the first report.
4. Progress: stdout of a fresh run contains a line matching `\[1/\d+\] KQvk V2 .* pass \(`.

(Look at how existing tests build the `argparse.Namespace` for `verify_prs` and add `full=False` there; add `full` to the CLI parser.)

- [ ] **Step 2: Run to verify they fail**

Run: `PYTHONPATH=$PWD/src/packages/api:$PWD/src/packages/api/tests python3 -m pytest src/packages/api/tests/test_contrib_delta.py -q`
Expected: FAIL — `ImportError: cannot import name 'reusable'`

- [ ] **Step 3: Implement**

```python
REUSE_SETTINGS = ("samples", "oracle_samples", "oracle_plies")


def reusable(prev: dict | None, material: str, shas: tuple[str, str], tool: str,
             settings: dict) -> dict | None:
    if not prev or prev.get("tool") != tool:
        return None
    if any(prev.get(k) != settings.get(k) for k in REUSE_SETTINGS):
        return None
    entry = prev.get("tables", {}).get(material)
    if not entry or not entry.get("passed"):
        return None
    if (entry.get("hm_sha256"), entry.get("stats_sha256")) != shas:
        return None
    return entry
```

In `verify_prs`, per PR: load `prev = json.loads((d/"report.json").read_text())` if it exists and `not a.full`; move the old file to `report.prev.json` before writing the new report. After `_stage`, read `.files.json` for the shas; for each material: if `reusable(...)` returns an entry, build `TableReport.from_json(m, entry, reused_from=prev["head"])` and print `[i/n] m reused from <head7>`; otherwise verify fresh with a `progress` printer. `report_json` writes, per table, `hm_sha256`/`stats_sha256` from `.files.json`, `payload_sha256` from the report, and `seed` (the reused entry's seed for reused tables, the run's seed otherwise). In `render_markdown`, a check with `reused_from` gets ` (reused from <head7>)` appended to its detail. In `verify_table`, call `progress(line)` after each check with the elapsed seconds of that check (`time.monotonic()` around each check call); keep the function's results unchanged when `progress` is None.

- [ ] **Step 4: Run to verify they pass**

Run: `PYTHONPATH=$PWD/src/packages/api:$PWD/src/packages/api/tests python3 -m pytest src/packages/api/tests/test_contrib_delta.py src/packages/api/tests/test_contrib_verify_pr.py src/packages/api/tests/test_contrib_duplicates.py src/packages/api/tests/test_contrib_accept.py -q`
Expected: all pass

- [ ] **Step 5: Lint, type-check, commit**

```bash
ruff check src/packages/api && mypy src/packages/api/helpmate_server/contrib
git add -A src/packages/api && git commit -m "verify: reuse results of unchanged tables (delta verify), --full, progress lines" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Duplicates in accept and the registry

**Files:**
- Modify: `src/packages/api/helpmate_server/contrib/registry.py` (`record_confirmation`, `confirmations_of`)
- Modify: `src/packages/api/helpmate_server/contrib/accept.py` (preflight, merge, local step, docs lines, claims comments)
- Test: `src/packages/api/tests/test_contrib_accept_duplicates.py` (new); `test_contrib_registry.py` (extend if it exists, else in the new file)

**Interfaces:**
- Consumes: report entries with `payload_sha256` (Tasks 1, 4); `PublishedHashes` (Task 2).
- Produces:
  - `Registry.record_confirmation(material, *, contributor: str, hf_pr: int, merged: str, generator_version: str) -> None` — appends `{"contributor", "hf_pr", "date", "generator_version"}` to `tables[material]["confirmed_by"]` (created if absent; no duplicate entry for the same contributor + hf_pr).
  - `Registry.confirmations_of(key) -> list[str]` — sorted materials where `key` appears in `confirmed_by`.
  - Accept behaviour:
    - Preflight: `already = [m for m in pr.materials if f"{m}.hm" in published]` is no longer an error. For each such m: `rep["tables"][m]["payload_sha256"]` must equal `PublishedHashes(tables, published).get(m)`, else `_err(f"PR #{n}: {m} differs from the published table; it cannot be a confirmation")`. Store `stored[str(n)]["duplicates"] = sorted(already)`.
    - Two PRs in one run sharing a material: keep the existing error and append `"; accept them in separate runs: the second becomes a confirmation"`.
    - Merge: a PR with duplicates is merged with `hub.merge_by_copy(n, verified, new_files, message=..., comment=...)` where `new_files` are the PR's files minus each duplicate's `.hm` and `.stats.json`; if `new_files` is empty, nothing is copied and the PR is closed with `hub.close_pr(n, comment)` where the comment thanks the contributor and lists the confirmed materials. The comment for a mixed PR lists merged tables and confirmations. Record progress in `copied` as today.
    - Local step: duplicate files are not moved into `--tables`.
    - Registry: after the merge, for each duplicate call `record_confirmation(m, contributor=p["key"], hf_pr=n, merged=today, generator_version=<sidecar's generator_version from staging>)`; new tables are recorded as today.
    - Docs lines: `- KQvkqqq, … contributed by X (dataset PR #n …).` for new tables; additionally `- KQvkqqq, … independently confirmed by X (dataset PR #n).` for duplicates. The docs step's material page build includes only new materials.
    - Claims step: unchanged except a confirmer's claim comment also lists the confirmed materials ("confirmed: …").

- [ ] **Step 1: Write the failing tests**

Base the accept tests on the helpers in `src/packages/api/tests/test_contrib_accept.py` (`_setup`, `_run`, `FakeGit`, `PageBuilder`). Write in `test_contrib_accept_duplicates.py`:

```python
import json

from fakes import FakeHub
from helpmate_server.contrib.registry import Registry
from test_contrib_accept import FakeGit, _run, _setup


def _publish(hub, tables, material, payload_bytes=b"table"):
    """Make `material` published on main and present locally (the first accepted copy)."""
    hub.main[f"{material}.hm"] = payload_bytes
    hub.main[f"{material}.stats.json"] = b'{"generator_version": "0.19.0", "material": "%s", "plane_size": 1, "max_dtm": 9}' % material.encode()
    (tables / f"{material}.hm").write_bytes(payload_bytes)
    (tables / f"{material}.stats.json").write_bytes(hub.main[f"{material}.stats.json"])


def test_registry_confirmations():
    reg = Registry(None, {"contributors": {}, "tables": {"KQvkqqq": {"contributor": "popeye37"}}})
    reg.record_confirmation("KQvkqqq", contributor="T31M", hf_pr=22, merged="2026-10-10", generator_version="0.20.0")
    reg.record_confirmation("KQvkqqq", contributor="T31M", hf_pr=22, merged="2026-10-10", generator_version="0.20.0")
    assert reg.tables["KQvkqqq"]["confirmed_by"] == [
        {"contributor": "T31M", "hf_pr": 22, "date": "2026-10-10", "generator_version": "0.20.0"}]
    assert reg.confirmations_of("T31M") == ["KQvkqqq"]
```

and accept scenarios (each builds on `_setup(tmp_path)`, which stages PR #2 with `KRRvkqq`):
1. **duplicate-only PR**: publish `KRRvkqq` locally and on main before the run; make the report's `tables.KRRvkqq.payload_sha256` equal the published hash (monkeypatch `helpmate_server.contrib.verify.PublishedHashes.get` to return the report's value). Run → rc 0; `hub.copies == []` and `hub.merged == []`; PR #2 closed with a comment containing "confirm"; registry `confirmed_by` has the contributor; CHANGELOG line contains "independently confirmed by"; `tables/KRRvkqq.hm` still holds the published bytes.
2. **mixed PR**: add a second material to PR #2 (stage its files and add them to the report) where only `KRRvkqq` is published → `hub.copies[0]["files"]` lists only the new material's two files; registry records the new table and the confirmation.
3. **mismatch**: published hash differs → rc 2, error contains "differs from the published table", nothing merged.
4. **two PRs in one run with the same unpublished material** → rc 2 and the message contains "accept them in separate runs".

Read `test_contrib_accept.py` for how `_setup` writes `report.json` (add `payload_sha256` to its table entry in your scenarios) and how `FakeHub.merge_by_copy` / `close_pr` record calls (`hub.copies`, `hub.closed`).

- [ ] **Step 2: Run to verify they fail**

Run: `PYTHONPATH=$PWD/src/packages/api:$PWD/src/packages/api/tests python3 -m pytest src/packages/api/tests/test_contrib_accept_duplicates.py -q`
Expected: FAIL — `AttributeError: 'Registry' object has no attribute 'record_confirmation'`

- [ ] **Step 3: Implement** the registry methods:

```python
    def record_confirmation(self, material: str, *, contributor: str, hf_pr: int, merged: str,
                            generator_version: str) -> None:
        entry = {"contributor": contributor, "hf_pr": hf_pr, "date": merged,
                 "generator_version": generator_version}
        conf = self.tables.setdefault(material, {}).setdefault("confirmed_by", [])
        if not any(c["contributor"] == contributor and c["hf_pr"] == hf_pr for c in conf):
            conf.append(entry)

    def confirmations_of(self, key: str) -> list[str]:
        return sorted(m for m, t in self.tables.items()
                      if any(c.get("contributor") == key for c in t.get("confirmed_by", [])))
```

Then the accept changes listed under Interfaces, in this order: preflight (replace the `already … in the dataset` error), the shared-material error text, the merge branch (`duplicates` non-empty → `merge_by_copy` with `new_files`, or `close_pr` when empty; no `hub.merge(n)` for such PRs), the local step filter, the registry step (where `record_table` is called today), the docs lines, the page-build material list, the claims comment. `Registry(None, data)` must work for the unit test (path unused until `save`).

- [ ] **Step 4: Run to verify they pass**

Run: `PYTHONPATH=$PWD/src/packages/api:$PWD/src/packages/api/tests python3 -m pytest src/packages/api/tests/test_contrib_accept_duplicates.py src/packages/api/tests/test_contrib_accept.py -q`
Expected: all pass

- [ ] **Step 5: Lint, type-check, commit**

```bash
ruff check src/packages/api && mypy src/packages/api/helpmate_server/contrib
git add -A src/packages/api && git commit -m "accept: identical duplicates become confirmations; only new files are merged" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Credits for confirmations everywhere

**Files:**
- Modify: `src/packages/api/helpmate_server/contrib/site_status.py` (per-material `confirmed_by`, per-contributor `confirmations`)
- Modify: `src/packages/api/helpmate_server/contrib/docs_sync.py` (`render_contributors` column; `all_contributors_rc` includes confirmers)
- Modify: `src/packages/api/helpmate_server/contrib/corpus_stats.py` (`materials_rows` + Parquet schema: `confirmed_by` string)
- Modify: `site/js/lib/materials.js` (`validStatus` accepts optional `confirmed_by`/`confirmations`; `mergeStatus` carries `confirmed_by`; filter matches author or confirmer; `contributorCards` shows confirmations)
- Modify: `site/js/materials.js` (contributor cell: `popeye37 · confirmed by T31M`)
- Test: `src/packages/api/tests/test_contrib_site_status.py`, `test_contrib_docs_sync.py`, `test_contrib_corpus_stats.py` (extend), `site/tests/materials.test.js` (extend)

**Interfaces:**
- Consumes: `Registry.confirmations_of`, `tables[m]["confirmed_by"]` (Task 5).
- Produces:
  - status.json: done entries `{"state": "done", "contributor": <author display>, "confirmed_by": [<display>, …], …}` (empty list when none); contributor entries gain `"confirmations": <int>`; a contributor with only confirmations is listed (tables 0).
  - Display names follow the existing rule (`_registered`: "anonymous" for anonymous contributors).
  - Credit table (docs_sync): columns `| contributor | tables | confirmations | notes |`.
  - Parquet `materials.parquet`: column `confirmed_by` (`pa.string()`), comma-separated display names, `""` when none, appended after `contributor`.
  - Site: cell text `"<author> · confirmed by <a>, <b>"`; contributor filter keeps a row if `r.contributor === f.contributor` or `r.confirmed_by.includes(f.contributor)`; card line `"N tables · M independent confirmations"` (omit the confirmations part when 0; "N tables" omitted when 0 and M > 0).

- [ ] **Step 1: Write the failing tests** — one per bullet above, in the listed test files, following each file's existing style. Concretely:
  - `test_contrib_site_status.py`: registry with `KQvkqqq` by popeye37 confirmed by T31M (both registered, T31M with no own tables) → status entry `confirmed_by == ["T31M"]`, contributors list contains T31M with `tables == 0` and `confirmations == 1`.
  - `test_contrib_docs_sync.py`: `render_contributors` output contains a header row with `confirmations` and a T31M row with `0 | 1`.
  - `test_contrib_corpus_stats.py`: `materials_rows` gives `confirmed_by == "T31M"` for that table and `""` otherwise; Parquet schema field `confirmed_by` is `string`.
  - `site/tests/materials.test.js`: `mergeStatus` keeps `confirmed_by`; `filterRows` with `contributor=T31M` keeps the confirmed row; `contributorCards` renders "1 independent confirmation"/"N independent confirmations"; `validStatus` accepts entries without `confirmed_by` (old status.json) and with it.
  - Update `tests/repo/test_site_stats_fresh.py` only if it reads contributors (it should not).

- [ ] **Step 2: Run to verify they fail**

Run: `PYTHONPATH=$PWD/src/packages/api:$PWD/src/packages/api/tests python3 -m pytest src/packages/api/tests/test_contrib_site_status.py src/packages/api/tests/test_contrib_docs_sync.py src/packages/api/tests/test_contrib_corpus_stats.py -q; node --test site/tests/materials.test.js`
Expected: the new tests FAIL

- [ ] **Step 3: Implement** per the Interfaces block. Keep old status.json readable by the site (fields optional). The Parquet schema change must keep `test_parquet_round_trip_with_fixed_schema` updated with the new column.

- [ ] **Step 4: Run to verify they pass**

Run: same commands as Step 2, plus `make test-site`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
ruff check src/packages/api && mypy src/packages/api/helpmate_server/contrib
git add -A src/packages/api site && git commit -m "credits: confirmations named with the author on the site, in the docs and in the statistics" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: `accept --no-pages` and `helpmate-tables pages`

**Files:**
- Modify: `src/packages/api/helpmate_server/contrib/accept.py` (`no_pages` parameter)
- Create: `src/packages/api/helpmate_server/contrib/pages.py`
- Modify: `src/packages/api/helpmate_server/contrib/cli.py` (`accept --no-pages`; new `pages` parser and dispatch; add `"pages"` to `CONTRIB_COMMANDS`)
- Test: `src/packages/api/tests/test_contrib_pages.py` (new); extend `test_contrib_accept.py`

**Interfaces:**
- Consumes: `accept.Git` (`commit_all`, `push`, `open_pr`, `wait_and_merge`, `back`, `reset_to_origin_main`, `clean`), `site_data.write_site_data`, the checkout's `tools/build_problems.py` (`main(argv)`, `merge_index`, `merge_themes`).
- Produces:
  - `accept(..., no_pages: bool = False)` — skips `build_material_pages` and its post-check; docs lines unchanged.
  - `pages.missing_pages(checkout: Path) -> list[str]` — done materials in `site/data/materials.json` without `site/data/material/<M>.json`, sorted.
  - `pages.split_jobs(materials: list[str], jobs: int) -> list[list[str]]` — round-robin, no empty lists.
  - `pages.run_pages(materials, *, checkout, tables, binary, jobs, staging, git, today, allow_failures=False, runner=subprocess.Popen) -> int`:
    1. state file `staging/pages-<today>.json` (`{"done_jobs": [...], "materials": [...], "pr": url?}`); resume skips finished jobs;
    2. each job: `job_dir = staging/pages-<today>/job-<i>`; copy `site/data/materials.json` there; run `python tools/build_problems.py --tables T --binary B --out job_dir --material ...` (cwd checkout), up to `jobs` processes at once; wait;
    3. after all jobs: move `job_dir/material/*.json` into `site/data/material/`; fold each job's `index.json`/`themes.json` into the real files with `merge_index(existing, job_rows, processed=set(job materials))` / `merge_themes(...)` (load the module with `importlib.util.spec_from_file_location` from `checkout/tools/build_problems.py`);
    4. failed materials (a job exiting non-zero, or a material without its page file) → listed; return 1 before the PR unless `allow_failures`;
    5. `write_site_data(checkout/"site"/"data", tables)`; branch `data/pages-<today>`; `git.commit_all("Site: material pages for N material(s)\n\n" + list)`; push; open PR; `wait_and_merge`; `back`; remove the state file.
  - CLI: `helpmate-tables pages --tables DIR (--missing | --material M [M ...]) [--jobs N] [--binary PATH] [--checkout PATH] [--staging DIR] [--allow-failures]`.

- [ ] **Step 1: Write the failing tests**

```python
# src/packages/api/tests/test_contrib_pages.py
import json

from helpmate_server.contrib.pages import missing_pages, split_jobs


def test_missing_pages_lists_done_materials_without_a_page(tmp_path):
    data = tmp_path / "site" / "data"
    (data / "material").mkdir(parents=True)
    (data / "materials.json").write_text(json.dumps([
        {"material": "KQvk", "done": True}, {"material": "KRvk", "done": True},
        {"material": "KBvk", "done": False}]))
    (data / "material" / "KQvk.json").write_text("{}")
    assert missing_pages(tmp_path) == ["KRvk"]


def test_split_jobs_round_robin_without_empty_jobs():
    assert split_jobs(["a", "b", "c", "d", "e"], 2) == [["a", "c", "e"], ["b", "d"]]
    assert split_jobs(["a"], 4) == [["a"]]
```

Plus with fakes (follow `test_contrib_accept.py`'s `FakeGit` and `PageBuilder`, but a fake runner that, per job, writes `job_dir/material/<M>.json`, `job_dir/index.json` (one row per material) and `job_dir/themes.json`):
1. `run_pages(["A","B","C"], jobs=2, ...)` → all three page files in `site/data/material/`, `index.json` contains A, B, C plus pre-existing rows, a docs PR opened and merged (`FakeGit.calls`), state file removed.
2. Resume: first run with the fake `git.wait_and_merge` raising → rerun does not re-run finished jobs (runner call count unchanged) and completes.
3. A job failing for material B → rc 1, no PR, pages of A and C kept; with `allow_failures=True` → PR opened, its message lists B as failed.
4. `accept(..., no_pages=True)`: the `PageBuilder` is never called and the run succeeds (extend `test_contrib_accept.py`).
5. CLI parses `pages --tables X --missing --jobs 3`.

- [ ] **Step 2: Run to verify they fail**

Run: `PYTHONPATH=$PWD/src/packages/api:$PWD/src/packages/api/tests python3 -m pytest src/packages/api/tests/test_contrib_pages.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'helpmate_server.contrib.pages'`

- [ ] **Step 3: Implement** `pages.py` per the Interfaces block:

```python
"""helpmate-tables pages: material pages for done materials, built in parallel jobs that each
write their own directory, then folded into site/data sequentially and shipped as a docs PR."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


def missing_pages(checkout: Path) -> list[str]:
    data = Path(checkout) / "site" / "data"
    rows = json.loads((data / "materials.json").read_text())
    return sorted(r["material"] for r in rows
                  if r.get("done") and not (data / "material" / f"{r['material']}.json").exists())


def split_jobs(materials: list[str], jobs: int) -> list[list[str]]:
    jobs = max(1, jobs)
    out = [materials[i::jobs] for i in range(jobs)]
    return [j for j in out if j]
```

`run_pages` follows steps 1–5 above; use `runner([...], cwd=checkout)` returning a process with `.wait()` (default `subprocess.Popen`), start at most `jobs` at once (all jobs are created up front, so with `split_jobs(..., jobs)` that is all of them). In `accept.py` add the `no_pages` keyword and guard the `build_material_pages(...)` call with `if not no_pages:`. Wire the CLI (`pages` needs `--binary` resolved like accept's `_absolute_binary`, and a `Git(checkout)` instance).

- [ ] **Step 4: Run to verify they pass**

Run: `PYTHONPATH=$PWD/src/packages/api:$PWD/src/packages/api/tests python3 -m pytest src/packages/api/tests/test_contrib_pages.py src/packages/api/tests/test_contrib_accept.py -q`
Expected: all pass

- [ ] **Step 5: Lint, type-check, commit**

```bash
ruff check src/packages/api && mypy src/packages/api/helpmate_server/contrib
git add -A src/packages/api && git commit -m "pages: build missing material pages in parallel jobs; accept --no-pages" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Docs, changelog, full verification

**Files:**
- Modify: `CHANGELOG.md` (Unreleased: delta verify, per-file staging, progress lines, confirmations with V8 and credits, `accept --no-pages`, `pages`)
- Modify: `docs/CONTRIBUTING-TABLES.md` (maintainer section: confirmations, V8, `--full`, `accept --no-pages`, `pages --missing --jobs N`; contributor-facing note that identical re-deliveries are credited as independent confirmations)
- Modify: `docs/ROADMAP.md` (mark delta verify, progress lines, and "second-builder confirmation" as done in the 2026-10-03 ideas list)

- [ ] **Step 1: Write the docs** (plain English, each file's style).
- [ ] **Step 2: Full verification**

```bash
PYTHONPATH=$PWD/src/packages/api:$PWD/src/packages/api/tests python3 -m pytest src/packages/api/tests tests/repo -q --deselect tests/repo/test_deepest_render.py::test_booklet_compiles
ruff check src/packages/api tools
mypy src/packages/api/helpmate_server/contrib
make test-site
PYTHONPATH=$PWD/src/packages/api:$PWD/src/packages/api/tests python3 -m pytest src/packages/api/tests -q --cov=helpmate_server.contrib.verify --cov=helpmate_server.contrib.pages --cov=helpmate_server.contrib.accept --cov=helpmate_server.contrib.registry --cov-report=term-missing
```

Expected: all green; each listed module ≥ 80 % line coverage (report the numbers).

- [ ] **Step 3: Read-only CLI smoke** (no Hub writes): `PYTHONPATH=$PWD/src/packages/api python3 -m helpmate_server.tables_cli verify --tables ~/tb --pr 22 --plan-only` prints the download plan with per-file "(already downloaded)" markers (nothing is downloaded with `--plan-only`).

- [ ] **Step 4: Commit**

```bash
git add CHANGELOG.md docs/CONTRIBUTING-TABLES.md docs/ROADMAP.md
git commit -m "docs: batch processing — confirmations, delta verify, deferred pages" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

## After the plan (controller, with the maintainer's go)

Real-data check of the payload-hash claim: download `KQvkqqq.hm` from HF PR #19 (popeye37) and #22 (T31M) into a scratch directory on the HDD (a few GiB each — ask first), run `payload_sha256` on both: they must be equal. Then merge, reinstall the CLI, and start wave 1.
