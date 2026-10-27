# Enrollment

`enroll.sh` ist ein universelles Script ohne Zugangsdaten. Es erkennt Container, zeigt sie zur Bestätigung an,
registriert den Host und richtet Script und Cronjob ein.

## Ablauf

1. Serverseitig `ENROLL_TOKEN` setzen (lange Zufallszeichenfolge, `openssl rand -hex 24`); ohne Token ist Enrollment aus.
2. Auf dem Host: Script laden, ansehen, `--dry-run`, dann ausführen. Das Token wird abgefragt oder aus der Umgebungsvariable `ENROLL_TOKEN` gelesen – nicht als Argument übergeben.
3. Das Script erkennt alle Container (auch gestoppte) und deren Bind-/Volume-Verzeichnisse per `docker inspect`.
   Ausgeschlossen werden sensible Pfade (`/`, `/etc`, `/root`, `/proc`, `/sys`, `/dev`, Docker-Socket, Pfade mit „secret“) und Nicht-Verzeichnisse. PostgreSQL-Container werden zusätzlich für `pg_dumpall` vorgeschlagen.
4. Der Server legt den Host an (stabile ID aus Hostname, Identität über Hash der `machine-id`) und liefert ein **Host-Token**.
5. Das Script lädt das Backup-Script, prüft die Syntax (`bash -n`) und installiert `/opt/backup/full_backup_<ID>.sh` (Modus 700) sowie `/etc/cron.d/hai-backup-<ID>`.

## Optionen

`--help`, `--dry-run`, `--yes`, `--host-name NAME`, `--update-config`, `--run-now`

## Wiederholtes Ausführen

Derselbe Host bleibt derselbe Eintrag (gleiche ID, gleiches Token, kein doppelter Cronjob). Manuell angepasste Container-Konfiguration wird **nicht** überschrieben, außer mit `--update-config`.

## Nicht enthalten

- Kein NAS-Mount und keine NAS-Zugangsdaten – der Zielpfad muss bereits gemountet sein.
- Keine Fernsteuerung: Der Server führt keine Befehle auf Clients aus.
