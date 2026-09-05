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

## Quickstart (auf 192.168.178.26)

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
**HTTP Basic Auth** geschuetzt (`BASIC_AUTH_USER`/`BASIC_AUTH_PASSWORD` in
`.env`). Ohne gesetztes Passwort startet der Server fail-closed (HTTP 500).
Details siehe `docs/ARCHITECTURE.md`.

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
