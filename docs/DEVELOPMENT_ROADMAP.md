# STREAMIOV – Gesamtentwicklungsplan

**Leitbild:** Von Streamern für Streamer. Dauerhaft kostenlos, ohne Abos, Pro-Stufen oder künstliche Bezahlschranken. STREAMIOV wird als eigenständige Creator- und Streaming-Plattform entwickelt – nicht als OBS-Oberfläche.

Dieser Plan ist die verbindliche Arbeitsreihenfolge für Core, KI, Studio, Spiele, Geschenke, Plattformanbindung, Cloud, Downloads und Veröffentlichung. Bestehende funktionierende Komponenten werden zuerst geprüft und weiterverwendet, statt sie unnötig neu zu bauen.

## Arbeitsregeln und Definition of Done

1. Jede Aufgabe wird zuerst im bestehenden Repository, in Issues, Tests und Workflows geprüft.
2. Kleine, sichere Änderungen werden direkt umgesetzt; größere Änderungen erhalten einen eigenen Branch und Pull Request.
3. Jede Änderung erhält passende automatisierte Tests. Fehler werden behoben und die betroffenen Tests erneut ausgeführt.
4. CI-Erfolg ist kein Beweis für Hardware-, Live-, Produktions- oder Nutzerprüfung. Diese Nachweise werden getrennt dokumentiert.
5. Nichts gilt als fertig, nur weil Code vorhanden ist. Fertig bedeutet: Akzeptanzkriterien erfüllt, Tests bestanden, Dokumentation aktualisiert und – wo nötig – echte Laufzeitprüfung durchgeführt.
6. Keine erfundenen Erfolgs- oder Veröffentlichungsangaben. Statuswerte: geplant, in Arbeit, implementiert, CI-geprüft, Laufzeit-geprüft, produktionsgeprüft, veröffentlicht.
7. Keine unkontrollierten Änderungen an Zugangsdaten, produktiven Daten, Zahlungsflüssen oder bestehenden Creator-Verbindungen.
8. Chromebook bleibt Entwicklungsumgebung, nicht Produktionshost. Cloud-Dienste und Produktionsinfrastruktur werden unabhängig davon geplant und betrieben.
9. Launch-Scope für externe Streamingplattformen: TikTok LIVE. Keine zusätzlichen Plattformadapter als Ablenkung vom Launch.
10. STREAMIOV bleibt im Produktziel kostenlos. Drittanbieter-, Infrastruktur-, Zahlungs- und gesetzliche Kosten müssen transparent behandelt werden, ohne daraus künstliche Nutzerstufen zu machen.

## Phase 0 – Bestandsaufnahme und Arbeitssteuerung

- Alle GitHub-Issues und Pull Requests vollständig inventarisieren, einschließlich geschlossener, offener und verknüpfter Einträge.
- Nummern, Titel, Status, Abhängigkeiten, Branches, Commits, CI-Läufe und vorhandene Implementierungen abgleichen.
- Issue #3 als übergreifenden Fertigstellungs-Tracker pflegen.
- Doppelte Aufgaben zusammenführen oder eindeutig verknüpfen; keine Historie oder offenen Anforderungen stillschweigend verwerfen.
- Fehlende Arbeit als konkrete Issues mit Akzeptanzkriterien, Tests und Abhängigkeiten erfassen.
- Für jeden Bereich eine nachvollziehbare Statusübersicht pflegen.

**Abnahme:** Vollständige Aufgabenliste und ein belastbarer Ist-Stand; keine Behauptung, eine Nummernliste sei vollständig, solange nicht alle Ergebnisseiten geprüft wurden.

## Phase 1 – STREAMIOV Core und Plattformfundament

- Core-API, Authentifizierung, Berechtigungen, Konfiguration und Fehlerbehandlung prüfen und vervollständigen.
- Gemeinsame Event- und Nachrichtenverträge für Studio, Spiele, Geschenke und KI definieren.
- Sichere lokale und entfernte Schnittstellen, Schema-Versionierung, Rate Limits und Audit-Protokolle etablieren.
- Konfiguration und Secrets strikt von Quellcode und Client-Paketen trennen.
- Health Checks, Metriken, Logs, Backups und Wiederherstellungsabläufe aufbauen.
- Cloudflare-Deployments, D1/R2 oder andere bereits vorgesehene Cloudflare-Dienste nur anhand realer Anforderungen und Kosten-/Limitprüfungen integrieren.
- Produktionshost und Cloud-Speicher unabhängig vom Chromebook bereitstellen und verifizieren.

