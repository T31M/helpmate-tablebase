from __future__ import annotations
import argparse, json, sys, tempfile
from pathlib import Path
from .contrib import cli as contrib_cli
from .manifest import build_manifest, verify_file

# Files per commit. The Hub caps repository commits at 128/hour.
_COMMIT_CHUNK = 64

def _default_hub(repo_id: str):
    from .storage import HFHub
    hub = HFHub(repo_id)

    def upload(path: Path, repo: str) -> None:
        from huggingface_hub import HfApi
        HfApi().upload_file(path_or_fileobj=str(path), path_in_repo=path.name,
                            repo_id=repo, repo_type="dataset")
    hub.upload = lambda path, repo=repo_id: upload(path, repo)  # type: ignore[attr-defined]

    def commit_files(paths: list[Path], message: str, create_pr: bool = False,
                     description: str = "", repo: str = repo_id) -> str | None:
        """Upload every path in ONE commit.

        One commit per file is what the obvious implementation does, and it is
        wrong twice over. The Hub rate-limits repository commits (128/hour), so
        pushing a real corpus -- 295 tables plus sidecars, ~590 files -- dies
        partway with a 429 that no amount of retrying fixes. And with
        create_pr=True, upload_file opens a SEPARATE pull request per call, so a
        contributor sending a table and its sidecar would file two half-PRs a
        maintainer has to merge in lockstep.
        """
        from huggingface_hub import CommitOperationAdd, HfApi
        ops = [CommitOperationAdd(path_in_repo=p.name, path_or_fileobj=str(p))
               for p in paths]
        info = HfApi().create_commit(repo_id=repo, repo_type="dataset",
                                     operations=ops, commit_message=message,
                                     commit_description=description or None,
                                     create_pr=create_pr)
        return getattr(info, "pr_url", None) if create_pr else None
    hub.commit_files = commit_files  # type: ignore[attr-defined]
    hub.open_pr = (lambda paths, message, description="":  # type: ignore[attr-defined]
                   commit_files(paths, message, create_pr=True, description=description))

    real_fetch_manifest = hub.fetch_manifest

    def fetch_manifest():
        from huggingface_hub.utils import EntryNotFoundError, RepositoryNotFoundError
        try:
            return real_fetch_manifest()
        except (EntryNotFoundError, RepositoryNotFoundError):
            # No manifest.json yet (or the dataset repo itself doesn't exist
            # yet): treat as "remote has no manifest", not an error.
            return None
    hub.fetch_manifest = fetch_manifest  # type: ignore[method-assign]
    return hub

