# Monitoring: Backup-Reports

Stand: 2026-10-26 (ab v1.2.0, Branch `feature/monitoring-reports`)

## Ablauf

Jedes generierte `full_backup_<HOST_ID>.sh` meldet seinen Lauf automatisch an
`POST /api/hosts/<HOST_ID>/report` (HTTP Basic Auth, Credentials stehen wie
beim Bootstrap-Script im generierten Script):

- **FEHLER**: der ERR-Trap ruft `report "error" <EXIT> "..."` auf -- inkl.
  Exit-Code und Zeilennummer. Da der Report per HTTP laeuft und nicht ueber
  das SMB-Share, kommt der Fehler-Report auch dann zentral an, wenn genau der
  NAS-Mount die Fehlerursache war.
- **ERFOLG**: am Script-Ende laeuft `report "ok" 0 "..."`.

Mitgelieferte Felder: `status`, `exit_code`, `duration_seconds`
(via `date +%s`), `size_bytes` (Groesse von `${RUN_DEST}` via `du -sb`),
`message`.

Wichtig: Alle Report-Aufrufe sind mit `|| true` abgesichert und haben ein
curl-Timeout von 15 s -- ein Orchestrator-Ausfall darf das Backup selbst
niemals blockieren oder zum Scheitern bringen.

## Persistenz

Die Reports landen in `app/config/reports.json`. Der Pfad liegt im selben
Bind-Mount wie `hosts.yml` (`./app/config:/app/config`), ueberlebt also
Redeploys des Portainer-Git-Stacks. Die Datei ist in `.gitignore`
eingetragen und wird nicht ins Repo committed.

## Endpunkte

| Methode | Pfad | Zweck |
|---|---|---|
| POST | `/api/hosts/{host_id}/report` | Report nach einem Backup-Lauf melden |
| GET | `/api/hosts/{host_id}/report` | Letzten Report eines Hosts abrufen |
| GET | `/api/reports` | Letzte Reports aller Hosts abrufen |

Beispiel-Report (JSON-Body des Scripts):

```json
{
  "status": "ok",
  "exit_code": 0,
  "duration_seconds": 187,
  "size_bytes": 2348810240,
  "message": "Backup highfish5 erfolgreich abgeschlossen."
}
```

`POST` antwortet mit `404`, wenn die Host-ID nicht konfiguriert ist, und mit
`400`, wenn `status` nicht `ok` oder `error` ist. `GET` auf einen Host ohne
bisherigen Report antwortet ebenfalls mit `404`.

## Dashboard

Die Host-Tabelle im Web-UI zeigt die Spalte **Letzter Lauf** mit Status-Pill
(OK/FEHLER), Zeitpunkt, Dauer und Datenmenge. Die Host-Detailansicht erhaelt
den letzten Report ebenfalls als Template-Kontext (`report`).

## Bezug zum Telegram-Bot (Roadmap)

Diese Reports bilden die Datenbasis fuer den geplanten `backup-telegram`-
Service: Fehler sollen sofort gepusht werden, Erfolge als tagesgesammelter
Digest (inkl. Liste der Hosts ohne Meldung, die nur ueber den Abgleich
konfigurierter Hosts vs. eingegangener Reports erkennbar sind).