**Abnahme:** reproduzierbare Tests, dokumentierte Deployments, Monitoring, Backup-/Restore-Test und bestätigte Produktions-Healthchecks.

## Phase 2 – Gesamte STREAMIOV-KI

Die KI ist ein zentrales Produkt- und Entwicklungsfundament, nicht nur ein Chatfenster.

### 2.1 Core-KI und Orchestrierung
- Zentrale Aufgabenannahme, Planung, Priorisierung und Zuweisung an Spezialisten.
- Aufgabenstatus, Abhängigkeiten, Zeitlimits, Budgets, Wiederholungsgrenzen und Abbruchbedingungen.
- Nachvollziehbare Entscheidungs- und Ausführungsprotokolle.
- Keine unbeschränkte Shell-, Datei-, Netzwerk- oder Produktionsberechtigung.

### 2.2 Spezialisten
- Code-KI: Implementierung, Refactoring und Dokumentation.
- Game-KI: Spielkonzepte, Spielcode, Balancing und technische Prüfung.
- Design-KI: UI, Szenen, Overlays, Animationen und visuelle Assets.
- Studio-KI: Studio-Module, Szenenabläufe und Geräteintegration.
- Gift-KI: Geschenkideen, Assets, Effekte und Event-Zuordnung.
- Test-KI: Unit-, Integrations-, Regression-, Sicherheits- und Smoke-Tests.
- Repair-KI: Fehlerdiagnose, reproduzierbare Korrekturen und erneute Tests.
- Integration-KI: API-Verträge und Modulkompatibilität.
- Server-/Ops-KI: Infrastrukturzustand, Logs, Deployments und Warnmeldungen.
- General-KI: Anfragen klassifizieren und an zuständige Spezialisten weiterleiten.

### 2.3 Sichere Ausführung und Qualität
- Rollen- und Pfadgrenzen pro Spezialist technisch erzwingen.
- Änderungen zunächst in isolierten Arbeitsbereichen/Branches erstellen.
- Tests und statische Prüfungen vor Merge ausführen.
- KI-generierte Ergebnisse auf Geheimnisse, unsichere Abhängigkeiten, Lizenz- und Sicherheitsrisiken prüfen.
- Menschliche Freigabe nur dort verlangen, wo externe, irreversible oder rechtlich/finanziell relevante Aktionen betroffen sind.
- Keine vorgetäuschte Autonomie: nicht implementierte Tools und nicht erreichbare Modelle klar als nicht verfügbar melden.

### 2.4 Lernen und Verbesserung
- Fehler, Testergebnisse und Nutzerfeedback strukturiert auswerten.
- Wiederkehrende Fehler in Regressionstests überführen.
- Wissensbasis und Prompt-/Regelversionen nachvollziehbar versionieren.
- Modellqualität mit reproduzierbaren Aufgaben messen; keine automatische Selbständerung produktiver Regeln ohne Tests.

**Abnahme:** Ende-zu-Ende-Aufgabenlauf mit echter Modellverbindung, Spezialistenzuweisung, isolierter Änderung, Testausführung, Fehlerbehandlung und nachvollziehbarem Ergebnis. Lokale Mock-Tests allein reichen nicht.

## Phase 3 – Eigenständiges STREAMIOV Studio

- Electron-Desktop-Studio als eigenständige Regie; keine OBS-Abhängigkeit.
- Szenenverwaltung, Vorschau/Programm-Ausgabe, Übergänge, Quellen und Ebenen.
- Eigene Medienpipeline mit Audio-Mischung, Video-Komposition und Encoder-Integration.
- Kamera-, Mikrofon-, Audio-, Capture- und Geräteerkennung mit verständlicher Diagnose.
- Alerts, Chat, Musik, TTS, Events, Geschenke und Spiele als integrierte Module.
- TikTok-LIVE-Anbindung ausschließlich über offiziell unterstützte und freigegebene Schnittstellen.
- Verlässliche Wiederverbindung, Fehlerzustände, Bandbreiten-/Encoderprofile und Stream-Status.
- Plattformübergreifende Pakete getrennt für Windows x64/ARM64, Linux x64/ARM64 und ChromeOS-Ziele erstellen; nur tatsächlich getestete Targets als unterstützt bezeichnen.

