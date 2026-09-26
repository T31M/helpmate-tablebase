"""The helpmate dashboard, packaged so the API can find it by import.

The files themselves are plain HTML/CSS/ES modules with no build step; this
package exists only to give them an importable, layout-independent address.
"""
from pathlib import Path

__version__ = "0.20.0"


def static_dir() -> Path:
    """Directory holding index.html, css/, js/ and vendor/.

    Deliberately __file__-relative rather than importlib.resources: the caller
    mounts this as a directory on a live server, which needs a real filesystem
    path, and wheels install unzipped.
    """
    return Path(__file__).resolve().parent / "static"
