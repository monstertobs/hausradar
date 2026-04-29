"""
HausRadar Versions-Modul.

Die einzige Quelle der Versionsnummer ist die Datei VERSION im Repo-Root.
Beim Release wird VERSION manuell erhöht und ein Git-Tag gesetzt.
"""

from pathlib import Path

_VERSION_FILE = Path(__file__).resolve().parent.parent.parent / "VERSION"


def get_version() -> str:
    """Liest die Versionsnummer aus der VERSION-Datei."""
    try:
        return _VERSION_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        return "unknown"


__version__: str = get_version()