**Abnahme:** Studio startet reproduzierbar, Geräte werden real erkannt, Vorschau und Programmausgabe funktionieren, Audio/Video-Pipeline ist nachgewiesen und ein autorisierter Teststream wurde erfolgreich geprüft. CI-Builds allein sind keine Live-Verifikation.

## Phase 4 – Spielebibliothek und unabhängige Veröffentlichungen

- Spiele unabhängig vom Fertigstellungsstand des Studios entwickeln.
- Einheitliches Manifest, Versionierung, Eingabe-/Event-Schnittstelle, Ressourcenlimits und isolierte Laufzeit.
- Prototypen Neon Relay, Echo Grid und Pulse Defender technisch und spielerisch prüfen und verbessern.
- Neue Spiele mit eigenständigem Konzept, zeitgemäßer Grafik, Wiederspielwert und Community-/Koop-Potenzial erstellen.
- Automatisierte Tests plus echte Gameplay-Prüfung durchführen.
- Release-Pipeline mit Version, Änderungsprotokoll, Paketen, Prüfsummen und Rückrollmöglichkeit aufbauen.

**Abnahme:** Jedes Spiel ist separat installierbar/startbar, spielbar verifiziert, getestet, dokumentiert und einzeln veröffentlicht. Entwicklungsprototypen werden nicht als Releases ausgegeben.

## Phase 5 – STREAMIOV-Geschenke und Eventsystem

- Eigene Geschenk-Galerie mit originalen STREAMIOV-Assets, Animationen und Sounds.
- Einheitlicher Eventbus für Geschenk-, Szenen-, Spiel- und Studioaktionen.
- Cross-Plattform-Zustellung der STREAMIOV-eigenen Geschenke; Aktionen werden nur innerhalb STREAMIOV ausgeführt.
- Ledger für Transaktionen, Zuordnung, Rückerstattungen, Gebühren und Auszahlungen.
- Zielmodell: 100 % des vorgesehenen Geschenk-Erlöses für den jeweiligen Streamer und 0 % STREAMIOV-Provision; Zahlungsanbietergebühren, Rückbuchungen, Steuern und rechtliche Pflichten transparent und korrekt ausweisen.
- TikTok-native Geschenke klar von STREAMIOV-eigenen Geschenken trennen.
- Keine Zahlungs- oder Auszahlungsfunktion als fertig bezeichnen, bevor Anbieterintegration, Sicherheitsprüfung und End-to-End-Test abgeschlossen sind.

**Abnahme:** Testtransaktion vom Kauf bis zur korrekten Zuordnung und Auszahlung im Sandbox-/Testmodus; nachvollziehbare Buchungen und geprüfte Fehler-/Rückerstattungsfälle.

## Phase 6 – TikTok LIVE und Creator-Verbindungen

- Vorhandene OAuth-Implementierung und Creator-Sitzungen zuerst inventarisieren und testen.
- Bestehende Client-Konfiguration, Redirect-URI, Scopes, Callback-Fluss und gespeicherte Tokens nicht als Routine-Refactoring austauschen.
- Keine Tokens löschen, überschreiben, migrieren oder Verbindungen invalidieren, ohne nachgewiesene technische Notwendigkeit und einen getesteten Erhaltungsplan.
- Keine erzwungene Neuautorisierung als Nebenwirkung von CI, Bereinigung oder Refactoring.
- Offizielle Berechtigungen und tatsächliche Verfügbarkeit von LIVE-, Chat- und Gift-Events getrennt verifizieren; keine nicht genehmigten oder inoffiziellen Endpunkte verwenden.
- Secrets serverseitig halten; bestehende Sicherheitsrisiken dokumentieren und eine kompatible Behebung planen, ohne bestehende Creator-Verbindungen leichtfertig zu unterbrechen.

**Abnahme:** Bestehende Verbindung bleibt erhalten; Status-, Refresh- und Fehlerfälle sind getestet; nur tatsächlich gewährte TikTok-Berechtigungen werden als verfügbar dargestellt.

