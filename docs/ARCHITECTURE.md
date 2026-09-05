# Architektur hAI.BackupServer

## Ziel

Zentrales Backup-Control-Center auf **192.168.178.26** (dort liegt auch das
SMB-Share `highfishNAS25`), das:

1. pro Host automatisch ein `full_backup_<HOST_ID>.sh` generiert (Basis:
   [hAI.FullBackupScript](https://github.com/jbkunama1/hAI.FullBackupScript)),
2. eine Weboberflaeche zur Hostverwaltung bereitstellt (geschuetzt per
   HTTP Basic Auth),
3. eine REST-API fuer Hosts/Agenten/MCP bereitstellt (ebenfalls per Basic
   Auth geschuetzt),
4. einen eigenen MCP-Server (`mcp_server/`) bereitstellt, der diese API als
   MCP-Tools kapselt,
5. optional per Filebrowser das SMB-Share im Browser verwaltbar macht.

## Komponenten

| Komponente            | Container            | Zweck                                             |
|------------------------|----------------------|----------------------------------------------------|
| backup-orchestrator     | `backup-orchestrator` | Web-UI, Template-Engine, Script-/Bootstrap-API, JSON-API (Basic Auth) |
| backup-mcp              | `backup-mcp`          | MCP-Server (SSE), kapselt die JSON-API als Tools fuer Agenten |
| filebrowser (optional)  | `filebrowser`         | Web-Dateimanager fuer `/mnt/highfishNAS25/Sicherung` |

## Datenfluss

1. Admin pflegt Hosts in der Web-UI (`hosts.yml`) -- Login per Basic Auth
   (`BASIC_AUTH_USER`/`BASIC_AUTH_PASSWORD`).
2. Beim Speichern wird sofort `full_backup_<HOST_ID>.sh` in `/app/generated` erzeugt.
3. Neuer/bestehender Host ruft `GET /bootstrap/{host_id}` (mit `-u user:pass`)
   ab (einmalig) bzw. `GET /script/{host_id}` (bei jedem Cron-Lauf optional
   erneut, falls sich die Konfiguration geaendert hat -- siehe `docs/ROLLOUT.md`).
4. Backup laeuft lokal auf dem Host, schreibt via `rsync`/`docker save` auf das
   SMB-Share.
5. Agenten/MCP-Clients rufen den `backup-mcp`-Server (SSE, Port 8090) auf,
   der intern per Basic Auth mit `backup-orchestrator` spricht.
6. Filebrowser zeigt den Inhalt des Shares im Browser.

## Sicherheit (Basic Auth)

- **Alle** Endpunkte von `backup-orchestrator` (Web-UI, `/script/*`,
  `/bootstrap/*`, `/api/*`) sind per HTTP Basic Auth geschuetzt
  (`BASIC_AUTH_USER` / `BASIC_AUTH_PASSWORD`, gesetzt via `.env`).
- Der Server startet **fail-closed**: ist `BASIC_AUTH_PASSWORD` nicht gesetzt,
  antwortet jeder Request mit HTTP 500 statt ungeschuetzt zu laufen.
- Generierte Bootstrap-Scripte enthalten das Passwort im Klartext (fuer den
  automatischen `curl`-Aufruf noetig) -- daher nur ueber vertrauenswuerdige
  Kanaele im LAN abrufen/aufbewahren, nicht oeffentlich posten.
- `backup-mcp` verwendet dieselben Zugangsdaten intern, um mit
  `backup-orchestrator` zu sprechen (Container-zu-Container, nicht extern
  exponiert).
- `hosts.yml` enthaelt selbst keine Zugangsdaten, nur Struktur-/Pfadinformationen.
- Fuer eine externe Erreichbarkeit (z.B. via Cloudflare Tunnel) zusaetzlich
  Cloudflare Access oder ein IP-Allowlist vorschalten -- Basic Auth allein
  ersetzt keine TLS-Terminierung; im LAN ist das Risiko gering, extern sollte
  zusaetzlich HTTPS erzwungen werden.

## Erweiterungsideen

- Monitoring-Erweiterung: Hosts melden nach dem Lauf per `curl -X POST
  /api/hosts/{id}/report` Status/Logfile, Dashboard zeigt letzten Lauf +
  Erfolg/Fehler an.
- Rate-Limiting/Lockout fuer wiederholte Basic-Auth-Fehlversuche.
