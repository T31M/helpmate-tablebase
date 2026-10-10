"""helpmate-tables pages: material pages for done materials, built in parallel jobs that each
write their own directory, then folded into site/data sequentially and shipped as a docs PR."""
from __future__ import annotations

import importlib.util
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


def _load_build_problems(checkout: Path):
    path = checkout / "tools" / "build_problems.py"
    spec = importlib.util.spec_from_file_location("_helpmate_build_problems", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fold(checkout: Path, job_dirs: list[tuple[Path, list[str]]]) -> list[str]:
    """Copy the pages of every job into site/data and merge its index rows and themes;
    returns the materials whose page file exists. The job directories stay (a rerun folds again)."""
    bp = _load_build_problems(checkout)
    data = checkout / "site" / "data"
    (data / "material").mkdir(parents=True, exist_ok=True)
    built: list[str] = []
    for job_dir, mats in job_dirs:
        have = [m for m in mats if (job_dir / "material" / f"{m}.json").exists()]
        for m in have:
            shutil.copyfile(job_dir / "material" / f"{m}.json", data / "material" / f"{m}.json")
        built += have
        if not have:
            continue
        processed = set(have)
        idx_path, th_path = data / "index.json", data / "themes.json"
        rows = json.loads((job_dir / "index.json").read_text()) if (job_dir / "index.json").exists() else []
        themes = json.loads((job_dir / "themes.json").read_text()) if (job_dir / "themes.json").exists() else {}
        existing = json.loads(idx_path.read_text()) if idx_path.exists() else []
        idx_path.write_text(json.dumps(
            bp.merge_index(existing, [r for r in rows if r["material"] in processed], processed), indent=1))
        old_themes = json.loads(th_path.read_text()) if th_path.exists() else {}
        # job themes.json is the merged-form {theme: {count, problems}}; merge_themes takes entry lists
        new_entries = {t: [p for p in info.get("problems", []) if p["material"] in processed]
                       for t, info in themes.items()}
        th_path.write_text(json.dumps(bp.merge_themes(old_themes, new_entries, processed), indent=1))
    return sorted(built)


def run_pages(materials: list[str], *, checkout: Path, tables: Path, binary: str, jobs: int,
              staging: Path, git, today: str, allow_failures: bool = False,
              runner=subprocess.Popen) -> int:
    from .accept import DOCS_PATHS
    from .site_data import write_site_data

    checkout, staging = Path(checkout), Path(staging)
    materials = sorted(set(materials))
    if not materials:
        print("no material pages to build", file=sys.stderr)
        return 0
    staging.mkdir(parents=True, exist_ok=True)
    state_path = staging / f"pages-{today}.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    if state.get("materials") != materials:
        state = {"done_jobs": [], "materials": materials}

    def save() -> None:
        state_path.write_text(json.dumps(state, indent=1))

    if "original" not in state:
        state["original"] = git.current()
    save()
    branch = f"data/pages-{today}"
    job_mats = split_jobs(materials, jobs)
    job_dirs = [(staging / f"pages-{today}" / f"job-{i}", mats) for i, mats in enumerate(job_mats)]
    if "pr" not in state:
        running = []
        for i, (job_dir, mats) in enumerate(job_dirs):
            if i in state["done_jobs"]:
                continue
            shutil.rmtree(job_dir, ignore_errors=True)
            (job_dir / "material").mkdir(parents=True)
            shutil.copyfile(checkout / "site" / "data" / "materials.json", job_dir / "materials.json")
            cmd = [sys.executable, str(checkout / "tools" / "build_problems.py"), "--tables", str(tables),
                   "--binary", binary, "--out", str(job_dir)]
            for m in mats:
                cmd += ["--material", m]
            running.append((i, runner(cmd, cwd=checkout)))
        failed: list[str] = []
        for i, proc in running:
            rc = proc.wait()
            job_dir, mats = job_dirs[i]
            lost = [m for m in mats if not (job_dir / "material" / f"{m}.json").exists()]
            if rc == 0 and not lost:
                state["done_jobs"].append(i)
                save()
        for i, (job_dir, mats) in enumerate(job_dirs):
            if i not in state["done_jobs"]:
                failed += [m for m in mats if not (job_dir / "material" / f"{m}.json").exists()]
        failed = sorted(failed)
        # a clean slate from origin/main, then the pages of every job (repeatable until committed)
        if not state.get("committed"):
            git.reset_to_origin_main(branch, DOCS_PATHS)
            built = _fold(checkout, job_dirs)
        else:
            built = sorted(set(materials) - set(failed))
        if failed:
            print(f"no page built for {len(failed)} material(s): {', '.join(failed)}", file=sys.stderr)
            if not allow_failures:
                git.back(state["original"])
                return 1
        if not built:
            git.back(state["original"])
            return 1
        title = f"Site: material pages for {len(built)} material(s)"
        body = ", ".join(built)
        if failed:
            body += "\n\nfailed (no page): " + ", ".join(failed)
        if not state.get("committed"):
            write_site_data(checkout / "site" / "data", tables)
            git.commit_all(title + "\n\n" + body)
            state["committed"] = True
            state["body"], state["title"] = body, title
            save()
        if not state.get("pushed"):
            git.push(branch)
            state["pushed"] = True
            save()
        state["pr"] = git.open_pr(state["title"], state["body"], branch)
        save()
    git.back(state["original"])  # before the merge deletes the data branch
    git.wait_and_merge(state["pr"], branch)
    state_path.unlink()
    return 0