## Phase 7 – Homepage, Downloads und Installationen

- Homepage https://streamiov.pages.dev/ als Informations- und Download-Einstieg pflegen, nicht als Studio-Host ausgeben.
- Vollständige, reproduzierbare Download-Pakete für unterstützte Plattformen bauen.
- Installationsablauf, Voraussetzungen, Updates, Deinstallation und Fehlerdiagnose dokumentieren.
- Artefakte signieren, Prüfsummen veröffentlichen und Download-Links automatisiert prüfen.
- Mobile/PWA-Funktionen separat von nativen Desktop-Builds kennzeichnen.
- Keine Download-Schaltfläche auf nicht vorhandene oder unvollständige Pakete zeigen.

**Abnahme:** Frischer Download, Integritätsprüfung, Installation, Start, Update und Deinstallation auf realen unterstützten Zielsystemen getestet.

## Phase 8 – Sicherheit, Zuverlässigkeit und Betrieb

- Dependency- und Secret-Scanning in CI.
- Rechtearme Tokens, sichere Speicherung, Verschlüsselung und Rotation nur mit kompatiblem Erhaltungsplan.
- Bedrohungsmodell für KI-Agenten, Dateioperationen, Plugins, Gerätezugriffe, Uploads und Zahlungsflüsse.
- Backups, Restore-Tests, Rate Limits, Missbrauchsschutz und Incident-Protokoll.
- Abhängigkeiten, Lizenzen und Software-Supply-Chain dokumentieren.
- Keine automatischen produktiven oder finanziellen Aktionen ohne passende Berechtigung und Kontrollmechanismen.

**Abnahme:** Sicherheits- und Wiederherstellungstests bestanden; offene Risiken sichtbar dokumentiert und priorisiert.

## Phase 9 – Release und laufende Verbesserung

- Release-Kandidaten für Core, Studio, Spiele und Homepage getrennt bauen und testen.
- Plattformmatrix mit Build-, CI-, Laufzeit- und Hardwarestatus pflegen.
- Release Notes, bekannte Einschränkungen, Prüfsummen und Support-/Rollback-Informationen veröffentlichen.
- Erst nach erfüllten Release-Kriterien veröffentlichen.
- Nach Veröffentlichung Monitoring, Fehlerberichte und Regressionstests fortführen.

## Priorisierung und Arbeitsrhythmus

1. Zuerst vollständige GitHub-Inventur und offene CI-/PR-Blocker.
2. Parallel sichere KI-, Core-, Spiele- und CI-Arbeiten vorantreiben.
3. Danach die Studio-Medienpipeline und die tatsächlich verfügbaren TikTok-Funktionen nachweisen.
4. Geschenk-Transaktions- und Auszahlungskette mit Testanbieter vervollständigen.
5. Downloads, Signierung, Plattformtests und getrennte Releases abschließen.
6. Jede abgeschlossene Teilfunktion sofort separat veröffentlichen, sobald ihre eigenen Kriterien erfüllt sind; nicht auf die gesamte Plattform warten.

## Wichtige Grenzen

- Externe Konten, TikTok-Freigaben, Zahlungsanbieter, reale Hardware und produktive Deployments können nur mit den jeweils verfügbaren Zugängen und Berechtigungen geprüft werden.
- Ein erfolgreicher GitHub-Workflow beweist nur die im Workflow ausgeführten Prüfungen.
- Keine Behauptung von „fertig“, „live“ oder „veröffentlicht“ ohne entsprechenden Nachweis.
- Bestehende TikTok-Verbindungen bleiben bei allen nicht zwingend erforderlichen Änderungen unangetastet.

---
**Arbeitsauftrag:** Den Repository-Bestand systematisch von den frühesten vorhandenen Issues/PRs aufwärts bis zu allen tatsächlich vorhandenen Einträgen prüfen. Aufgaben nicht allein nach Nummern vermuten. Sichere, klar abgegrenzte Arbeiten eigenständig umsetzen, testen und über nachvollziehbare Commits/PRs integrieren. Diesen Plan bei neuen Erkenntnissen aktualisieren.


## Umsetzung gestartet – 2026-11-01

