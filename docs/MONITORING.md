# Monitoring

## Meldungen der Clients

Jeder Lauf sendet zwei Meldungen an `POST /api/hosts/<ID>/report` (Header `X-Host-Token`):

1. `running` beim Start,
2. `ok`, `warning` oder `error` beim Beenden (EXIT-Trap, auch bei Abbruch und vor dem Anlegen von Verzeichnissen).

Felder: `run_id`, `status`, `exit_code`, `duration_seconds`, `size_bytes`, `warnings`, `started_at`, `message`.

- **warning:** z. B. konfigurierter Container nicht gefunden – nie fälschlich „ok“.
- **error:** fehlgeschlagene Sicherung, kein NAS-Mount, Ziel nicht beschreibbar u. a. Der ursprüngliche Exit-Code bleibt erhalten.
- Meldungen laufen per HTTP, nicht über das NAS, und werden bei Ausfall lokal gespoolt (`/var/lib/hai-backup/<ID>/spool`) und nachgereicht. Doppelte Zustellung ist unschädlich (idempotent über `run_id`).
- Ein hart beendeter Prozess (Stromausfall, `kill -9`) sendet keine Abschlussmeldung: Der Lauf bleibt „läuft“ und wird nach `max_run_hours` als **unklar** markiert.

## Zustände

| Zustand | Bedeutung |
|---|---|
| OK / WARNUNG / FEHLER | Ergebnis des letzten Laufs |
| LÄUFT | Lauf aktiv (jünger als `max_run_hours`) |
| ÜBERFÄLLIG | Letzter Lauf älter als Intervall + Karenz, oder seit der Einrichtung (+ Frist) nie eine Meldung |
| KEINE MELDUNG | Neuer Host innerhalb der Einrichtungsfrist – das ist **nicht** „nie gelaufen“ |
| UNKLAR | Lauf gestartet, nie abgeschlossen |
| PAUSIERT | Monitoring bewusst ausgesetzt (Wartung) |

Standardwerte (Einstellungen in der Web-UI): Intervall 24 h, Karenz 4 h, Einrichtungsfrist 30 h, max. Laufzeit 12 h, Historie 200 Läufe je Host. Je Host kann ein eigenes Intervall gesetzt werden.

## Endpunkte (Admin)

| Methode | Pfad | Zweck |
|---|---|---|
| GET | `/api/status` | Abgeleiteter Status aller Hosts |
| GET | `/api/runs?host_id=&limit=` | Laufhistorie |
| GET | `/api/digest?hours=24` | Datengrundlage des Tagesdigest |
| GET | `/api/events?after=<id>` | Fehler-Ereignisse (Bot) |
| GET | `/api/hosts/<ID>/report` | Letzter Lauf |
| GET | `/api/reports` | Letzter Lauf je Host (kompatibel) |
| POST | `/api/hosts/<ID>/pause` | Pausieren/Fortsetzen (Header `X-Requested-With`) |

## Grenzen

- Der Orchestrator sieht nur, was gemeldet wird. Ein Host, der aus ist oder dessen Cron fehlt, fällt erst über „überfällig“ auf.
- „OK“ bedeutet: alle konfigurierten Schritte liefen fehlerfrei – nicht, dass die Konfiguration vollständig ist und nicht, dass ein Restore funktioniert.
- Dateikopien laufender Anwendungen sind nicht automatisch konsistent; für Datenbanken `db_containers` (pg_dumpall) nutzen.
