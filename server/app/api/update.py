"""
Update-API für HausRadar.

Endpunkte:
  GET  /api/update/status   → Aktueller Commit vs. origin/main
  POST /api/update/start    → Update im Hintergrund starten
  GET  /api/update/stream   → SSE-Fortschrittsstream
  POST /api/update/cancel   → Zustand zurücksetzen (nach done/failed)

Ablauf:
  1. Aktuellen Commit merken
  2. config/*.json → /tmp/hausradar_backup_*/  sichern
  3. git fetch origin main
  4. git reset --hard origin/main
  5. config/*.json aus Backup wiederherstellen  (Nutzerdaten bleiben erhalten)
  6. pip install -r requirements.txt
  7. Python-Import-Check (server-Sanity)
  8. sudo systemctl restart hausradar
     → dieser Prozess stirbt; Browser erkennt Verbindungsabbruch und fragt
       GET /api/health bis der neue Prozess antwortet.

Rollback (bei Fehler in Schritt 6–7):
  - git reset --hard <prev_commit>
  - config/*.json aus Backup wiederherstellen
"""

import asyncio
import json
import logging
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.version import __version__ as _current_version

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/update", tags=["update"])

BASE_DIR     = Path(__file__).resolve().parent.parent.parent.parent
CONFIG_DIR   = BASE_DIR / "config"
SERVER_DIR   = BASE_DIR / "server"
VENV_PY      = SERVER_DIR / ".venv" / "bin" / "python"
SERVICE_NAME = "hausradar"


# ---------------------------------------------------------------------------
# Gemeinsamer Zustand (thread-sicher über GIL + _lock)
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_state: dict = {
    "phase":       "idle",   # idle | running | restarting | done | failed
    "log":         [],       # [{"level", "msg", "pct", "ts"}]
    "prev_commit": None,     # str – zum Rollback
    "backup_dir":  None,     # str – Pfad zum Config-Backup
}


def _emit(level: str, msg: str, pct: int = -1) -> None:
    entry = {"level": level, "msg": msg, "pct": pct, "ts": time.time()}
    logger.info("[update/%s] %s", level, msg)
    with _lock:
        _state["log"].append(entry)


def _git(args: list, cwd: Path = None, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git"] + args,
        capture_output=True, text=True,
        cwd=str(cwd or BASE_DIR),
        timeout=timeout,
    )


# ---------------------------------------------------------------------------
# GET /api/update/status
# ---------------------------------------------------------------------------

@router.get("/status")
def get_status():
    """Liest aktuellen Commit und den Stand von origin/main (erfordert Internet)."""
    try:
        # Aktueller Commit
        r = _git(["rev-parse", "HEAD"])
        cur_hash = r.stdout.strip() if r.returncode == 0 else ""

        r2 = _git(["log", "-1", "--format=%s|||%ad", "--date=short", "HEAD"])
        if r2.returncode == 0 and "|||" in r2.stdout:
            cur_msg, cur_date = r2.stdout.strip().split("|||", 1)
        else:
            cur_msg, cur_date = "–", ""

        # Remote abrufen (Timeout kurz halten)
        fetch = _git(["fetch", "origin", "main", "--quiet"], timeout=15)
        fetch_ok = fetch.returncode == 0

        if fetch_ok:
            r3 = _git(["rev-parse", "origin/main"])
            rem_hash = r3.stdout.strip() if r3.returncode == 0 else ""

            r4 = _git(["log", "-1", "--format=%s|||%ad", "--date=short", "origin/main"])
            if r4.returncode == 0 and "|||" in r4.stdout:
                rem_msg, rem_date = r4.stdout.strip().split("|||", 1)
            else:
                rem_msg, rem_date = "–", ""

            r5 = _git(["rev-list", "--count", "HEAD..origin/main"])
            behind_by = int(r5.stdout.strip()) if r5.returncode == 0 else 0

            # Neue Commits auflisten
            r6 = _git(["log", "--oneline", "HEAD..origin/main"])
            new_commits = r6.stdout.strip().splitlines() if r6.returncode == 0 else []
        else:
            rem_hash = rem_msg = rem_date = ""
            behind_by = 0
            new_commits = []

        with _lock:
            phase = _state["phase"]

        # Version aus origin/main lesen (VERSION-Datei im Remote-Branch)
        if fetch_ok:
            r7 = _git(["show", "origin/main:VERSION"])
            rem_version = r7.stdout.strip() if r7.returncode == 0 else ""
        else:
            rem_version = ""

        return {
            "current":          {"hash": cur_hash[:8], "message": cur_msg,
                                 "date": cur_date, "version": _current_version},
            "latest":           {"hash": rem_hash[:8], "message": rem_msg,
                                 "date": rem_date, "version": rem_version},
            "update_available": behind_by > 0,
            "behind_by":        behind_by,
            "new_commits":      new_commits,
            "fetch_ok":         fetch_ok,
            "phase":            phase,
        }
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "GitHub nicht erreichbar (Timeout)")
    except Exception as e:
        raise HTTPException(500, str(e))