- [x] PR #72 zusammengeführt: Gitleaks-Scan des aktuellen Arbeitsbaums in CI; fehlerhafte Secret-Ignore-Regel korrigiert. Der Scan lief erfolgreich. Git-Historie wurde damit nicht bereinigt; bestehende TikTok-Verbindungen/OAuth-Konfiguration wurden nicht verändert.
- [x] PR #73 zusammengeführt: rollenbasierte KI-Spezialisten für Core, Code, Game, Design, Gifts, Testing, Repair, Integration, Studio, Server/Ops und General. Rollen haben eigene Missionsanweisungen und technisch erzwungene Schreibpfade; CLI-Auswahl über `python -m ai --specialist <rolle>`. Die vorhandenen Agenten- und Cloudflare-Worker-Tests sowie die neuen Spezialistentests liefen in GitHub Actions erfolgreich (Run 41278837404).
- [ ] Echte Modellinferenz gegen einen tatsächlich laufenden lokalen oder autorisierten Streamiov-Provider nachweisen; die CI nutzt weiterhin Test-/Mock-Endpunkte und ersetzt keinen Hardware-/Provider-Test.
- [ ] Sicheren Aufgaben-Orchestrator mit Warteschlange, Zustandsmodell, Retry-/Timeout-Grenzen, Spezialistenzuweisung, Branch-Isolation und Ergebnisprotokollen ergänzen.
- [ ] Agentendienst mit sicherem Start/Stop, Wiederanlauf, Healthcheck und kontrollierter Ausführung bereitstellen; nicht als dauerhaft aktiv markieren, bevor real getestet.

- [x] PR #74 zusammengeführt: synchroner, begrenzter DAG-Orchestrator mit Abhängigkeitsprüfung, stabiler Ausführungsreihenfolge, Fehlerisolierung und Überspringen abhängiger Aufgaben.
- [x] PR #75 zusammengeführt: SQLite-Warteschlange mit transaktionalem Claim, Worker-Leases, Heartbeat-API, begrenzten Wiederholungen und einem One-Task-Worker; CI nach Korrektur der Reihenfolge-/Abhängigkeitstests erfolgreich.
- [x] PR #76 zusammengeführt: CLI zum dauerhaften Einreihen und zum Ausführen genau eines Worker-Auftrags; ein leerer Worker beendet sich ohne Modellstart. Full AI/Cloudflare tests and secret scan passed.
- [ ] Dauerhafter Worker-Dienst mit kontrolliertem Polling, sauberem SIGTERM/SIGINT-Stopp, Lease-Erneuerung während langer Inferenz und Supervisor-Konfiguration ergänzen und auf dem vorgesehenen Cloud-Host testen.
- [ ] Echtes Ende-zu-Ende-Modell mit realer Inferenz und realer Agenten-Dateiänderung im isolierten Branch ausführen; bisherige Agenten-/Queue-Tests verwenden kontrollierte Testprovider.
- [x] PR #77 zusammengeführt: supervisierter Worker-Loop mit SIGINT/SIGTERM-Stopp, Polling, Task-Limit und automatischer Lease-Erneuerung bei langen Modellaufrufen; abgelaufene Leases können keine Aufgaben mehr abschließen/fehlschlagen lassen. Gehärtetes systemd-Beispiel und Host-Dokumentation ergänzt. KI-/Cloudflare-Tests und Secret-Scan erfolgreich.
- [ ] systemd-Beispiel auf einem echten, vorgesehenen Cloud-Host einrichten, Provider-Konfiguration außerhalb Git hinterlegen, Dienst starten und Restart-/Stop-/Backup-/Monitoring-Abnahme durchführen. Der Dienst wurde nicht produktiv installiert oder gestartet.
- [x] PR #78 zusammengeführt: Core-KI kann ein Ziel in einen begrenzten Spezialisten-Aufgabenplan aufteilen, Rollen/IDs/Abhängigkeiten/Zyklen validieren und den Plan über `--plan-and-enqueue` dauerhaft einreihen. KI-/Cloudflare-Tests und Secret-Scan erfolgreich.
- [ ] Echter Core-Planungslauf mit dem vorgesehenen Modellprovider und anschließende Ausführung durch den supervisierten Worker auf dem vorgesehenen Host nachweisen; die bisherigen Tests nutzen kontrollierte Fake-Provider.
