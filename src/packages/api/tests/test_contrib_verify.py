import json
import shutil

from contrib_helpers import flip_frame_byte
from helpmate_server import tables_cli
from helpmate_server.contrib.verify import VerifyOptions, verify_table

FAST = VerifyOptions(samples=100, oracle_samples=3, oracle_plies=3, seed=42)


def test_verify_table_runs_v2_to_v7(compressed_tables):
    r = verify_table("KQvk", compressed_tables, FAST, "99.0.0")
    assert [c.id for c in r.checks] == ["V2", "V3", "V4", "V5", "V6", "V7"]
    assert r.passed


def test_verify_stops_after_a_structural_failure(table_copy):
    flip_frame_byte(table_copy / "KQvk.hm", 2)
    r = verify_table("KQvk", table_copy, FAST, "99.0.0")
    assert [c.id for c in r.checks] == ["V2", "V3"] and not r.passed


def test_cli_verify_material(compressed_tables, capsys, tmp_path):
    out = tmp_path / "r.json"
    rc = tables_cli.main(["verify", "--tables", str(compressed_tables), "--material", "KQvk",
                          "--samples", "100", "--oracle-samples", "3", "--seed", "42",
                          "--report", str(out)])
    assert rc == 0
    text = capsys.readouterr().out
    assert "KQvk" in text and "✅" in text and "seed 42" in text
    data = json.loads(out.read_text())
    assert data["result"] == "pass" and data["tables"]["KQvk"]["passed"]
    assert (data["samples"], data["oracle_samples"], data["oracle_plies"]) == (100, 3, 3)


def test_cli_verify_failure_exit_code(table_copy, capsys):
    flip_frame_byte(table_copy / "KQvk.hm", 2)
    rc = tables_cli.main(["verify", "--tables", str(table_copy), "--material", "KQvk"])
    assert rc == 1
    assert "❌" in capsys.readouterr().out


def test_cli_verify_unknown_material_is_usage_error(compressed_tables, capsys):
    assert tables_cli.main(["verify", "--tables", str(compressed_tables),
                            "--material", "KQQQQQvk"]) == 2


def test_cli_verify_missing_subtable_is_environment_error(compressed_tables, tmp_path, capsys):
    for ext in ("hm", "stats.json"):
        shutil.copy(compressed_tables / f"KPvk.{ext}", tmp_path / f"KPvk.{ext}")
    rc = tables_cli.main(["verify", "--tables", str(tmp_path), "--material", "KPvk",
                          "--samples", "50", "--oracle-samples", "2", "--seed", "1"])
    captured = capsys.readouterr()
    assert rc == 2
    assert captured.err.startswith("error:") and "no table for" in captured.err
    assert "FAILED" not in captured.out


def test_tables_cli_imports_nothing_heavy():
    import subprocess
    import sys
    code = ("import sys, helpmate_server.tables_cli; "
            "bad = [m for m in ('helpmate', 'numpy', 'zstandard', 'chess', 'huggingface_hub') "
            "if m in sys.modules]; print(bad); sys.exit(1 if bad else 0)")
    assert subprocess.run([sys.executable, "-c", code]).returncode == 0


def _assert_sidecar_defect_reported(table_copy, capsys):
    r = verify_table("KQvk", table_copy, FAST, "99.0.0")
    assert not r.passed
    rc = tables_cli.main(["verify", "--tables", str(table_copy), "--material", "KQvk"])
    assert rc == 1
    assert "❌" in capsys.readouterr().out


def test_missing_sidecar_is_a_failed_report_not_a_crash(table_copy, capsys):
    (table_copy / "KQvk.stats.json").unlink()
    _assert_sidecar_defect_reported(table_copy, capsys)


def test_malformed_sidecar_is_a_failed_report_not_a_crash(table_copy, capsys):
    (table_copy / "KQvk.stats.json").write_text("{not json")
    _assert_sidecar_defect_reported(table_copy, capsys)


def test_cli_verify_accepts_several_materials_after_one_flag(compressed_tables, capsys):
    rc = tables_cli.main(["verify", "--tables", str(compressed_tables),
                          "--material", "KQvk", "KPvk",
                          "--samples", "50", "--oracle-samples", "2", "--seed", "1"])
    text = capsys.readouterr().out
    assert rc == 0 and "KQvk" in text and "KPvk" in text
