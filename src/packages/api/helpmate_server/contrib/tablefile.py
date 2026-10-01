"""Read a .hm file without the C++ reader.

verify has to look inside files the C++ reader would refuse, and report why,
so this parses TableHeader (src/core/format/table_file.h) itself. Read-only.
"""
from __future__ import annotations

import json
import os
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

MAGIC = b"HM8P"
HEADER_LEN = 64
DTM_UNSET, DTM_INVALID, DTM_UNSOLVABLE = 253, 254, 255
COUNT_SAT = 255
MAX_REPORTED = 20  # bad blocks listed before giving up on a table


class TableFormatError(Exception):
    pass


@dataclass(frozen=True)
class Header:
    version: int
    encoding: int
    symmetry: int
    material: str
    plane_size: int
    max_dtm: int
    flags: int
    block_size: int
    codec: int
    json_len: int

    @property
    def marker(self) -> bool:
        return bool(self.flags & 1)


def read_header(path: Path | str) -> Header:
    with open(path, "rb") as fh:
        raw = fh.read(HEADER_LEN)
    if len(raw) < HEADER_LEN or raw[:4] != MAGIC:
        raise TableFormatError("not a helpmate table (magic)")
    version, encoding, symmetry = struct.unpack_from("<IBB", raw, 4)
    material = raw[10:36].split(b"\0", 1)[0].decode("ascii", "replace")
    (plane_size,) = struct.unpack_from("<Q", raw, 36)
    max_dtm, flags, block_size, codec = struct.unpack_from("<BBIB", raw, 44)
    (json_len,) = struct.unpack_from("<I", raw, 60)
    return Header(version, encoding, symmetry, material, plane_size, max_dtm,
                  flags, block_size, codec, json_len)


def read_meta(path: Path | str, header: Header) -> dict:
    with open(path, "rb") as fh:
        fh.seek(HEADER_LEN)
        return json.loads(fh.read(header.json_len))


def _read_index(fh, header: Header) -> tuple[int, tuple[int, ...], int]:
    fh.seek(HEADER_LEN + header.json_len)
    raw = fh.read(8)
    if len(raw) < 8:
        raise TableFormatError("truncated before block index")
    (nb,) = struct.unpack("<Q", raw)
    index = fh.read(8 * (nb + 1))
    if len(index) < 8 * (nb + 1):
        raise TableFormatError("truncated block index")
    offsets = struct.unpack(f"<{nb + 1}Q", index)
    start = fh.tell()
    if start + offsets[-1] > os.fstat(fh.fileno()).st_size:
        raise TableFormatError("block index points past end of file")
    return nb, offsets, start


class BlockReader:
    """Random access to the logical payload (4 planes) of an encoding-2 table.
    Keeps the last four decoded blocks: a lockstep walk over a dtm plane and
    its count plane touches two blocks at a time."""

    def __init__(self, path: Path | str):
        import zstandard

        self.header = h = read_header(path)
        if h.marker or h.encoding != 2 or h.block_size == 0:
            raise TableFormatError("not a block-compressed table")
        self._fh = open(path, "rb")
        try:
            self.nblocks, self._offsets, self._start = _read_index(self._fh, h)
        except Exception:
            self._fh.close()
            raise
        self.logical_size = 4 * h.plane_size
        self._dctx = zstandard.ZstdDecompressor()
        self._cache: dict[int, bytes] = {}

    def __enter__(self) -> "BlockReader":
        return self

    def __exit__(self, *exc) -> None:
        self._fh.close()

    def block_len(self, b: int) -> int:
        return min(self.header.block_size, self.logical_size - b * self.header.block_size)

    def block(self, b: int) -> bytes:
        hit = self._cache.get(b)
        if hit is not None:
            return hit
        self._fh.seek(self._start + self._offsets[b])
        src = self._fh.read(self._offsets[b + 1] - self._offsets[b])
        out = self._dctx.decompress(src, max_output_size=self.header.block_size)
        if len(out) != self.block_len(b):
            raise TableFormatError(
                f"block {b}: decoded {len(out)} bytes, index says {self.block_len(b)}")
        if len(self._cache) >= 4:
            self._cache.pop(next(iter(self._cache)))
        self._cache[b] = out
        return out

    def read(self, offset: int, n: int) -> bytes:
        bs = self.header.block_size
        parts, end = [], offset + n
        while offset < end:
            b = offset // bs
            data = self.block(b)
            lo = offset - b * bs
            hi = min(len(data), end - b * bs)
            parts.append(data[lo:hi])
            offset += hi - lo
        return b"".join(parts)

    def plane_chunks(self, plane: int, chunk: int = 1 << 22) -> Iterator[bytes]:
        ps = self.header.plane_size
        base = plane * ps
        for off in range(0, ps, chunk):
            yield self.read(base + off, min(chunk, ps - off))


def check_blocks(path: Path | str) -> tuple[str, int]:
    """Decode every block; verdict 'OK', 'skip ...' or 'BAD ...'."""
    import zstandard

    try:
        h = read_header(path)
    except TableFormatError as exc:
        return f"BAD {exc}", 0
    if h.marker:
        return f"skip marker (v{h.version})", 0
    if h.encoding != 2 or h.block_size == 0:
        return f"skip raw (v{h.version}, encoding {h.encoding})", 0
    with open(path, "rb") as fh:
        try:
            nb, offsets, start = _read_index(fh, h)
        except TableFormatError as exc:
            return f"BAD {exc}", 0
        total = 4 * h.plane_size
        dctx = zstandard.ZstdDecompressor()
        bad: list[str] = []
        for b in range(nb):
            expect = min(h.block_size, total - b * h.block_size)
            fh.seek(start + offsets[b])
            src = fh.read(offsets[b + 1] - offsets[b])
            try:
                out = dctx.decompress(src, max_output_size=expect)
            except zstandard.ZstdError as exc:
                bad.append(f"block {b}: {exc}")
            else:
                if len(out) != expect:
                    bad.append(f"block {b}: decoded {len(out)} bytes, index says {expect}")
            if len(bad) >= MAX_REPORTED:
                bad.append("...")
                break
    return ("OK" if not bad else "BAD " + "; ".join(bad)), nb