def main(argv: list[str] | None = None, hub_factory=_default_hub, gh_factory=None) -> int:
    p = argparse.ArgumentParser("helpmate-tables")
    sub = p.add_subparsers(dest="cmd")
    for name in ("push", "pull"):
        s = sub.add_parser(name)
        s.add_argument("--tables", required=True, metavar="DIR")
        s.add_argument("--repo", required=True, metavar="USER/DATASET")
        s.add_argument("--material", action="append", default=[])
    sub.choices["push"].add_argument(
        "--create-pr", action="store_true",
        help="open a pull request on the dataset instead of writing to it "
             "directly (the route for contributors without write access)")
    sub.choices["push"].add_argument(
        "--claim", type=int, metavar="N",
        help="with --create-pr: the GitHub claim issue number this table belongs to")
    sub.choices["push"].add_argument(
        "--github", metavar="LOGIN",
        help="with --create-pr: your GitHub login, so the maintainer can credit you")
    contrib_cli.add_parsers(sub)
    a = p.parse_args(argv)
    if a.cmd is None:
        p.print_usage()
        return 2
    if a.cmd in contrib_cli.CONTRIB_COMMANDS:
        return contrib_cli.run(a, hub_factory=None if hub_factory is _default_hub
                               else hub_factory, gh_factory=gh_factory)
    tables = Path(a.tables)
    if not tables.is_dir():
        print(f"error: not a directory: {tables}", file=sys.stderr)
        return 2
    if a.cmd == "push" and (getattr(a, "claim", None) or getattr(a, "github", None)) \
            and not a.create_pr:
        print("error: --claim and --github only apply with --create-pr", file=sys.stderr)
        return 2
    hub = hub_factory(a.repo)

    if a.cmd == "push" and a.create_pr:
        # A contributor has no write access, so this path must not touch
        # manifest.json at all: not the remote one (the maintainer regenerates
        # it after merging, and a PR that edits it would conflict with every
        # other open PR), and not the local one either -- writing into someone
        # else's tables directory is a side effect they did not ask for.
        names = a.material or sorted({f.name[: -len(".hm")]
                                      for f in tables.glob("*.hm")})
        paths = [f for mat in names
                 for f in (tables / f"{mat}.hm", tables / f"{mat}.stats.json")
                 if f.exists()]
        if not paths:
            print(f"error: no tables to propose in {tables}", file=sys.stderr)
            return 2
        try:
            from .contrib.links import format_links
            url = hub.open_pr(paths, "Add " + ", ".join(names),
                              description=format_links(a.claim, a.github))
        except Exception as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        for f in paths:
            print(f"proposed {f.name}")
        print(f"opened pull request: {url}" if url else "opened pull request")
        return 0

    if a.cmd == "push":
        try:
            gen_version = "unknown"
            for sc in sorted(tables.glob("*.stats.json")):
                gen_version = json.loads(sc.read_text()).get("generator_version",
                                                              "unknown")
                break
            local_manifest = build_manifest(tables, gen_version)
            (tables / "manifest.json").write_text(
                json.dumps(local_manifest, indent=2, sort_keys=True))
            local_files = local_manifest["files"]
            names = a.material or sorted({f.name[: -len(".hm")]
                                          for f in tables.glob("*.hm")})

            # Fetch the remote manifest *before* uploading anything: if this
            # fails (transient network error, corrupt manifest), we must not
            # upload a manifest that forgets previously-pushed materials.
            remote_manifest = hub.fetch_manifest()
            remote_files = (dict(remote_manifest.get("files", {}))
                            if remote_manifest is not None else {})

            paths = [f for mat in names
                     for f in (tables / f"{mat}.hm", tables / f"{mat}.stats.json")
                     if f.exists()]
            for f in paths:
                remote_files[f.name] = local_files[f.name]
            upload_manifest = {"schema": 1, "generator_version": gen_version,
                                "files": remote_files}

            with tempfile.TemporaryDirectory() as tmpdir:
                manifest_path = Path(tmpdir) / "manifest.json"
                manifest_path.write_text(json.dumps(upload_manifest,
                                                     indent=2, sort_keys=True))
                # Chunked, not one commit per file. The Hub allows 128
                # repository commits an hour, and a full corpus is ~590 files,
                # so per-file commits die partway through with a 429 that
                # retrying cannot fix. Chunking keeps each commit's payload
                # reasonable while turning the whole push into ~10 commits.
                #
                # The manifest rides in the LAST chunk so it never advertises a
                # file that is not there yet: if an earlier chunk fails, the
                # uploaded tables are simply invisible until a re-run completes,
                # which is the same failure mode as before and a safe one.
                batches = [paths[i:i + _COMMIT_CHUNK]
                           for i in range(0, len(paths), _COMMIT_CHUNK)] or [[]]
                for n, batch in enumerate(batches, 1):
                    files = list(batch)
                    if n == len(batches):
                        files = files + [manifest_path]
                    hub.commit_files(
                        files,
                        f"Add {len(batch)} files ({n}/{len(batches)})"
                        if len(batches) > 1 else f"Add {len(batch)} files")
                    for f in batch:
                        print(f"pushed {f.name}")
                    if n == len(batches):
                        print("pushed manifest.json")
            return 0
        except Exception as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    # pull
    try:
        manifest = hub.fetch_manifest()
        if manifest is None:
            print("error: remote has no manifest", file=sys.stderr)
            return 1
        materials = a.material or sorted({name[: -len(".hm")]
                                          for name in manifest.get("files", {})
                                          if name.endswith(".hm")})
        for mat in materials:
            for name in (f"{mat}.hm", f"{mat}.stats.json"):
                if name not in manifest.get("files", {}):
                    continue
                f = hub.download(name, tables)
                if not verify_file(f, manifest):
                    f.unlink(missing_ok=True)
                    print(f"error: sha256 mismatch for {name}", file=sys.stderr)
                    return 1
                print(f"pulled {name}")
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
