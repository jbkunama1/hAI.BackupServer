# Architektur hAI.BackupServer

## Ziel

Zentrales Backup-Control-Center: Der Orchestrator verwaltet Hosts, erzeugt pro Host ein Backup-Script
(Basis: [hAI.FullBackupScript](https://github.com/jbkunama1/hAI.FullBackupScript)) und sammelt Ergebnis-Reports.
Die Sicherung selbst läuft **auf dem jeweiligen Host** und schreibt auf ein dort gemountetes NAS.

## Komponenten

| Komponente | Container | Zweck |
|---|---|---|
| backup-orchestrator | `backup-orchestrator` | Web-UI mit Adminmenü, Script-/Bootstrap-/Enroll-Auslieferung, Admin-API, Report-Annahme (SQLite) |
| backup-mcp | `backup-mcp` | MCP-Server (SSE), kapselt die Admin-API als Tools |
| backup-telegram (optional) | `backup-telegram` | Admin-Bot (Long-Polling), Sofort-Fehlermeldungen, Tagesdigest |
| filebrowser (optional) | `filebrowser` | Web-Dateimanager für das Backup-Ziel |

## Zugriffsmodell (drei getrennte Berechtigungen)

| Berechtigung | Mittel | Darf |
|---|---|---|
| Admin | HTTP Basic Auth | Web-UI, Verwaltungs-API, Bootstrap-Download |
| Host | Header `X-Host-Token` (pro Host) | Nur eigenes Script abrufen und eigene Reports senden |
| Enrollment | Header `X-Enroll-Token` | Nur `POST /api/enroll`; ohne `ENROLL_TOKEN` deaktiviert (fail-closed) |

Clients erhalten **nie** das Admin-Passwort. Alte, bereits installierte Scripte mit Admin-Zugang funktionieren weiter,
sollten aber per erneutem Bootstrap/Enroll auf Host-Token umgestellt werden.

## Datenhaltung

- `app/config/hosts.yml` – Konfiguration (inkl. Host-Tokens, Klartext; Datei nur für Administratoren lesbar halten). Atomares Schreiben, Sperre gegen parallele Änderungen.
- `app/config/backupserver.db` – SQLite (WAL): Läufe, Fehler-Ereignisse, Audit-Log. Transaktional, parallelsicher.
- Alte `reports.json` wird beim Start einmalig importiert; die Datei bleibt unverändert als Rückfallebene.
- Bot-Zustand (Cursor, Digest-Datum, Dedup) liegt separat im Volume `telegram_data`.

## Ablauf eines Backups

1. Cron startet `full_backup_<ID>.sh` auf dem Host; lokaler Lock verhindert Überlappung.
2. Script meldet `running`, prüft Docker/rsync und den NAS-Mount (kein Fallback auf lokale Platte), sichert Container, Datenpfade, DB-Dumps.
3. Beim Beenden (auch bei Abbruch) sendet ein EXIT-Trap `ok`, `warning` oder `error` mit unverändertem Exit-Code. Nicht zustellbare Reports bleiben in einem lokalen Spool und werden beim nächsten Lauf nachgereicht.
4. Der Orchestrator speichert den Lauf (idempotent über `run_id`) und legt bei Fehlern genau ein Ereignis an. Der Bot holt Ereignisse ab und sendet sie sofort.

## Sicherheitshinweise

- Basic Auth und Host-Tokens laufen über HTTP; im LAN vertretbar, extern HTTPS/VPN vorschalten.
- Web-Formulare sind CSRF-geschützt; mutierende JSON-Endpunkte erwarten `X-Requested-With`.
- Alle Hostnamen, Container, Pfade und Report-Felder werden validiert; Scripte quoten Werte per `shlex.quote`.
- Der Bot hat Default-Deny: nur erlaubte Nutzer-IDs im Privatchat, für Befehle **und** Buttons.
