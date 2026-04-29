#!/usr/bin/env bash
# HausRadar – Installations-Skript für Raspberry Pi Zero 2 W
#
# Verwendung (aus dem Projektverzeichnis):
#   bash scripts/install_pi.sh
#
# Was dieses Skript tut:
#   1. System-Pakete installieren (python3-venv, mosquitto)
#   2. Python-Virtualenv erstellen und Abhängigkeiten installieren
#   3. Datenbankverzeichnis anlegen
#   4. Mosquitto für das lokale Netzwerk konfigurieren
#   5. systemd-Service einrichten und starten

set -euo pipefail

# ---------------------------------------------------------------------------
# Farben
# ---------------------------------------------------------------------------
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

ok()   { echo -e "${GREEN}✓${RESET}  $*"; }
info() { echo -e "${CYAN}→${RESET}  $*"; }
warn() { echo -e "${YELLOW}⚠${RESET}  $*"; }
fail() { echo -e "${RED}✗${RESET}  $*" >&2; exit 1; }
step() { echo -e "\n${BOLD}$*${RESET}"; }

# ---------------------------------------------------------------------------
# Plattform-Check
# ---------------------------------------------------------------------------
if [[ "$(uname -s)" != "Linux" ]]; then
    fail "Dieses Skript ist nur für Raspberry Pi (Linux) gedacht."
fi

# Ohne root neu starten mit sudo
if [[ $EUID -ne 0 ]]; then
    info "Starte neu mit sudo …"
    exec sudo -E bash "$0" "$@"
fi

INSTALL_USER="${SUDO_USER:-$(who am i | awk '{print $1}')}"
if [[ -z "$INSTALL_USER" || "$INSTALL_USER" == "root" ]]; then
    INSTALL_USER="pi"
fi

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_NAME="hausradar"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
MOSQUITTO_CONF="/etc/mosquitto/conf.d/hausradar.conf"
VENV_DIR="$PROJECT_DIR/server/.venv"
DATA_DIR="$PROJECT_DIR/data"
LOG_DIR="/var/log/hausradar"

echo ""
echo -e "${BOLD}╔══════════════════════════════════════╗${RESET}"
echo -e "${BOLD}║       HausRadar Installation         ║${RESET}"
echo -e "${BOLD}╚══════════════════════════════════════╝${RESET}"
echo ""
info "Projektpfad : $PROJECT_DIR"
info "Service-User: $INSTALL_USER"
echo ""

# ---------------------------------------------------------------------------
# 1. System-Pakete
# ---------------------------------------------------------------------------
step "1/6  System-Pakete installieren"

apt-get update -qq
PKGS=(python3 python3-venv python3-pip mosquitto mosquitto-clients sqlite3 git)
MISSING=()
for pkg in "${PKGS[@]}"; do
    dpkg -s "$pkg" &>/dev/null || MISSING+=("$pkg")
done

