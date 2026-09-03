# hAI.BackupServer

Zentrales **Backup-Control-Center** fuer heterogene Docker-/Linux-Umgebungen.

Dieses Repo ergaenzt [`hAI.FullBackupScript`](https://github.com/jbkunama1/hAI.FullBackupScript)
um eine Orchestrierungs-Schicht:

- **Web-UI** zur Verwaltung aller Backup-Hosts (Name, Host-ID, NAS-Ziel, Container, Volumes, DB-Dumps).
- **Template-Engine**, die aus `templates/full_backup_template.sh.j2` fuer jeden Host automatisch
  ein fertiges, ausfuehrbares Backup-Script generiert (`full_backup_<HOST_ID>.sh`).
- **REST-API**, ueber die Hosts fertige Scripte abholen koennen (`GET /script/{host_id}`)
  und die sich als Grundlage fuer MCP-Tools/Agenten eignet.
- **Bootstrap-Script**, das auf einem neuen Server einmalig ausgefuehrt wird: laedt das
  generierte Script, macht es ausfuehrbar und traegt den Cronjob ein.
- **Optionaler Filebrowser-Container**, um das SMB-Share (`highfishNAS25`) direkt im
  Browser zu verwalten (Sicherungsdateien ansehen/loeschen/umbenennen).

## Architektur

```
                         +--------------------------------------------+
                         |        192.168.178.26  (SMB-Share-Host)     |
                         |                                            |
  Docker-Host highfish5  |  +---------------+   +----------------+    |
  +-------------------+  |  | backup-        |   | filebrowser    |    |
  | bootstrap.sh       |--+->| orchestrator   |   | (Web-Dateimgr) |    |
  |  -> holt Script    |  |  | (FastAPI+UI)   |   +-------+--------+   |
  |  -> Cron 03:00     |  |  +-------+--------+           |            |
  |  -> full_backup_*  |  |          | generiert           |            |
  |     .sh laeuft     |  |          v                     v            |
  +---------+----------+  |   hosts.yml + generated/   /srv (SMB-Mount) |
            | rsync        |                                            |
            +--------------->  /mnt/highfishNAS25/Sicherung/<HOST_NAME>  |
                         +--------------------------------------------+
```

## Quickstart (auf 192.168.178.26)

```bash
git clone https://github.com/jbkunama1/hAI.BackupServer.git
cd hAI.BackupServer
cp app/config/hosts.yml.example app/config/hosts.yml
# hosts.yml an eigene Umgebung anpassen
docker compose up -d --build
```

- Web-UI: `http://192.168.178.26:8080`
- Script-API: `http://192.168.178.26:8080/script/<HOST_ID>`
- Filebrowser (optional): `http://192.168.178.26:4455`

## Neuen Host anbinden

1. In der Web-UI (`/hosts/new`) Host anlegen: Hostname, Host-ID, NAS-Mount-Pfad, Container
   (inkl. Volume-Pfade), optional DB-Container.
2. Auf dem neuen Server einmalig ausfuehren:

   ```bash
   curl -fsSL http://192.168.178.26:8080/bootstrap/<HOST_ID> -o bootstrap.sh
   chmod +x bootstrap.sh
   sudo ./bootstrap.sh
   ```

3. Fertig -- der Host sichert ab sofort taeglich um 03:00 Uhr auf das SMB-Share.

## Verzeichnisstruktur

```
hAI.BackupServer/
├── app/
│   ├── main.py                     # FastAPI-App (Web-UI + API)
│   ├── script_generator.py         # Template-Engine
│   ├── models.py                   # Host-/Container-Datenmodelle
│   ├── config/
│   │   └── hosts.yml.example       # Beispiel-Konfiguration
│   ├── templates/
│   │   ├── full_backup_template.sh.j2
│   │   ├── bootstrap_template.sh.j2
│   │   ├── dashboard.html
│   │   ├── host_form.html
│   │   └── host_detail.html
│   └── static/style.css
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── docs/ARCHITECTURE.md
├── docs/ROLLOUT.md
├── docs/mcp_integration.md
└── LICENSE
```

## Lizenz

MIT, siehe `LICENSE`. Keine Gewaehrleistung fuer Datensicherheit -- immer Testlauf und
Restore-Test vor produktivem Einsatz durchfuehren (siehe `RESTORE.md` im
[hAI.FullBackupScript](https://github.com/jbkunama1/hAI.FullBackupScript) Repo).
