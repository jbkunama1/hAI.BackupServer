# Rollout-Leitfaden

## Vorbereitung: Basic Auth konfigurieren

Vor dem ersten Start `.env` aus `.env.example` anlegen und ein starkes
Passwort setzen:

```bash
cp .env.example .env
# BASIC_AUTH_USER / BASIC_AUTH_PASSWORD in .env anpassen
docker compose --env-file .env up -d --build
```

Ohne gesetztes `BASIC_AUTH_PASSWORD` startet die Web-UI/API nicht nutzbar
(fail-closed, siehe `docs/ARCHITECTURE.md`).

## Neuen Host anbinden

1. Web-UI oeffnen: `http://192.168.178.26:8080/hosts/new` (Basic-Auth-Login
   mit den Werten aus `.env`).
2. Felder ausfuellen:
   - **Hostname**: z.B. `highfish9`
   - **Host-ID**: kurze eindeutige ID, z.B. `9`
   - **NAS-Mount**: i.d.R. `highfishNAS25`
   - **Container**: eine Zeile pro Container im Format
     `containername;/pfad/zum/volume`
   - **DB-Container**: eine Zeile pro DB-Container im Format
     `db_containername;db_user`
3. Speichern -> Script wird sofort generiert.
4. Auf dem neuen Host einmalig:

   ```bash
   curl -fsSL -u "admin:<PASSWORT>" \
     http://192.168.178.26:8080/bootstrap/9 -o bootstrap.sh
   chmod +x bootstrap.sh
   sudo ./bootstrap.sh
   ```

5. Der Host fuehrt beim Bootstrap direkt einen Testlauf aus und richtet
   anschliessend den taeglichen Cronjob (Standard: 03:00 Uhr) ein.

## Bestehenden Host aendern (z.B. neuer Container)

1. In der Web-UI: `Hosts -> Bearbeiten`, Container-Liste ergaenzen, speichern.
2. Das Script auf dem Host aktualisiert sich **nicht automatisch** -- entweder:
   - erneut `curl -u "admin:<PASSWORT>" http://192.168.178.26:8080/script/<HOST_ID>
     -o /opt/backup/full_backup_<HOST_ID>.sh` ausfuehren, oder
   - ueber das MCP-Tool `regenerate_backup_script` per Agent anstossen
     (siehe `mcp_server/README.md`).

## Host entfernen

Aktuell ueber direktes Bearbeiten von `app/config/hosts.yml` (Eintrag
loeschen) plus Neustart des Containers. Ein Loesch-Button in der Web-UI ist als
Erweiterung vorgesehen (Issue anlegen).
