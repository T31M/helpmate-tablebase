"""Contribution pipeline: claims, verification, acceptance, generated docs.

Every module here is importable without the C++ bindings; the ones that need
them (or numpy / zstandard / python-chess) import inside functions.
"""
from pathlib import Path

DATASET_REPO = "osick/helpmate-tables"
GITHUB_REPO = "osick/helpmate-tablebase"
DEFAULT_STAGING = Path("~/tb-staging").expanduser()
SITE_MATERIALS_URL = "https://osick.github.io/helpmate-tablebase/#/materials"
