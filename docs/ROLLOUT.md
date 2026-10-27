# Rollout-Leitfaden

## 1. Zentrale bereitstellen

`.env` aus `.env.example` anlegen (mindestens `BASIC_AUTH_PASSWORD`), externes Netzwerk sicherstellen, Images ziehen:

```bash
docker network inspect highfishNetwork >/dev/null 2>&1 || docker network create highfishNetwork
docker compose --env-file .env pull
docker compose --env-file .env up -d
```

Portainer: Git-Stack (`refs/heads/main`, `docker-compose.yml`), Variablen als Stack-Umgebung, danach **Pull and redeploy** mit aktivierter Image-Aktualisierung. `./app/config` muss auf dem Docker-Host bestehen bleiben (enthält `hosts.yml` und die Datenbank) – den Stack nicht löschen, ohne vorher zu sichern.

## 2. Backup-Ziel auf jedem Client prüfen

```bash
findmnt -T /mnt/highfishNAS25/Sicherung   # muss das NAS zeigen, nicht "/"
```

Das Backup bricht absichtlich ab, wenn der Pfad auf dem lokalen Root-Dateisystem liegt. Ein NAS-Mount wird von keinem Script eingerichtet.

## 3. Neuen Host anbinden

**Variante A – Enroll (empfohlen):** `ENROLL_TOKEN` setzen, dann auf dem Host

```bash
curl -fsS http://192.168.178.26:8080/enroll.sh -o enroll.sh && less enroll.sh
sudo ./enroll.sh --dry-run
sudo ./enroll.sh
```

**Variante B – manuell:** Host in der Web-UI anlegen, dann `sudo bash bootstrap.sh --run-now` (Download siehe Host-Detailseite).

Beide installieren `/opt/backup/full_backup_<ID>.sh` und `/etc/cron.d/hai-backup-<ID>` (idempotent) und verwenden ein Host-Token.

## 4. Verifizieren

1. Ersten Lauf manuell starten, `/var/log/backup_<ID>.log` und das Dashboard prüfen.
2. Zieldateien auf dem NAS kontrollieren (Image-Archive, `*_data`, `paths_map.txt`, DB-Dumps).
3. **Restore-Test** in einer getrennten Umgebung durchführen ([Anleitung](https://github.com/jbkunama1/hAI.FullBackupScript/blob/main/docs/RESTORE.md)).

## 5. Änderungen und Entfernen

- Konfiguration ändern: Web-UI → Bearbeiten. Clients übernehmen das Script nach erneutem Download oder bei aktiviertem Auto-Update.
- Host entfernen: Web-UI → Host-Detail → „Aus der Konfiguration entfernen“. Das löscht weder Backups noch den Client-Cronjob (`/etc/cron.d/hai-backup-<ID>` manuell entfernen).

## 6. Migration und Rückfall

- Beim ersten Start vergibt der Server für bestehende Hosts Tokens und importiert `reports.json` (Original bleibt).
- Rückfall: vorherige Image-Tags (`sha-<Commit>`) in der Compose-Datei eintragen. Unveränderte Alt-Hosts bleiben im alten Format. Wurde ein Host aber per Web-UI oder Enroll gespeichert, enthält er das Feld `volume_paths`, das ältere Versionen nicht lesen können – dann die gesicherte `hosts.yml` zurückspielen.
- Vor größeren Updates `app/config/` sichern.
