"""
Zentrales Versionsmodul für den News Aggregator Bot.
Ermittelt die Version dynamisch aus Git-Tags oder nutzt den statischen Release-Fallback.
"""

import subprocess
from functools import lru_cache
from pathlib import Path

__version__ = "v0.10.1"


@lru_cache(maxsize=1)
def get_app_version() -> str:
    """
    Gibt die aktuelle Version der Anwendung zurück.
    Prüft zunächst 'git describe --tags --abbrev=0'.
    Falls kein Git verfügbar ist (z. B. auf Streamlit Cloud oder in Minimalcontainern),
    wird __version__ als verlässlicher Fallback verwendet.
    """
    repo_dir = Path(__file__).resolve().parent.parent
    try:
        res = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0"],
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if res.returncode == 0:
            tag = res.stdout.strip()
            if tag.startswith("v"):
                return tag
    except Exception:
        pass
    return __version__
