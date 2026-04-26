#!/usr/bin/env bash
# HausRadar – Datenbank-Backup
#
# Erstellt ein konsistentes Backup der SQLite-Datenbank (auch bei laufendem Server).
# Behält die letzten 14 Backups, ältere werden automatisch gelöscht.
#
# Verwendung:
#   bash scripts/backup_db.sh
#   bash scripts/backup_db.sh --dest /mnt/usb/backups
#
# Als Cronjob (täglich 03:00):
#   0 3 * * * /opt/hausradar/scripts/backup_db.sh >> /var/log/hausradar/backup.log 2>&1

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB_PATH="$PROJECT_DIR/data/hausradar.db"
BACKUP_DIR="$PROJECT_DIR/data/backups"
KEEP=14

# Alternatives Backup-Ziel per Argument
while [[ $# -gt 0 ]]; do
    case $1 in
        --dest) BACKUP_DIR="$2"; shift 2 ;;
        *) echo "Unbekannte Option: $1" >&2; exit 1 ;;
    esac
done

TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_FILE="$BACKUP_DIR/hausradar_${TIMESTAMP}.db"

# Datenbank muss existieren
if [[ ! -f "$DB_PATH" ]]; then
    echo "[$(date '+%F %T')] FEHLER: Datenbank nicht gefunden: $DB_PATH" >&2
    exit 1
fi

mkdir -p "$BACKUP_DIR"

# sqlite3 .backup ist sicher bei laufendem Prozess (nutzt SQLite-WAL)
if command -v sqlite3 &>/dev/null; then
    sqlite3 "$DB_PATH" ".backup '$BACKUP_FILE'"
else
    # Fallback: cp (nur sicher wenn Server gestoppt ist)
    cp "$DB_PATH" "$BACKUP_FILE"
fi

SIZE="$(du -sh "$BACKUP_FILE" | cut -f1)"
echo "[$(date '+%F %T')] Backup erstellt: $BACKUP_FILE  ($SIZE)"

# Alte Backups rotieren: nur die neuesten $KEEP behalten
EXCESS=$(find "$BACKUP_DIR" -maxdepth 1 -name 'hausradar_*.db' | sort | head -n -"$KEEP")
if [[ -n "$EXCESS" ]]; then
    echo "$EXCESS" | xargs rm -f
    COUNT=$(echo "$EXCESS" | wc -l)
    echo "[$(date '+%F %T')] $COUNT alte Backup(s) gelöscht (behalte letzte $KEEP)"
fi
