# Telegram-Bot

## Einrichtung

1. Bei [@BotFather](https://t.me/BotFather) `/newbot` ausführen und das Token **nur** in `.env` bzw. den Portainer-Stack-Variablen eintragen – nicht in Chats, Tickets oder Commits.
2. Eigene numerische Nutzer-ID ermitteln (z. B. über @userinfobot) und als `TELEGRAM_ALLOWED_USER_IDS` eintragen (mehrere kommagetrennt).
3. `COMPOSE_PROFILES=telegram` setzen und Stack aktualisieren (oder `docker compose --profile telegram up -d`).
4. Dem Bot im **Privatchat** `/admin` senden.

Ohne Token oder ohne erlaubte IDs bleibt der Bot inaktiv (Default-Deny). Zugriff haben ausschließlich die erlaubten Nutzer im Privatchat – für Befehle **und** Buttons.

## Funktionen

| Menü | Funktion |
|---|---|
| 📊 Status / 🖥️ Hosts | Zustand aller Hosts, Details, Verlauf |
| 🔄 Script neu generieren | mit Bestätigung, im Audit-Log |
| ⏸️ Monitoring pausieren/fortsetzen | mit Bestätigung, im Audit-Log |
| 📰 Digest-Vorschau | sofortige Ansicht (setzt den Tagesversand nicht zurück) |
| 🩺 Health | Erreichbarkeit des Orchestrators |

Nicht enthalten: „Backup jetzt starten“ (würde Fernausführung auf Clients erfordern) sowie Passwörter oder Scripte im Chat.

## Benachrichtigungen

- **Fehler** werden sofort gesendet, je Lauf genau einmal. Zustellprobleme werden wiederholt, ohne Duplikate.
- **Überfällige Hosts** werden einmal je Vorfall gemeldet.
- **Tagesdigest** (Standard 08:00 `Europe/Berlin`, `DIGEST_TIME`/`DIGEST_TZ`): Zähler, Handlungsbedarf, erfolgreiche Hosts und Hosts ohne Meldung. Nach einem Neustart wird ein verpasster Digest einmal nachgeholt.
- Ist der Orchestrator nicht erreichbar, meldet der Bot das ausdrücklich als Serverproblem – nicht als Backup-Fehler.

Ein Ausfall des Bots beeinträchtigt weder Backups noch die Annahme von Reports.
