# MCP-Integration (Vorschlag)

hAI.BackupServer stellt bereits eine JSON-API bereit, die sich 1:1 als
Grundlage fuer MCP-Tools eignet (z.B. im hAI.MCP-Server):

| MCP-Tool (Vorschlag)     | Ruft intern auf                              | Zweck                              |
|--------------------------|-----------------------------------------------|-------------------------------------|
| `list_backup_hosts`      | `GET /api/hosts`                              | Alle konfigurierten Hosts auflisten |
| `get_backup_host`        | `GET /api/hosts/{host_id}`                    | Details zu einem Host               |
| `upsert_backup_host`     | `POST /api/hosts`                             | Host anlegen/aktualisieren          |
| `regenerate_backup_script` | `POST /api/hosts/{host_id}/regenerate`      | Script neu generieren               |
| `get_backup_script`      | `GET /script/{host_id}`                       | Aktuelles Bash-Script abrufen        |
| `get_bootstrap_script`   | `GET /bootstrap/{host_id}`                    | Bootstrap-Script fuer neuen Host     |

Damit koennen Agenten z.B. auf Zuruf neue Hosts anlegen ("Lege einen neuen
Backup-Host highfish12 mit Container xyz an") oder pruefen, welche Hosts
aktuell konfiguriert sind, bevor ein neues Server-Deployment ausgerollt wird.
