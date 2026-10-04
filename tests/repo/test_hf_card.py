# tests/repo/test_hf_card.py
"""The dataset card shows the two statistics files in the Hugging Face viewer
and nothing else (the .hm tables are not viewable data)."""
from pathlib import Path

import yaml

CARD = Path(__file__).resolve().parents[2] / "docs" / "hf-dataset-card.md"


def _front_matter() -> dict:
    text = CARD.read_text()
    assert text.startswith("---\n")
    return yaml.safe_load(text.split("---\n")[1])


def test_card_configures_the_viewer_for_the_statistics():
    fm = _front_matter()
    assert fm.get("viewer") is not False
    configs = {c["config_name"]: c for c in fm["configs"]}
    assert configs["materials"]["data_files"] == "stats/materials.parquet"
    assert configs["materials"].get("default") is True
    assert configs["histogram"]["data_files"] == "stats/histogram.parquet"


def test_card_documents_the_statistics():
    text = CARD.read_text()
    assert "## Statistics" in text
    assert 'pd.read_parquet("hf://datasets/osick/helpmate-tables/stats/materials.parquet")' in text