# ---------------------------------------------------------------------------
# POST /api/update/start
# ---------------------------------------------------------------------------

@router.post("/start")
def start_update():
    with _lock:
        if _state["phase"] == "running":
            raise HTTPException(409, "Update läuft bereits")
        _state.update({
            "phase": "running", "log": [],
            "prev_commit": None, "backup_dir": None,
        })

    threading.Thread(target=_worker, daemon=True).start()
    return {"started": True}


# ---------------------------------------------------------------------------
# POST /api/update/cancel  – Zustand zurücksetzen
# ---------------------------------------------------------------------------

@router.post("/cancel")
def cancel_update():
    with _lock:
        if _state["phase"] == "running":
            raise HTTPException(409, "Update läuft – kann nicht abgebrochen werden")
        _state["phase"] = "idle"
        _state["log"]   = []
    return {"ok": True}


# ---------------------------------------------------------------------------
# GET /api/update/stream  – SSE
# ---------------------------------------------------------------------------

@router.get("/stream")
async def stream_progress():
    """
    Server-Sent Events: streamt Log-Einträge in Echtzeit.
    Schließt wenn phase=done/failed/restarting erreicht und alle Events gesendet.
    """
    async def gen():
        yield ": connected\n\n"
        sent = 0
        while True:
            with _lock:
                log   = list(_state["log"])
                phase = _state["phase"]

            while sent < len(log):
                yield f"data: {json.dumps(log[sent])}\n\n"
                sent += 1

            if phase in ("done", "failed", "restarting") and sent >= len(log):
                final = {"level": "phase", "msg": phase, "pct": 100 if phase == "done" else -1}
                yield f"data: {json.dumps(final)}\n\n"
                break

            await asyncio.sleep(0.35)
            yield ": keepalive\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":     "no-cache",
            "X-Accel-Buffering": "no",
            "Connection":        "keep-alive",
        },
    )


# ---------------------------------------------------------------------------
# Update-Worker
# ---------------------------------------------------------------------------

def _worker():
    try:
        _do_update()
    except Exception as exc:
        _emit("error", f"Fehler: {exc}", 0)
        _rollback()
        with _lock:
            _state["phase"] = "failed"


