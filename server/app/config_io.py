"""
Gemeinsame Hilfsfunktionen für atomares Lesen und Schreiben von JSON-Config-Dateien.

Atomares Schreiben: erst in .tmp-Datei, dann umbenennen → kein korrupter
Zustand bei Stromausfall oder Prozess-Absturz während des Schreibens.
"""

import json
import logging
from pathlib import Path

from fastapi import HTTPException

logger = logging.getLogger(__name__)


def load_json(path: Path):
    """Lädt JSON-Datei. Wirft HTTP 500 bei Fehler (für API-Handler)."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail=f"{path.name} nicht gefunden")
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"{path.name}: ungültiges JSON – {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{path.name} lesen fehlgeschlagen: {e}")


def save_json(path: Path, data) -> None:
    """Schreibt JSON atomar: erst .tmp, dann rename → kein halb-geschriebener Zustand."""
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.chmod(0o600)   # HR-SEC-006: nur Owner darf Config-Dateien lesen
        tmp.replace(path)  # atomar auf POSIX, best-effort auf Windows
    except Exception as e:
        tmp.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"{path.name} schreiben fehlgeschlagen: {e}")
