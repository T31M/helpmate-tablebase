import shutil

import pytest, helpmate
from pathlib import Path
from fastapi.testclient import TestClient
from helpmate_server.storage import LocalDir, ChainSource
from helpmate_server.app import create_app

@pytest.fixture(scope="session")
def kqvk_dir(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("tables")
    helpmate.generate("KQvk", tables=str(d), threads=2)
    return Path(d)

@pytest.fixture()
def client(kqvk_dir) -> TestClient:
    app = create_app(ChainSource([LocalDir(kqvk_dir)]))
    return TestClient(app)

@pytest.fixture(scope="session")
def kqvk_only_dir(tmp_path_factory, kqvk_dir) -> Path:
    """KQvk.hm (+ sidecar) with NO Kvk.hm alongside it -- a partial table set,
    the routine (on-demand HF chain) shape that I-1 needs: KQvk itself is
    reachable, but a capture into Kvk is not. Copied out of kqvk_dir's full
    closure rather than generated fresh, so this stays cheap."""
    d = tmp_path_factory.mktemp("tables_kqvk_only")
    for ext in (".hm", ".stats.json"):
        (d / f"KQvk{ext}").write_bytes((kqvk_dir / f"KQvk{ext}").read_bytes())
    return Path(d)

@pytest.fixture()
def client_partial(kqvk_only_dir) -> TestClient:
    app = create_app(ChainSource([LocalDir(kqvk_only_dir)]))
    return TestClient(app)

@pytest.fixture()
def client_mining(kqvk_dir) -> TestClient:
    """A server with position search switched on.

    Search is off by default from 0.14.0, so every test that exercises
    /v1/mine needs this rather than `client`. Kept as a separate fixture, not
    a flag on `client`, so the default fixture keeps testing the shipped
    configuration."""
    app = create_app(ChainSource([LocalDir(kqvk_dir)]), enable_mine=True)
    return TestClient(app)


@pytest.fixture(scope="session")
def compressed_tables(tmp_path_factory) -> Path:
    """Block-compressed closure of KQvk and KPvk (KPvk promotes into KQvk,
    KRvk, KBvk, KNvk and captures into Kvk), 1 KiB blocks so even these small
    tables have many blocks. Generated once; tests that damage a table must
    use `table_copy`."""
    d = tmp_path_factory.mktemp("compressed")
    for mat in ("KQvk", "KPvk"):
        helpmate.generate(mat, tables=str(d), threads=2, compress=True, block_size=1)
    return Path(d)


@pytest.fixture()
def table_copy(tmp_path, compressed_tables) -> Path:
    d = tmp_path / "tables"
    shutil.copytree(compressed_tables, d)
    return d
