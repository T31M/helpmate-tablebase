# src/packages/api/helpmate_server/contrib/stats_push.py
"""helpmate-tables stats-push: the corpus statistics on Hugging Face. Uploads the two
Parquet files (and main's dataset card) only when their content changed and the local
corpus is exactly the published one; --check compares the published statistics with
the manifest, for the daily stats-check workflow."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .corpus_stats import (
    MATERIALS_PATH, collect, completeness, histogram_rows, parquet_files, parquet_materials,
    same_content)

if TYPE_CHECKING:
    from .registry import Registry


class StatsError(Exception):
    pass


def read_published(hub, path: str) -> bytes | None:
    try:
        return hub.read_bytes(path)
    except KeyError:
        return None
    except Exception as exc:  # huggingface_hub's EntryNotFoundError, without importing it here
        if type(exc).__name__ in ("EntryNotFoundError", "RemoteEntryNotFoundError"):
            return None
        raise


def _published_tables(hub) -> set[str]:
    return {f[: -len(".hm")] for f in hub.fetch_manifest().get("files", {}) if f.endswith(".hm")}


def check(hub) -> list[str]:
    data = read_published(hub, MATERIALS_PATH)
    if data is None:
        return [f"{MATERIALS_PATH} is not on the dataset yet"]
    published, listed = _published_tables(hub), set(parquet_materials(data))
    problems = []
    if published - listed:
        problems.append("statistics lack " + ", ".join(sorted(published - listed)))
    if listed - published:
        problems.append("statistics list tables not in the dataset: " + ", ".join(sorted(listed - published)))
    return problems


def push(hub, tables: Path, registry: Registry | None, card: bytes | None, dry_run: bool) -> str:
    ts = collect(tables)
    missing, extra = completeness(ts, hub.fetch_manifest())
    if missing or extra:
        raise StatsError("the local corpus is not the published one"
                         + (f"; missing locally: {', '.join(missing)}" if missing else "")
                         + (f"; not published: {', '.join(extra)}" if extra else ""))
    files = parquet_files(ts, registry)
    changed = {p: b for p, b in files.items() if not same_content(read_published(hub, p), b)}
    if not changed:
        return f"statistics unchanged ({len(ts)} tables)"
    if dry_run:
        return (f"would upload {', '.join(sorted(changed))} ({len(ts)} tables; "
                f"{len(ts)} materials rows, {len(histogram_rows(ts))} histogram rows)")
    upload = dict(files)
    if card is not None:
        upload["README.md"] = card
    hub.commit(upload, "Dataset statistics" + (" and card" if card is not None else ""))
    return f"uploaded {', '.join(sorted(upload))} ({len(ts)} tables)"
