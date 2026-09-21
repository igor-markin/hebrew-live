"""Filesystem defaults that also work from an installed wheel."""
import os
from pathlib import Path


def data_root() -> Path:
    """Return the user-controlled local data root without creating it."""
    override = os.environ.get("HEBREW_LIVE_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / "Library" / "Application Support" / "Hebrew Live CLI"
