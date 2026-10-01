"""Ways to damage a block-compressed table, for tests that must watch a
check fail. Each rewrites the file in place with a valid container, so only
the check aimed at that damage can notice."""
from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Callable

import zstandard

from helpmate_server.contrib.tablefile import HEADER_LEN, read_header


def _payload(path: Path) -> tuple[bytes, bytes, bytearray]:
    raw = path.read_bytes()
    h = read_header(path)
    head = raw[: HEADER_LEN + h.json_len]
    pos = HEADER_LEN + h.json_len
    (nb,) = struct.unpack_from("<Q", raw, pos)
    offsets = struct.unpack_from(f"<{nb + 1}Q", raw, pos + 8)
    start = pos + 8 + 8 * (nb + 1)
    d = zstandard.ZstdDecompressor()
    out = bytearray()
    for b in range(nb):
        out += d.decompress(raw[start + offsets[b]: start + offsets[b + 1]],
                            max_output_size=h.block_size)
    return head, raw, out


def rewrite_payload(path: Path, mutate: Callable[[bytearray, int], None]) -> None:
    """Decode the whole logical payload, let `mutate(payload, plane_size)` edit
    it, and recompress with a correct index and checksums."""
    h = read_header(path)
    head, _, payload = _payload(path)
    mutate(payload, h.plane_size)
    c = zstandard.ZstdCompressor(level=3, write_checksum=True, write_content_size=True)
    frames = [c.compress(bytes(payload[i:i + h.block_size]))
              for i in range(0, len(payload), h.block_size)]
    offsets, pos = [], 0
    for f in frames:
        offsets.append(pos)
        pos += len(f)
    offsets.append(pos)
    path.write_bytes(head + struct.pack("<Q", len(frames))
                     + struct.pack(f"<{len(offsets)}Q", *offsets) + b"".join(frames))


def flip_frame_byte(path: Path, block: int) -> None:
    """Flip one byte in the middle of a compressed frame (the zstd content
    checksum must catch it)."""
    h = read_header(path)
    raw = bytearray(path.read_bytes())
    pos = HEADER_LEN + h.json_len
    (nb,) = struct.unpack_from("<Q", raw, pos)
    offsets = struct.unpack_from(f"<{nb + 1}Q", raw, pos + 8)
    start = pos + 8 + 8 * (nb + 1)
    mid = start + (offsets[block] + offsets[block + 1]) // 2
    raw[mid] ^= 0xFF
    path.write_bytes(bytes(raw))


def edit_sidecar(path: Path, fn: Callable[[dict], None]) -> None:
    sc = path.with_name(path.name[: -len(".hm")] + ".stats.json")
    data = json.loads(sc.read_text())
    fn(data)
    sc.write_text(json.dumps(data, indent=2))
