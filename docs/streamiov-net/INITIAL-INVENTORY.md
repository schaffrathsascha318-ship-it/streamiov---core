# STREAMIOV NET – erste Bestandsaufnahme

**Prüfgrundlage:** öffentlicher Repository-Stand auf `main`, gelesen am 15.11.2026.  
**Status:** statische Quellcode-/Dokumentationsprüfung; keine lokale Ausführung, kein Live-Cloud-Test und kein Produktionszugriff.

## 1. Bereits vorhandene Bausteine

| Baustein | Im Repository belegter Stand | Bedeutung für STREAMIOV NET |
| --- | --- | --- |
| Self-hosted Host | `host/server.py`, `host/README.md` | Python-Standardbibliothek-Host für statische Site, lokale Konten, Forum und Diagnose |
| Konten | `host/auth.py` | SQLite, PBKDF2-HMAC-SHA256, zufällige Sessions; Registrierungs- und Recovery-Grenzen bleiben offen |
| Forum | `host/forum.py` | lokale Community-Grundlage mit Sitzungs- und Same-Origin-Schutz |
| Datenkatalog | `host/data_store.py` | getrennte, read-only SQLite-Katalogdatenbank aus Repository-JSON |
| Systembetrieb | `host/systemd/streamiov-host.service` | Beispiel für einen eigenständigen Linux-Hostdienst, loopback-gebunden hinter einem TLS-Reverse-Proxy |
| KI-Inferenz | `infrastructure/cloudflare/streamiov-ai-worker/` | separater Cloudflare AI Worker; Konfiguration bindet die AI-Laufzeit |
| KI-Agenten | `ai/` | vorhandene CLI, Spezialisten, Queue-/Mission- und Worker-Bausteine |
| Homepage | `dist/streamiov-homepage-worker/wrangler.jsonc` | Assets-only Homepage-Worker; keine Core-API |
| AI-Runner | `.github/workflows/autonomous-development.yml` | geplanter/gepflegter Missionslauf auf GitHub Actions, mit persistentem verschlüsseltem Missionsartefakt |

## 2. Konkrete Lücken aus der vorhandenen Dokumentation

### Self-hosted Host ist noch kein vollständiger Core
Die Host-README beschreibt ausdrücklich, dass:
- die breitere Anwendungs-API nicht verfügbar ist,
- `POST /api/v1/ai/tasks` nur ein authentifizierter Platzhalter ist und `503 ai_execution_not_ready` zurückgibt,
- dieser Endpunkt Aufträge weder speichert noch ausführt,
- Passwort-Wiederherstellung, E-Mail-Verifikation, Kontolöschung und OAuth-Callback fehlen,
- der Host vor öffentlicher Kontonutzung zusätzliche Sicherheits-, Datenschutz- und Betriebsabnahmen benötigt.

### Cloudflare-Core-Quelle ist im geprüften Repository nicht auffindbar
Das Verzeichnis `infrastructure/cloudflare/` enthält auf `main` nur `streamiov-ai-worker/`. Die Homepage-Worker-Konfiguration liegt getrennt unter `dist/streamiov-homepage-worker/` und ist Assets-only. Eine versionierte Core-API-Worker-Implementierung samt Wrangler-Konfiguration ist in diesen geprüften Pfaden nicht vorhanden. Ein separat im Cloudflare-Konto existierender Worker wird damit nicht ausgeschlossen; dessen Quellcode, Bindings und Deployment müssen separat abgeglichen werden.

### Der autonome Runner hängt derzeit an GitHub Actions
Die Workflow-Datei `.github/workflows/autonomous-development.yml` definiert einen Ubuntu-24.04-Runner mit 45-Minuten-Laufzeit und einem 15-Minuten-Zeitplan. Die Missionsdaten werden als verschlüsseltes Workflow-Artefakt wiederhergestellt. Das ist ein brauchbarer Übergang, aber noch keine vollständig eigene Streamiov-Ausführungsinfrastruktur. Für langfristige Unabhängigkeit muss ein portierbarer Streamiov-Scheduler/Runner entstehen, der auf einem unabhängigen Host betrieben werden kann und GitHub nicht als Laufzeitvoraussetzung benötigt.

## 3. Vorhandene Schutzmaßnahmen, die erhalten bleiben müssen

- Der Host bindet standardmäßig an Loopback; Remote-Bindings verlangen TLS-Zertifikat und Schlüssel.
- Die systemd-Beispieldatei nutzt einen eigenen Dienstbenutzer, restriktive Systemd-Sandboxing-Optionen und begrenzte Ressourcen.
- Konten speichern Passwort-Hashes statt Klartextpasswörter; Session-Tokens werden gehasht gespeichert.
- Registrierung ist standardmäßig geschlossen.
- AI-Worker und Homepage sind getrennte Deployments.
- Der AI-Worker verlangt Bearer-Authentifizierung und hält das Modell serverseitig fest.

Diese Schutzmaßnahmen dürfen nicht entfernt werden, nur um Funktionen schneller verfügbar zu machen.

## 4. Empfohlene Reihenfolge ab diesem Ist-Stand

1. **Core-API-Abgleich:** den bereits im Cloudflare-Konto vorhandenen `streamiov-core-api` mit versioniertem Quellcode, Bindings, D1-Schema und Deployment-Historie abgleichen. Keine Secrets auslesen oder anzeigen.
2. **Ein gemeinsamer Core-Vertrag:** Authentifizierung, Rollen/Berechtigungen, API-Versionen, Fehlerformat und Dienststatus vereinheitlichen.
3. **Persistente Aufträge:** den AI-Platzhalter durch eine echte, dauerhaft gespeicherte und wiederaufnehmbare Auftragsverarbeitung ersetzen; vorher Queue, Idempotenz und isolierte Runner festlegen.
4. **Self-hosted Core-Adapter:** den bestehenden Python-Host nicht verwerfen, sondern als portierbaren lokalen/self-hosted Adapter weiterentwickeln und gegen denselben API-Vertrag testen.
5. **Unabhängiger Runner:** GitHub Actions als optionalen CI-Adapter behalten, aber eine eigene Runner-Installation auf einem unabhängigen Server ermöglichen.
6. **Datenportabilität:** Backup/Restore und Host-Migration mit Testdaten nachweisen, bevor Nutzerkonten oder Community-Daten öffentlich erweitert werden.

## 5. Grenzen dieser Prüfung

Diese Bestandsaufnahme liest Repository-Dateien. Sie bestätigt nicht:
- den aktuellen Live-Zustand eines Cloudflare Workers,
- die tatsächliche Konfiguration oder Existenz von D1-/Queue-Bindings im Konto,
- erfolgreiche externe Core-API-Aufrufe,
- den aktuellen Zustand lokaler, nicht synchronisierter Arbeitskopien,
- die erfolgreiche Ausführung des GitHub Actions-Runners.

Dafür sind separate, gezielte Read-only-Prüfungen nötig. Keine Produktionsänderung ist Teil dieses Arbeitsschritts.
