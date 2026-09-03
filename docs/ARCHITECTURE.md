# Architektur hAI.BackupServer

## Ziel

Zentrales Backup-Control-Center auf **192.168.178.26** (dort liegt auch das
SMB-Share `highfishNAS25`), das:

1. pro Host automatisch ein `full_backup_<HOST_ID>.sh` generiert (Basis:
   [hAI.FullBackupScript](https://github.com/jbkunama1/hAI.FullBackupScript)),
2. eine Weboberflaeche zur Hostverwaltung bereitstellt,
3. eine REST-API fuer Hosts/Agenten/MCP bereitstellt,
4. optional per Filebrowser das SMB-Share im Browser verwaltbar macht.

## Komponenten

| Komponente            | Container            | Zweck                                             |
|------------------------|----------------------|----------------------------------------------------|
| backup-orchestrator     | `backup-orchestrator` | Web-UI, Template-Engine, Script-/Bootstrap-API, JSON-API |
| filebrowser (optional)  | `filebrowser`         | Web-Dateimanager fuer `/mnt/highfishNAS25/Sicherung` |

## Datenfluss

1. Admin pflegt Hosts in der Web-UI (`hosts.yml`).
2. Beim Speichern wird sofort `full_backup_<HOST_ID>.sh` in `/app/generated` erzeugt.
3. Neuer/bestehender Host ruft `GET /bootstrap/{host_id}` ab (einmalig) bzw.
   `GET /script/{host_id}` (bei jedem Cron-Lauf optional erneut, falls sich die
   Konfiguration geaendert hat -- siehe `docs/ROLLOUT.md`).
4. Backup laeuft lokal auf dem Host, schreibt via `rsync`/`docker save` auf das
   SMB-Share.
5. Filebrowser zeigt den Inhalt des Shares im Browser.

## Sicherheitshinweise

- Die Script-/Bootstrap-Endpunkte sind aktuell **ohne Authentifizierung** und
  sollten nur im LAN erreichbar sein (kein Cloudflare-Tunnel ohne Zusatzschutz,
  z.B. Cloudflare Access oder ein API-Token-Header).
- `hosts.yml` enthaelt keine Zugangsdaten, nur Struktur-/Pfadinformationen.
- Fuer produktive Nutzung: Reverse-Proxy mit Basic-Auth oder Cloudflare Access
  vorschalten, bevor der Port 8080 extern erreichbar gemacht wird.

## Erweiterungsideen

- MCP-Server, der `/api/hosts`, `/api/hosts/{id}/regenerate` und
  `/script/{id}` kapselt (Tools: `list_hosts`, `get_host`, `trigger_regenerate`).
- Monitoring-Erweiterung: Hosts melden nach dem Lauf per `curl -X POST
  /api/hosts/{id}/report` Status/Logfile, Dashboard zeigt letzten Lauf +
  Erfolg/Fehler an.
