# hAI.BackupServer

Zentrales **Backup-Control-Center** fuer heterogene Docker-/Linux-Umgebungen.

Dieses Repo ergaenzt [`hAI.FullBackupScript`](https://github.com/jbkunama1/hAI.FullBackupScript)
um eine Orchestrierungs-Schicht:

- **Web-UI** (per HTTP Basic Auth geschuetzt) zur Verwaltung aller Backup-Hosts.
- **Template-Engine**, die aus `templates/full_backup_template.sh.j2` fuer jeden Host automatisch
  ein fertiges, ausfuehrbares Backup-Script generiert (`full_backup_<HOST_ID>.sh`).
- **REST-API** (ebenfalls Basic-Auth-geschuetzt), ueber die Hosts fertige Scripte abholen
  und Agenten/MCP-Tools Hosts verwalten koennen.
- **Eigener MCP-Server** (`mcp_server/`, SSE-Transport), der die API direkt als MCP-Tools
  bereitstellt -- fertig zum Einbinden ins hAI.MCP-/AnythingMCP-Gateway.
- **Bootstrap-Script**, das auf einem neuen Server einmalig ausgefuehrt wird: laedt das
  generierte Script, macht es ausfuehrbar und traegt den Cronjob ein.
- **Optionaler Filebrowser-Container**, um das SMB-Share (`highfishNAS25`) direkt im
  Browser zu verwalten.

## Architektur

```
                         +--------------------------------------------+
                         |        192.168.178.26  (SMB-Share-Host)     |
                         |                                            |
  Docker-Host highfish5  |  +---------------+   +----------------+    |
  | bootstrap.sh       |--+->| backup-        |   | backup-mcp     |   |
  |  -> holt Script    |  |  | orchestrator   |<->| (SSE, Port 8090)|  |
  |  -> Cron 03:00     |  |  | (FastAPI, 8080)|   +----------------+   |
  |  -> full_backup_*  |  |  +-------+--------+                        |
  |     .sh laeuft     |  |          |                                 |
  +---------+----------+  |          v                                 |
            | rsync        |   hosts.yml + generated/                 |
            +--------------->  /mnt/highfishNAS25/Sicherung/<HOST_NAME>|
                         |          ^                                  |
                         |  +-------+--------+                         |
                         |  | filebrowser    |  (optional, Port 4455)  |
                         |  +----------------+                         |
                         +--------------------------------------------+
```

## Quickstart -- Docker Compose (CLI)

```bash
git clone https://github.com/jbkunama1/hAI.BackupServer.git
cd hAI.BackupServer
cp .env.example .env                          # BASIC_AUTH_PASSWORD setzen!
cp app/config/hosts.yml.example app/config/hosts.yml
docker compose --env-file .env up -d --build
```

- Web-UI: `http://192.168.178.26:8080` (Login: Basic Auth aus `.env`)
- Script-API: `http://192.168.178.26:8080/script/<HOST_ID>`
- MCP-Server (SSE): `http://192.168.178.26:8090/sse`
- Filebrowser (optional): `http://192.168.178.26:4455`

## Deployment ueber Portainer (Git-Repository / Stack)

Da das Repo oeffentlich auf GitHub liegt, laesst sich der komplette Stack
direkt in Portainer als **Git-basierter Stack** deployen -- ohne manuelles
`git clone` auf dem Host.

### Schritt-fuer-Schritt

1. In Portainer: **Stacks -> Add stack**.
2. **Name**: z.B. `hai-backupserver`.
3. **Build method**: `Repository` auswaehlen (nicht "Web editor"/"Upload").
4. **Repository URL**: `https://github.com/jbkunama1/hAI.BackupServer`
5. **Repository reference**: `refs/heads/main`
6. **Compose path**: `docker-compose.yml`
7. **Authentication**: da das Repo public ist, kein Token noetig. (Falls du
   es spaeter auf privat stellst: "Authentication" aktivieren, GitHub-Username
   + Personal Access Token mit `repo`-Scope hinterlegen.)
8. **Environment variables** (unten im Formular, ersetzt die lokale `.env`):

   | Name                  | Beispielwert                | Pflicht |
   |------------------------|------------------------------|---------|
   | `BASIC_AUTH_USER`      | `admin`                      | nein (Default: `admin`) |
   | `BASIC_AUTH_PASSWORD`  | `<dein-starkes-Passwort>`    | **ja**  |
   | `ORCHESTRATOR_HOST`    | `192.168.178.26`             | nein (Default gesetzt) |
   | `CRON_SCHEDULE`        | `0 3 * * *`                  | nein (Default gesetzt) |

   Ohne `BASIC_AUTH_PASSWORD` startet `backup-orchestrator` **nicht**
   (fail-closed, siehe Abschnitt "Sicherheit").
9. Optional: **GitOps updates** aktivieren, wenn Portainer bei jedem Push auf
   `main` automatisch neu deployen soll (Webhook oder Polling-Intervall).
10. **Deploy the stack** klicken.

Nach dem Deployment erscheinen drei Container: `backup-orchestrator`,
`backup-mcp`, `filebrowser`.

### Wichtiger Hinweis zu Bind-Mounts bei Git-Stacks

`docker-compose.yml` bindet `./app/config` und `./app/templates` relativ zum
Stack-Verzeichnis ein. Bei einem **Git-basierten** Portainer-Stack liegt
dieses Verzeichnis unter `/data/compose/<stack-id>/` auf dem Docker-Host --
das ist unkritisch, **solange der Stack nicht geloescht wird** (Redeploys /
GitOps-Updates ueberschreiben nur die Dateien aus dem Repo, nicht deine
lokal angelegte `hosts.yml`, da diese in `.gitignore` steht und beim Git-Pull
nicht ueberschrieben wird). Empfehlung: nach dem ersten Deploy einmalig per
Portainer-Konsole oder SSH pruefen, dass `app/config/hosts.yml` im
Stack-Verzeichnis existiert (wird beim ersten Start automatisch aus
`hosts.yml.example` kopiert, siehe `app/main.py::_ensure_config`).

### Umgebungsvariablen -- vollstaendige Uebersicht

| Variable                | Service               | Default                            | Beschreibung                                       |
|--------------------------|------------------------|--------------------------------------|-------------------------------------------------------|
| `BASIC_AUTH_USER`        | backup-orchestrator, backup-mcp | `admin`                    | Benutzername fuer HTTP Basic Auth                     |
| `BASIC_AUTH_PASSWORD`    | backup-orchestrator, backup-mcp | *(keiner, Pflicht)*        | Passwort fuer HTTP Basic Auth -- Server startet ohne dieses nicht nutzbar |
| `ORCHESTRATOR_HOST`      | backup-orchestrator    | `192.168.178.26`                    | Wird in generierten Bootstrap-/Backup-Scripten sowie der Web-UI verwendet |
| `CRON_SCHEDULE`          | backup-orchestrator    | `0 3 * * *`                          | Cron-Ausdruck, der in generierte Bootstrap-Scripte eingebettet wird |
| `GENERATED_DIR`          | backup-orchestrator    | `/app/generated`                     | Zielverzeichnis fuer generierte Host-Scripte innerhalb des Containers |
| `BACKUP_API_BASE_URL`    | backup-mcp             | `http://backup-orchestrator:8080`   | Interne Docker-Netzwerk-Adresse der REST-API           |
| `BACKUP_API_USER`        | backup-mcp             | `admin`                              | Muss mit `BASIC_AUTH_USER` von backup-orchestrator uebereinstimmen |
| `BACKUP_API_PASSWORD`    | backup-mcp             | *(keiner, Pflicht)*                  | Muss mit `BASIC_AUTH_PASSWORD` von backup-orchestrator uebereinstimmen |
| `BACKUP_API_TIMEOUT`     | backup-mcp             | `15`                                  | Timeout in Sekunden pro API-Call                       |
| `TZ`                     | alle Services          | `Europe/Berlin`                      | Zeitzone fuer Logs/Cron-Zeitstempel                    |

## Neuen Host anbinden

1. In der Web-UI (`/hosts/new`) Host anlegen: Hostname, Host-ID, NAS-Mount-Pfad, Container
   (inkl. Volume-Pfade), optional DB-Container.
2. Auf dem neuen Server einmalig ausfuehren:

   ```bash
   curl -fsSL -u "admin:<PASSWORT>" \
     http://192.168.178.26:8080/bootstrap/<HOST_ID> -o bootstrap.sh
   chmod +x bootstrap.sh
   sudo ./bootstrap.sh
   ```

3. Fertig -- der Host sichert ab sofort taeglich um 03:00 Uhr auf das SMB-Share.

## Sicherheit

Alle Endpunkte (Web-UI, Script-/Bootstrap-Auslieferung, JSON-API) sind per
**HTTP Basic Auth** geschuetzt (`BASIC_AUTH_USER`/`BASIC_AUTH_PASSWORD`, per
`.env` oder Portainer-Stack-Umgebungsvariablen gesetzt). Ohne gesetztes
Passwort startet der Server fail-closed (HTTP 500). Details siehe
`docs/ARCHITECTURE.md`.

## Verzeichnisstruktur

```
hAI.BackupServer/
├── app/
│   ├── main.py                     # FastAPI-App (Web-UI + API, Basic Auth)
│   ├── script_generator.py         # Template-Engine
│   ├── models.py                   # Host-/Container-Datenmodelle
│   ├── config/hosts.yml.example
│   ├── templates/
│   │   ├── full_backup_template.sh.j2
│   │   ├── bootstrap_template.sh.j2
│   │   ├── dashboard.html
│   │   ├── host_form.html
│   │   └── host_detail.html
│   └── static/style.css
├── mcp_server/                     # Eigener MCP-Server (SSE)
│   ├── server.py
│   ├── requirements.txt
│   ├── Dockerfile
│   └── README.md
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── .env.example
├── docs/ARCHITECTURE.md
├── docs/ROLLOUT.md
├── docs/mcp_integration.md
└── LICENSE
```

## Lizenz

MIT, siehe `LICENSE`. Keine Gewaehrleistung fuer Datensicherheit -- immer Testlauf und
Restore-Test vor produktivem Einsatz durchfuehren (siehe `RESTORE.md` im
[hAI.FullBackupScript](https://github.com/jbkunama1/hAI.FullBackupScript) Repo).
