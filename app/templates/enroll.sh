#!/bin/bash
###############################################################################
# hAI.BackupServer - universelles Enroll-Script
# Erkennt Docker-Container dieses Hosts, registriert den Host am Orchestrator
# und richtet das Backup-Script samt Cronjob ein. Enthaelt KEINE Zugangsdaten.
###############################################################################
set -euo pipefail

ORCH_URL=@@ORCH_URL@@
TARGET_DIR="${HAI_TARGET_DIR:-/opt/backup}"
CRON_DIR="${HAI_CRON_DIR:-/etc/cron.d}"
BACKUP_DIR_NAME="${HAI_BACKUP_DIR_NAME:-}"

usage() {
  cat <<'EOF'
Verwendung: sudo ./enroll.sh [Optionen]

  --help, -h          Diese Hilfe
  --dry-run           Nur erkennen und anzeigen, nichts senden/installieren
  --yes, -y           Alle Rueckfragen mit Standardwerten beantworten
  --host-name NAME    Hostname statt "hostname -s" verwenden
  --backup-dir NAME    Backup-Verzeichnisname (Standard: Server)
  --update-config     Bei erneutem Enroll die Container-Konfiguration auf dem Server ueberschreiben
  --run-now           Nach der Installation sofort einen Backup-Lauf starten

Das Enroll-Token wird aus der Umgebungsvariable ENROLL_TOKEN gelesen oder
verdeckt abgefragt. Nicht als Argument uebergeben (Shell-History / ps).
Wiederholtes Ausfuehren ist sicher: derselbe Host bleibt derselbe Eintrag.
Das Script richtet KEINEN NAS-Mount ein - der Zielpfad muss bereits gemountet sein.
EOF
}

YES=false; DRY=false; RUN_NOW=false; UPDATE_CFG=false; HOST_NAME_ARG=""; BACKUP_DIR_ARG=""
while [ $# -gt 0 ]; do
  case "$1" in
    --help|-h) usage; exit 0 ;;
    --yes|-y) YES=true ;;
    --dry-run) DRY=true ;;
    --run-now) RUN_NOW=true ;;
    --update-config) UPDATE_CFG=true ;;
    --host-name) HOST_NAME_ARG="${2:-}"; shift ;;
    --backup-dir) BACKUP_DIR_ARG="${2:-}"; shift ;;
    *) echo "Unbekannte Option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

die() { echo "FEHLER: $*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || die "Benoetigtes Programm fehlt: $1"; }
json_escape() { printf '%s' "$1" | tr '\n\t\r' '   ' | tr -d '\000-\037' | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'; }
ask() {  # ask "Frage" default(j|n)
  [ "$YES" = "true" ] && { [ "$2" = "j" ]; return; }
  local a; read -r -p "$1 [$( [ "$2" = "j" ] && echo J/n || echo j/N )] " a || true
  case "${a:-}" in [jJyY]*) return 0 ;; [nN]*) return 1 ;; *) [ "$2" = "j" ] ;; esac
}
forbidden() {
  case "$1" in
    /|/etc|/root|/boot|/run|/var|/var/run|/usr|/bin|/sbin|/lib|/lib64|/home) return 0 ;;
    /proc*|/sys*|/dev*|*docker.sock|*secret*) return 0 ;;
  esac
  return 1
}

[ "$DRY" = "true" ] || [ "${HAI_SKIP_ROOT_CHECK:-0}" = "1" ] || [ "$(id -u)" -eq 0 ] || die "Bitte als root ausfuehren (sudo)."
for c in docker curl rsync gzip findmnt sha256sum; do need "$c"; done

HOST_NAME="${HOST_NAME_ARG:-$(hostname -s)}"
printf '%s' "$HOST_NAME" | grep -Eq '^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$' || die "Ungueltiger Hostname '${HOST_NAME}' (--host-name verwenden)."
if [ -r /etc/machine-id ] && [ -s /etc/machine-id ]; then FPR_SRC="$(cat /etc/machine-id)"; else FPR_SRC="$HOST_NAME"; fi
FPR="$(printf '%s' "$FPR_SRC" | sha256sum | cut -c1-32)"

