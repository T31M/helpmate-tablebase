import hashlib
import json

from helpmate_server.contrib.checks import check_sidecar, payload_from_planes
from helpmate_server.contrib.tablefile import marker_payload_sha256, payload_sha256


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
    assert payload_sha256(compressed_tables / "KQvk.hm") != payload_sha256(compressed_tables / "KPvk.hm")


def test_v4_yields_the_same_payload_hash_without_an_extra_read(table_copy):
    path = table_copy / "KQvk.hm"
    check, payload = check_sidecar(path)
    assert check.status == "pass"
    assert payload == payload_sha256(path)


def test_payload_from_planes_is_sha_of_concatenated_digests():
    d = ["a" * 64, "b" * 64, "c" * 64, "d" * 64]
    assert payload_from_planes(d) == hashlib.sha256("".join(d).encode()).hexdigest()


def test_marker_payload_hash_uses_the_sidecar_cells():
    sc = {"cells": {"invalid": {"wtm": 0, "btm": 0}, "unsolvable": {"wtm": 5, "btm": 5}}}
    h = marker_payload_sha256(sc)
    assert h.startswith("marker:") and h == marker_payload_sha256(json.loads(json.dumps(sc)))
