# MCP-Integration

hAI.BackupServer stellt zwei Wege bereit, die Backup-Verwaltung als MCP-Tools
fuer Agenten (z.B. im hAI.MCP-/AnythingMCP-Gateway) nutzbar zu machen.

## Weg 1: eigener MCP-Server (empfohlen)

Im Verzeichnis `mcp_server/` liegt ein eigenstaendiger MCP-Server (Python,
`mcp`-SDK, SSE-Transport), der folgende Tools bereitstellt:

| MCP-Tool                 | Ruft intern auf                              | Zweck                              |
|----------------------------|-----------------------------------------------|-------------------------------------|
| `list_backup_hosts`        | `GET /api/hosts`                              | Alle konfigurierten Hosts auflisten |
| `get_backup_host`          | `GET /api/hosts/{host_id}`                    | Details zu einem Host               |
| `upsert_backup_host`       | `POST /api/hosts`                             | Host anlegen/aktualisieren          |
| `regenerate_backup_script` | `POST /api/hosts/{host_id}/regenerate`        | Script neu generieren               |
| `get_backup_script`        | `GET /script/{host_id}`                       | Aktuelles Bash-Script abrufen        |
| `get_bootstrap_script`     | `GET /bootstrap/{host_id}`                    | Bootstrap-Script fuer neuen Host     |
| `check_backup_api_health`  | `GET /api/health`                             | Erreichbarkeit pruefen               |

Start ueber den Compose-Stack (`docker compose up -d backup-mcp`), danach
Registrierung im Gateway ueber die SSE-URL
`http://192.168.178.26:8090/sse` -- Details siehe `mcp_server/README.md`.

## Weg 2: direkter OpenAPI-Import (Alternative)

Falls das Gateway REST-/OpenAPI-Import bevorzugt (statt eines separaten
MCP-Servers): hAI.BackupServer liefert unter
`http://192.168.178.26:8080/openapi.json` eine vollstaendige, mit Tags und
Beschreibungen versehene OpenAPI-Spezifikation (FastAPI generiert diese
automatisch aus den Endpoint-Definitionen in `app/main.py`). Beim Import als
Connector muss zusaetzlich HTTP Basic Auth (Benutzer/Passwort aus `.env`)
hinterlegt werden.

## Beispiel-Agentenablauf

Mit den Tools aus Weg 1 kann ein Agent z.B. auf Zuruf:

1. `list_backup_hosts` aufrufen, um zu pruefen, welche Hosts schon
   angebunden sind.
2. `upsert_backup_host` mit neuen Containerdaten aufrufen, um einen neuen
   Server anzulegen ("Lege einen neuen Backup-Host highfish12 mit Container
   xyz an").
3. `get_bootstrap_script` abrufen und dem Nutzer das fertige Script zur
   Ausfuehrung auf dem neuen Server praesentieren.