if [[ ${#MISSING[@]} -gt 0 ]]; then
    info "Installiere: ${MISSING[*]}"
    apt-get install -y -qq "${MISSING[@]}"
    ok "Pakete installiert"
else
    ok "Alle Pakete bereits vorhanden"
fi

# ---------------------------------------------------------------------------
# 2. Python-Virtualenv
# ---------------------------------------------------------------------------
step "2/6  Python-Virtualenv einrichten"

if [[ ! -x "$VENV_DIR/bin/pip" ]]; then
    if [[ -d "$VENV_DIR" ]]; then
        warn "Unvollständiges Virtualenv gefunden – wird neu erstellt …"
        rm -rf "$VENV_DIR"
    fi
    info "Erstelle Virtualenv in $VENV_DIR …"
    sudo -u "$INSTALL_USER" python3 -m venv "$VENV_DIR"
    ok "Virtualenv erstellt"
else
    ok "Virtualenv bereits vorhanden"
fi

info "Abhängigkeiten installieren (kann einige Minuten dauern) …"
sudo -u "$INSTALL_USER" "$VENV_DIR/bin/pip" install -q --upgrade pip
sudo -u "$INSTALL_USER" "$VENV_DIR/bin/pip" install -q -r "$PROJECT_DIR/server/requirements.txt"
ok "Python-Abhängigkeiten installiert"

# ---------------------------------------------------------------------------
# 3. Verzeichnisse
# ---------------------------------------------------------------------------
step "3/6  Verzeichnisse anlegen"

mkdir -p "$DATA_DIR" "$LOG_DIR"
chown "$INSTALL_USER:$INSTALL_USER" "$DATA_DIR" "$LOG_DIR"
ok "$DATA_DIR"
ok "$LOG_DIR"

# ---------------------------------------------------------------------------
# 4. Mosquitto konfigurieren
# ---------------------------------------------------------------------------
step "4/6  Mosquitto konfigurieren"

if [[ ! -d /etc/mosquitto/conf.d ]]; then
    mkdir -p /etc/mosquitto/conf.d
fi

cat > "$MOSQUITTO_CONF" << 'EOF'
# HausRadar – Mosquitto-Konfiguration
# Öffnet Port 1883 für das lokale Netzwerk.
# (persistence, log_dest etc. sind bereits in /etc/mosquitto/mosquitto.conf)
listener 1883
allow_anonymous true
EOF

ok "Mosquitto-Konfiguration geschrieben: $MOSQUITTO_CONF"

systemctl enable mosquitto
systemctl restart mosquitto
ok "Mosquitto gestartet"

# ---------------------------------------------------------------------------
# 5. systemd-Service
# ---------------------------------------------------------------------------
step "5/6  systemd-Service installieren"

cat > "$SERVICE_FILE" << EOF
[Unit]
Description=HausRadar Backend
Documentation=file://${PROJECT_DIR}/docs/setup-pi-zero-2.md
After=network-online.target mosquitto.service
Wants=network-online.target

[Service]
Type=simple
User=${INSTALL_USER}
WorkingDirectory=${PROJECT_DIR}
ExecStart=${VENV_DIR}/bin/uvicorn app.main:app \\
    --app-dir ${PROJECT_DIR}/server \\
    --host 0.0.0.0 \\
    --port 8000 \\
    --workers 1 \\
    --log-level warning
Restart=always
RestartSec=10
StandardOutput=append:${LOG_DIR}/hausradar.log
StandardError=append:${LOG_DIR}/hausradar.log

# Speicher-Limit für Pi Zero 2 W (512 MB RAM)
MemoryMax=256M

[Install]
WantedBy=multi-user.target
EOF

ok "Service-Datei geschrieben: $SERVICE_FILE"

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

sleep 2
if systemctl is-active --quiet "$SERVICE_NAME"; then
    ok "HausRadar-Service läuft"
else
    warn "Service gestartet, aber Status unklar – prüfe mit: journalctl -u hausradar -n 30"
fi

# ---------------------------------------------------------------------------
# 6. Firewall-Hinweis + Abschluss
# ---------------------------------------------------------------------------
step "6/6  Abschluss"

# IP-Adresse ermitteln
IP=$(hostname -I | awk '{print $1}')

echo ""
echo -e "${GREEN}${BOLD}╔══════════════════════════════════════════════╗${RESET}"
echo -e "${GREEN}${BOLD}║  HausRadar erfolgreich installiert!          ║${RESET}"
echo -e "${GREEN}${BOLD}╚══════════════════════════════════════════════╝${RESET}"
echo ""
echo -e "  Weboberfläche:   ${BOLD}http://${IP}:8000${RESET}"
echo -e "  API-Health:      ${BOLD}http://${IP}:8000/api/health${RESET}"
echo -e "  MQTT-Broker:     ${BOLD}${IP}:1883${RESET}"
echo ""
echo -e "  Logs anzeigen:    ${CYAN}journalctl -u hausradar -f${RESET}"
echo -e "  Service-Status:   ${CYAN}systemctl status hausradar${RESET}"
echo -e "  Service stoppen:  ${CYAN}systemctl stop hausradar${RESET}"
echo ""
echo -e "  Simulation starten:"
echo -e "  ${CYAN}cd $PROJECT_DIR && source server/.venv/bin/activate${RESET}"
echo -e "  ${CYAN}python3 scripts/simulate_sensor_data.py --mqtt${RESET}"
echo ""
