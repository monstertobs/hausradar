#!/usr/bin/env bash
# HausRadar – Update-Skript für Raspberry Pi
#
# Holt die neuesten Änderungen von GitHub und startet den Dienst neu.
#
# Verwendung (aus dem Projektverzeichnis):
#   bash scripts/update_pi.sh
#
# Was dieses Skript tut:
#   1. Git-Pull (neueste Version vom Repository)
#   2. Python-Abhängigkeiten aktualisieren (falls requirements.txt geändert)
#   3. systemd-Daemon neu laden (falls Service-Unit geändert)
#   4. Dienst neu starten
#   5. Status prüfen

set -euo pipefail

# ---------------------------------------------------------------------------
# Farben + Hilfsfunktionen
# ---------------------------------------------------------------------------
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

ok()   { echo -e "${GREEN}✓${RESET}  $*"; }
info() { echo -e "${CYAN}→${RESET}  $*"; }
warn() { echo -e "${YELLOW}⚠${RESET}  $*"; }
fail() { echo -e "${RED}✗${RESET}  $*" >&2; exit 1; }
step() { echo -e "\n${BOLD}── $* ──${RESET}"; }

# ---------------------------------------------------------------------------
# Pfade
# ---------------------------------------------------------------------------
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PY="$PROJECT_DIR/server/.venv/bin/python"
SERVICE_NAME="hausradar"

echo ""
echo -e "${BOLD}╔══════════════════════════════════════╗${RESET}"
echo -e "${BOLD}║        HausRadar Update              ║${RESET}"
echo -e "${BOLD}╚══════════════════════════════════════╝${RESET}"
echo ""
info "Projektpfad: $PROJECT_DIR"

# ---------------------------------------------------------------------------
# 1. Aktuellen Stand sichern (zeige was sich ändert)
# ---------------------------------------------------------------------------
step "1. Git-Stand prüfen"

cd "$PROJECT_DIR"

if [[ ! -d .git ]]; then
    fail "Kein Git-Repository gefunden in $PROJECT_DIR"
fi

CURRENT_COMMIT=$(git rev-parse HEAD)
info "Aktueller Commit: $(git log --oneline -1)"

# ---------------------------------------------------------------------------
# 2. Neueste Version holen
# ---------------------------------------------------------------------------
step "2. Aktualisiere von GitHub"

git fetch origin main

REMOTE_COMMIT=$(git rev-parse origin/main)

if [[ "$CURRENT_COMMIT" == "$REMOTE_COMMIT" ]]; then
    ok "Bereits auf dem neuesten Stand."
    NEW_COMMITS=0
else
    CHANGES=$(git log --oneline "$CURRENT_COMMIT..origin/main")
    echo ""
    echo -e "${CYAN}Neue Commits:${RESET}"
    echo "$CHANGES" | sed 's/^/  /'
    echo ""
    git pull --ff-only origin main
    ok "Code aktualisiert → $(git log --oneline -1)"
    NEW_COMMITS=$(git log --oneline "$CURRENT_COMMIT..HEAD" | wc -l | tr -d ' ')
fi

# ---------------------------------------------------------------------------
# 3. Python-Abhängigkeiten prüfen und ggf. aktualisieren
# ---------------------------------------------------------------------------
step "3. Python-Abhängigkeiten"

if [[ ! -f "$VENV_PY" ]]; then
    fail "Virtualenv nicht gefunden: $VENV_PY\nBitte erst install_pi.sh ausführen."
fi

# Nur installieren wenn requirements.txt sich geändert hat (oder --force)
REQS="$PROJECT_DIR/server/requirements.txt"
if git diff "$CURRENT_COMMIT" HEAD -- server/requirements.txt | grep -q "^+" 2>/dev/null \
   || [[ "${1:-}" == "--force" ]]; then
    info "requirements.txt hat sich geändert – aktualisiere Pakete …"
    "$VENV_PY" -m pip install -q --upgrade -r "$REQS"
    ok "Pakete aktualisiert"
else
    ok "Keine Paketänderungen nötig"
fi

# ---------------------------------------------------------------------------
# 3b. sudoers-Eintrag prüfen (für Web-Update-Funktion benötigt)
# ---------------------------------------------------------------------------
SUDOERS_FILE="/etc/sudoers.d/hausradar"
CURRENT_USER="${SUDO_USER:-$(whoami)}"
if [[ ! -f "$SUDOERS_FILE" ]]; then
    info "Richte sudoers-Eintrag für Web-Update ein …"
    SYSTEMCTL_BIN="$(which systemctl)"
    echo "${CURRENT_USER} ALL=(ALL) NOPASSWD: ${SYSTEMCTL_BIN} restart hausradar" \
        | sudo tee "$SUDOERS_FILE" > /dev/null
    sudo chmod 440 "$SUDOERS_FILE"
    ok "sudoers gesetzt ($SUDOERS_FILE)"
else
    ok "sudoers-Eintrag vorhanden"
fi

# ---------------------------------------------------------------------------
# 4. systemd-Unit neu laden (falls Service-Datei geändert)
# ---------------------------------------------------------------------------
step "4. systemd"

SERVICE_CHANGED=0
if git diff "$CURRENT_COMMIT" HEAD -- deploy/hausradar.service | grep -q "^+" 2>/dev/null; then
    warn "Service-Unit hat sich geändert – lade Daemon neu …"
    SERVICE_CHANGED=1
fi

# Prüfe ob der Dienst überhaupt läuft (braucht sudo)
if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
    if [[ $SERVICE_CHANGED -eq 1 ]]; then
        info "Installiere neue Service-Unit …"
        # Platzhalter ersetzen wie in install_pi.sh
        INSTALL_USER="${SUDO_USER:-$(whoami)}"
        sed -e "s|__PROJECT_DIR__|$PROJECT_DIR|g" \
            -e "s|__USER__|$INSTALL_USER|g" \
            deploy/hausradar.service \
            | sudo tee /etc/systemd/system/hausradar.service > /dev/null
        sudo systemctl daemon-reload
        ok "systemd-Unit aktualisiert"
    fi

    info "Starte Dienst neu …"
    sudo systemctl restart "$SERVICE_NAME"
    sleep 2

    if systemctl is-active --quiet "$SERVICE_NAME"; then
        ok "Dienst läuft wieder"
    else
        fail "Dienst konnte nicht gestartet werden!\nLog: sudo journalctl -u $SERVICE_NAME -n 30"
    fi
else
    warn "Dienst '$SERVICE_NAME' läuft nicht – kein Neustart."
    info "Starten mit: sudo systemctl start $SERVICE_NAME"
fi

# ---------------------------------------------------------------------------
# 5. Status-Zusammenfassung
# ---------------------------------------------------------------------------
step "5. Status"

echo ""
if [[ $NEW_COMMITS -gt 0 ]]; then
    ok "$NEW_COMMITS neuer/neue Commit(s) eingespielt"
fi
ok "Update abgeschlossen"
echo ""
echo -e "  ${BOLD}Dienst-Status:${RESET}"
systemctl status "$SERVICE_NAME" --no-pager -l 2>/dev/null | head -8 | sed 's/^/  /' || true
echo ""
echo -e "  ${CYAN}Log anzeigen:${RESET}  sudo journalctl -u $SERVICE_NAME -f"
echo -e "  ${CYAN}Log-Datei:${RESET}     tail -f /var/log/hausradar/hausradar.log"
echo ""
