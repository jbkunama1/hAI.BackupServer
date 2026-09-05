# hAI.BackupServer MCP-Server

Eigenstaendiger MCP-Server (SSE-Transport), der die JSON-API von
hAI.BackupServer als MCP-Tools bereitstellt:

| Tool                     | Beschreibung                                              |
|--------------------------|------------------------------------------------------------|
| `list_backup_hosts`      | Alle konfigurierten Hosts auflisten                         |
| `get_backup_host`        | Detailkonfiguration eines Hosts abrufen                     |
| `upsert_backup_host`     | Host anlegen/aktualisieren, Script wird automatisch generiert |
| `regenerate_backup_script` | Script fuer einen Host neu generieren                     |
| `get_backup_script`      | Aktuelles Bash-Script eines Hosts abrufen                   |
| `get_bootstrap_script`   | Bootstrap-Script fuer einen (neuen) Host abrufen            |
| `check_backup_api_health` | Health-Check der hAI.BackupServer-API                      |

## Deployment

Laeuft am einfachsten im selben Docker-Compose-Stack wie hAI.BackupServer
(siehe `docker-compose.yml` im Repo-Root, Service `backup-mcp`):

```bash
docker compose up -d --build backup-mcp
```

Der Server ist danach unter `http://<ORCHESTRATOR_HOST>:8090/sse` erreichbar.

## Umgebungsvariablen

| Variable                 | Standard                                 | Zweck                                    |
|---------------------------|-------------------------------------------|--------------------------------------------|
| `BACKUP_API_BASE_URL`     | `http://backup-orchestrator:8080`        | interne Docker-Adresse von hAI.BackupServer |
| `BACKUP_API_USER`         | `admin`                                   | Basic-Auth-Benutzer (muss zu main.py passen) |
| `BACKUP_API_PASSWORD`     | *(leer)*                                  | Basic-Auth-Passwort (Pflicht, aus `.env`)   |
| `BACKUP_API_TIMEOUT`      | `15`                                      | Timeout in Sekunden pro API-Call            |

## Einbindung ins hAI.MCP-/AnythingMCP-Gateway

1. Im Gateway (z.B. `hAI.AnythingMCP`) einen neuen **MCP-Server-Connector**
   hinzufuegen (nicht "REST/OpenAPI-Import", sondern direkter MCP-SSE-Endpoint,
   sofern das Gateway das unterstuetzt).
2. URL eintragen: `http://<ORCHESTRATOR_HOST>:8090/sse`
3. Nach dem Verbinden stehen alle sieben Tools automatisch im Gateway zur
   Verfuegung und koennen wie die uebrigen hAI.MCP-Tools von Agenten genutzt
   werden.

**Alternative (falls das Gateway nur OpenAPI/REST-Import kann):** Statt
diesen MCP-Server einzubinden, kann alternativ direkt die REST-API von
hAI.BackupServer importiert werden -- die automatische OpenAPI-Spezifikation
liegt unter `http://<ORCHESTRATOR_HOST>:8080/openapi.json` und enthaelt
bereits saubere Tags/Beschreibungen fuer jeden Endpoint (siehe
`docs/mcp_integration.md` im Repo-Root).

## Lokaler Test (stdio, z.B. fuer Claude Desktop)

Fuer lokale Tests ohne Docker kann der Server auch per stdio laufen, indem
in `server.py` `mcp.run(transport="sse")` durch `mcp.run()` (Standard: stdio)
ersetzt wird. Fuer den produktiven Betrieb im Compose-Stack bleibt SSE die
empfohlene Transport-Variante.