echo "== Erkenne Container auf ${HOST_NAME} =="
CJSON=""; DJSON=""
while IFS= read -r name; do
  [ -n "$name" ] || continue
  if ! printf '%s' "$name" | grep -Eq '^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$'; then echo "  uebersprungen (Name ungueltig): $name"; continue; fi
  image="$(docker inspect --format '{{.Config.Image}}' "$name" 2>/dev/null || true)"
  paths=(); PJSON=""
  while IFS='|' read -r mtype msrc mdst; do
    [ -n "${msrc:-}" ] || continue
    case "$mtype" in bind|volume) ;; *) continue ;; esac
    if forbidden "$msrc"; then echo "    ausgeschlossen (sensibel): $msrc"; continue; fi
    [ -d "$msrc" ] || { echo "    ausgeschlossen (kein Verzeichnis): $msrc"; continue; }
    paths+=("$msrc")
    PJSON="${PJSON:+$PJSON,}\"$(json_escape "$msrc")\""
  done < <(docker inspect --format '{{range .Mounts}}{{.Type}}|{{.Source}}|{{.Destination}}{{"\n"}}{{end}}' "$name" 2>/dev/null)
  echo "- ${name}  (${image:-?}) Pfade: ${paths[*]:-keine}"
  if ask "  Container ${name} sichern?" j; then
    CJSON="${CJSON:+$CJSON,}{\"name\":\"$(json_escape "$name")\",\"volume_paths\":[${PJSON}]}"
    case "$image" in *postgres*)
      if ask "  ${name} ist PostgreSQL - zusaetzlich per pg_dumpall sichern?" j; then
        DJSON="${DJSON:+$DJSON,}{\"name\":\"$(json_escape "$name")\",\"db_user\":\"postgres\"}"
      fi ;;
    esac
  fi
done < <(docker ps -a --format '{{.Names}}')

BACKUP_DIR_NAME="${BACKUP_DIR_ARG:-$( [ "$YES" = "true" ] && echo "Server" || ask "Backup-Verzeichnisname" Server && echo "$REPLY" || echo "Server" )}"
PAYLOAD="{\"host_name\":\"$(json_escape "$HOST_NAME")\",\"fingerprint\":\"${FPR}\",\"update_config\":${UPDATE_CFG},\"backup_dir_name\":\"$(json_escape "$BACKUP_DIR_NAME")\",\"containers\":[${CJSON}],\"db_containers\":[${DJSON}]}"
if [ "$DRY" = "true" ]; then
  echo "== Trockenlauf - wuerde senden an ${ORCH_URL}/api/enroll =="; echo "$PAYLOAD"; exit 0
fi
[ "$YES" = "true" ] || ask "Host jetzt am Orchestrator registrieren und Backup einrichten?" j || { echo "Abgebrochen."; exit 0; }

TOKEN="${ENROLL_TOKEN:-}"
if [ -z "$TOKEN" ]; then read -r -s -p "Enroll-Token: " TOKEN; echo; fi
[ -n "$TOKEN" ] || die "Kein Enroll-Token angegeben."

umask 077
HDR="$(mktemp)"; TMP="$(mktemp)"; BODY="$(mktemp)"
trap 'rm -f "$HDR" "$TMP" "$BODY"' EXIT
printf 'X-Enroll-Token: %s\n' "$TOKEN" > "$HDR"
printf '%s' "$PAYLOAD" > "$BODY"
RESP="$(curl -fsS -m 30 -X POST -H "@${HDR}" -H 'Content-Type: application/json' --data-binary "@${BODY}" "${ORCH_URL}/api/enroll?format=env")" \
  || die "Enrollment fehlgeschlagen (Token falsch oder Server nicht erreichbar)."
HOST_ID="$(printf '%s\n' "$RESP" | sed -n 's/^HOST_ID=\([A-Za-z0-9_-]\{1,32\}\)$/\1/p' | head -n1)"
HOST_TOKEN="$(printf '%s\n' "$RESP" | sed -n 's/^HOST_TOKEN=\([A-Za-z0-9_-]\{20,128\}\)$/\1/p' | head -n1)"
CRON_SCHEDULE="$(printf '%s\n' "$RESP" | sed -n 's/^CRON_SCHEDULE=\([0-9*/, -]\{1,60\}\)$/\1/p' | head -n1)"
[ -n "$HOST_ID" ] && [ -n "$HOST_TOKEN" ] || die "Unerwartete Serverantwort."
CRON_SCHEDULE="${CRON_SCHEDULE:-0 3 * * *}"

printf 'X-Host-Token: %s\n' "$HOST_TOKEN" > "$HDR"
curl -fsS -m 30 -H "@${HDR}" "${ORCH_URL}/script/${HOST_ID}" -o "$TMP" || die "Script-Download fehlgeschlagen."
bash -n "$TMP" || die "Heruntergeladenes Script hat Syntaxfehler - Abbruch."
install -d -m 700 "$TARGET_DIR"
SCRIPT="${TARGET_DIR}/full_backup_${HOST_ID}.sh"
install -m 700 "$TMP" "$SCRIPT"
install -d "$CRON_DIR"
printf '%s root %s >> /var/log/backup_%s.log 2>&1\n' "$CRON_SCHEDULE" "$SCRIPT" "$HOST_ID" > "${CRON_DIR}/hai-backup-${HOST_ID}"
chmod 644 "${CRON_DIR}/hai-backup-${HOST_ID}"
echo "== Fertig: Host-ID ${HOST_ID}, Script ${SCRIPT}, Zeitplan '${CRON_SCHEDULE}' =="
echo "Pruefen Sie, dass ${HOST_NAME} das NAS unter dem konfigurierten Pfad gemountet hat."
if [ "$RUN_NOW" = "true" ]; then "$SCRIPT"; else echo "Erster Lauf: sudo ${SCRIPT}"; fi
