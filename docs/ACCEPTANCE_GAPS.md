# Streamiov Zentrale Abnahme- und Restliste

Stand: 2026-11-27. Diese Datei ist die zentrale Liste aller verbleibenden Arbeiten und externen Abnahmeblocker. `VERIFIED` bedeutet ausschließlich eine praktisch ausgeführte, reproduzierbare interne Prüfung. `EXTERNAL` bedeutet, dass echte Zugangsdaten, Rechte, Geräte, Plattformfreigaben oderLive-Zustände erforderlich sind und nicht simuliert werden dürfen.

## Gesamtstatus

- **Streamiov Produktstatus:** `INTEGRATED_AND_LOCALLY_VERIFIED`, nicht `RELEASE_READY`.
- **Letzte lokale Gesamtprüfung:** `742` Python-Tests OK, `32/32` Node-Tests OK, `146/146` Engine-Tests OK, `compileall`, `bash -n`, Cloudflare-Konfigurationsverifikation und `git diff --check` OK.
- **Freigabegrund:** alle intern umsetzbaren Funktionen sind integriert und geprüft; die verbleibenden Punkte sind echte externe Zugänge, Rechte, Geräte, Build-Signierung, Plattform-Deployments und Live-Nachweise.

## Zentrale Restliste

| Nr. | Bereich | Status | Verbleibend / Nachweis |
| --- | --- | --- | --- |
| 1 | Installation, Start, Anmeldung, Einrichtung | Intern VERIFIED; EXTERNAL offen | Reproduction im Repository und Host-/Studio-Tests bestanden. Echte installierte Desktop-Builds, OS-spezifische Installer, Signierung, Crash-/Startberichte und eine echte Erstinstallation auf Zielgeräten müssen extern abgenommen werden. |
| 2 | Studio: Szenen, Quellen, Regie | Intern VERIFIED; Manual EXTERNAL | Szenen-, Quellen-, IPC-, Event- und UI-Verträge sind integriert und automatisiert geprüft. Eine echte Benutzerbedienung mit Renderer, Fenstern und Audio-/Videogeräten bleibt extern. |
| 3 | TikTok-Ausgang getrennt | Intern VERIFIED; EXTERNAL offen | OAuth-Vertrag, CSRF/PKCE, Token-Verschlüsselung, scopes und getrennte Konfiguration sind implementiert und getestet. Echtes TikTok-Konto, Konsolen-Freigaben, Redirect-URI, Live-Rechte und ein echter Live-Stream müssen extern geprüft werden. |
| 4 | Twitch-Ausgang getrennt | Intern VERIFIED; EXTERNAL offen | OAuth-/Helix-/Revocation-/Rotation-Pfad und getrennte Konfiguration sind implementiert und getestet. Echte Twitch-Entwicklungsanwendung, Token, Stream-Key und Live-Stream müssen extern geprüft werden. |
| 5 | Audio-Mixer: Mikrofon, Musik, Spielsound, Alerts, TTS | Intern VERIFIED; Gerätetest offen | Mixer-, Validierungs-, Katalog- und TTS-Verträge sind getestet. Echte Audio-Geräte, Latenz, Lautstärke, Alerts und TTS-Ausgabe auf Zielsystemen bleiben extern. |
| 6 | Wunschbox-Aufträge annehmen und bearbeiten | VERIFIED | Persistenter Host-Store, API, Studio-UI, Ledger, Status-/Result-Events und Gaming-Handoff sind real mit lokalen Requests und echten Dateien getestet. Echter Plattform-Chat und echte Zuschauerinteraktion bleiben extern. |
| 7 | AI Chief und alle 28 Rollen | Intern VERIFIED; Modell EXTERNAL | Registry, Planner, Orchestrator, Queue, Workspaces, Marker, Rollen-Lifecycle und Final Verification sind mit allen 28 Rollen ausgeführt. Echte Modellverbindung, Quoten und ein langer Produktionslauf bleiben extern. |
| 8 | Eigene Spiele starten und vollständig spielen | Intern VERIFIED; Manual EXTERNAL | Spiel-/Engine-Verträge, Preflight und native Spiele sind automatisiert geprüft. Ein vollständiger manueller Playthrough auf Zielgeräten bleibt extern. |
| 9 | Externe Spielaufträge bis Test-Build | Intern VERIFIED; Release EXTERNAL | Intake, Rückfragen, isolierte Workspaces, deterministischer Test-Build, Verify, Tamper-Erkennung und Rechte-/Claim-Sperren sind ausgeführt. Echte Rechtenachweise, Kundenfreigaben und Produktionspublikation bleiben gesperrt. |
| 10 | Homepage, Downloads, Installationen | Intern VERIFIED; Live EXTERNAL | Konfigurationsverifikation prüft Links, lokale Dateien, GitHub-Assets, Signaturen und Prüfsummen. Ein Live-Deployment und ein echter Download-/Installationslauf auf Zielsystemen bleiben extern. |
| 11 | Updates und Daten-/Backups | Intern VERIFIED; Release EXTERNAL | Update-Manifest, Backup-/Restore-, Verschlüsselungs- und Retention-Pfade sind getestet. Echte veröffentlichte Update-Artefakte und echte Wiederherstellung nach einem Live-Update bleiben extern. |
| 12 | Fehler simulieren, erkennen, beheben, Betrieb wiederherstellen | Intern VERIFIED | Terminal Failures hängen abhängige Tasks korrekt auf `failed`; Workspace-Konflikte blockieren Integration; Ledger-/API-Fehler werden abgefangen; Retry-/Recovery-Pfade sind automatisiert geprüft. Echte Produktionsincidents bleiben extern. |
| 13 | Forum-Aufbewahrung | Intern VERIFIED; Automatisierung offen | Richtlinie, Dry-Run und idempotente Anwendung sind getestet. Ein Zeitplan-/Cron-Trigger und eine rechtliche Freigabe fehlen. |
| 14 | E-Mail-Benachrichtigungen | OFFEN | Es existiert kein versandfähiger, freigegebener Mailprovider. Keine Adresse, kein Template und kein Opt-in-/Opt-out-Vertrag dürfen erfunden werden. |
| 15 | Verteilte Rate Limiter | OFFEN | Der persistente lokale Limiter ist geprüft; ein gemeinsamer Limiter über mehrere Hosts/getrennte Datenverzeichnisse ist nicht implementiert. |
| 16 | Release-Builds und Artefakte | BLOCKED | Windows-, macOS-, iOS-, Linux-, ChromeOS-Installer und signierte Artefakte wurden nicht erzeugt. Signierungsschlüssel, Ziel-OS, Signaturzertifikate und Installationsmedien müssen bereitgestellt werden. |
| 17 | Veröffentlichung / Live-Prüfung | BLOCKED | Keine echten Deployment-Credentials, kein Owner-bestätigter Produktionslauf, kein veröffentlichtes Release und keine Live-Downloadprüfung vorhanden. Nicht simulieren. |
| 18 | Rechtsprüfung / Kundenprojekte | BLOCKED | Keine externen Rechtenachweise, Kundenfreigaben oder Plattform-Genehmigungen vorhanden. Kein ungeprüftes Kundenprojekt veröffentlichen. |

## Nächste automatische Entwicklungsmission

`M19`: verbleibende intern umsetzbare Lücken Nr. 13–15 priorisieren und implementieren, danach erneute Gesamtverifikation. Externe PunkteNr. 16–18 bleiben solange `BLOCKED`, bis echte Freigaben, Zugangsdaten und Zielgeräte bereitstehen.