def _do_update():
    # ── 1. Aktuellen Commit merken ──────────────────────────────────────────
    _emit("info", "Aktuellen Commit ermitteln …", 5)
    r = _git(["rev-parse", "HEAD"])
    if r.returncode != 0:
        raise RuntimeError("git rev-parse HEAD fehlgeschlagen")
    prev = r.stdout.strip()
    with _lock:
        _state["prev_commit"] = prev
    _emit("ok", f"Aktuell: {prev[:8]}", 8)

    # ── 2. Config sichern ───────────────────────────────────────────────────
    _emit("info", "Konfigurationsdateien sichern …", 10)
    backup = Path(tempfile.mkdtemp(prefix="hausradar_backup_"))
    shutil.copytree(str(CONFIG_DIR), str(backup / "config"))
    with _lock:
        _state["backup_dir"] = str(backup)
    _emit("ok", f"Backup: {backup.name}", 15)

    # ── 3. Remote abrufen ───────────────────────────────────────────────────
    _emit("info", "Verbinde mit GitHub …", 20)
    fetch = _git(["fetch", "origin", "main", "--quiet"], timeout=30)
    if fetch.returncode != 0:
        raise RuntimeError(f"git fetch fehlgeschlagen: {fetch.stderr.strip()}")
    _emit("ok", "GitHub erreichbar", 25)

    # ── 4. Prüfen ob Update nötig ───────────────────────────────────────────
    r2 = _git(["rev-list", "--count", "HEAD..origin/main"])
    behind_by = int(r2.stdout.strip()) if r2.returncode == 0 else 0

    if behind_by == 0:
        _emit("ok", "Bereits auf dem neuesten Stand – kein Update nötig.", 100)
        with _lock:
            _state["phase"] = "done"
        return

    # Neue Commits auflisten
    r3 = _git(["log", "--oneline", "HEAD..origin/main"])
    if r3.returncode == 0:
        for line in r3.stdout.strip().splitlines():
            _emit("info", f"  ↓ {line}", -1)

    # ── 5. Code aktualisieren (force, Config wurde gesichert) ───────────────
    _emit("info", f"{behind_by} Commit(s) herunterladen …", 35)
    pull = _git(["reset", "--hard", "origin/main"])
    if pull.returncode != 0:
        raise RuntimeError(f"git reset --hard fehlgeschlagen: {pull.stderr.strip()}")
    new_hash = _git(["rev-parse", "HEAD"]).stdout.strip()[:8]
    _emit("ok", f"Code aktualisiert → {new_hash}", 50)

    # ── 6. Konfiguration wiederherstellen ───────────────────────────────────
    _emit("info", "Eigene Konfiguration zurückspielen …", 55)
    for f in (backup / "config").glob("*.json"):
        shutil.copy2(str(f), str(CONFIG_DIR / f.name))
    _emit("ok", "Konfigurationsdateien wiederhergestellt", 60)

    # ── 7. Python-Abhängigkeiten ────────────────────────────────────────────
    _emit("info", "Python-Pakete aktualisieren …", 65)
    pip = subprocess.run(
        [str(VENV_PY), "-m", "pip", "install", "-q", "--upgrade",
         "-r", str(SERVER_DIR / "requirements.txt")],
        capture_output=True, text=True,
        cwd=str(SERVER_DIR),
        timeout=300,
    )
    if pip.returncode != 0:
        raise RuntimeError(f"pip install fehlgeschlagen:\n{pip.stderr.strip()[:400]}")
    _emit("ok", "Pakete aktualisiert", 80)

    # ── 8. Code-Prüfung ─────────────────────────────────────────────────────
    _emit("info", "Neuen Code prüfen …", 83)
    check = subprocess.run(
        [str(VENV_PY), "-c", "import app.main; print('ok')"],
        capture_output=True, text=True,
        cwd=str(SERVER_DIR),
        timeout=30,
    )
    if check.returncode != 0 or "ok" not in check.stdout:
        raise RuntimeError(
            f"Code-Prüfung fehlgeschlagen:\n{check.stderr.strip()[:400]}"
        )
    _emit("ok", "Code-Prüfung bestanden", 88)

    # ── 9. Dienst neu starten ────────────────────────────────────────────────
    _emit("info", "Dienst wird neu gestartet …", 92)
    with _lock:
        _state["phase"] = "restarting"

    try:
        restart = subprocess.run(
            ["sudo", "-n", "/usr/bin/systemctl", "restart", SERVICE_NAME],
            capture_output=True, text=True,
            timeout=30,
        )
        rc = restart.returncode
    except Exception as exc:
        # Prozess wurde durch SIGTERM beendet bevor subprocess zurückkehren konnte
        rc = -15

    # rc == 0     → systemctl hat Neustart angestoßen (Prozess wird gleich beendet)
    # rc == -15   → SIGTERM: systemd hat diesen Prozess bereits beendet → Neustart läuft
    # rc < 0      → sonstiger Signal-Kill → ebenfalls als Neustart werten
    # rc > 0      → echter Fehler (z.B. kein sudo-Recht)
    if rc > 0:
        err = (restart.stderr or restart.stdout or "").strip()
        _emit("warn", f"Neustart fehlgeschlagen (exit {rc}): {err or 'kein Fehlertext'}", -1)
        _emit("warn", f"Bitte manuell: sudo systemctl restart {SERVICE_NAME}", -1)
        with _lock:
            _state["phase"] = "done"
    # rc <= 0: Neustart läuft – dieser Prozess wird gleich durch systemd beendet.
    # Der Browser erkennt den Verbindungsabbruch und fragt per /api/health ab.


def _rollback():
    """Stellt den alten Code und die Konfiguration wieder her."""
    try:
        prev   = _state.get("prev_commit")
        backup = _state.get("backup_dir")

        if prev:
            _emit("warn", f"Rollback zu {prev[:8]} …", -1)
            _git(["reset", "--hard", prev])
            _emit("ok", "Code-Rollback abgeschlossen", -1)

        if backup:
            bp = Path(backup) / "config"
            if bp.exists():
                for f in bp.glob("*.json"):
                    shutil.copy2(str(f), str(CONFIG_DIR / f.name))
                _emit("ok", "Konfiguration wiederhergestellt", -1)

        _emit("warn", "Rollback fertig – Dienst manuell neu starten:", -1)
        _emit("warn", f"sudo systemctl restart {SERVICE_NAME}", -1)
    except Exception as e:
        _emit("error", f"Rollback-Fehler: {e}", -1)
