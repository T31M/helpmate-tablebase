import pytest

from contrib_helpers import flip_frame_byte
from helpmate_server.contrib.tablefile import (
    BlockReader, TableFormatError, check_blocks, read_header, read_meta,
)


def test_header_of_a_generated_table(compressed_tables):
    h = read_header(compressed_tables / "KQvk.hm")
    assert (h.version, h.encoding, h.codec, h.symmetry) == (3, 2, 1, 1)
    assert h.material == "KQvk" and h.plane_size == 29568 and not h.marker
    assert read_header(compressed_tables / "KPvk.hm").symmetry == 0
    meta = read_meta(compressed_tables / "KQvk.hm", h)
    assert meta["material"] == "KQvk"


def test_plane_chunks_cover_each_plane_exactly(compressed_tables):
    with BlockReader(compressed_tables / "KQvk.hm") as r:
        for plane in range(4):
            data = b"".join(r.plane_chunks(plane, chunk=5000))
            assert len(data) == r.header.plane_size
            assert data == r.read(plane * r.header.plane_size, r.header.plane_size)


def test_clean_table_ok_and_marker_skipped(compressed_tables):
    verdict, nb = check_blocks(compressed_tables / "KQvk.hm")
    assert verdict == "OK" and nb == -(-4 * 29568 // 1024)
    markers = [p for p in compressed_tables.glob("*.hm") if read_header(p).marker]
    assert markers, "the KQvk/KPvk closure contains at least one marker (Kvk)"
    assert check_blocks(markers[0])[0].startswith("skip marker")


def test_flipped_frame_byte_is_bad(table_copy):
    flip_frame_byte(table_copy / "KQvk.hm", 7)
    verdict, _ = check_blocks(table_copy / "KQvk.hm")
    assert verdict.startswith("BAD block 7:"), verdict


def test_not_a_table(tmp_path):
    p = tmp_path / "x.hm"
    p.write_bytes(b"nope")
    with pytest.raises(TableFormatError):
        read_header(p)
    assert check_blocks(p)[0] == "BAD not a helpmate table (magic)"
