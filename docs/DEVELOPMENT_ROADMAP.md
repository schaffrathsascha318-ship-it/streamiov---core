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

### GitHub inventory baseline (2026-11-26)

- **Method:** read-only `gh issue list --repo schaffrathsascha318-ship-it/streamiov---core --state all --limit 1000 ...` and `gh pr list --repo schaffrathsascha318-ship-it/streamiov---core --state all --limit 1000 ...`; all result pages were checked. No issue, PR, comment, commit, or deployment was created or modified.
- **Counts:** 52 issues (44 open, 8 closed); 203 pull requests (34 open, 40 closed unmerged, 129 merged; 56 drafts total, 28 of the 34 open PRs). Highest issue `#247`; highest PR `#255`.
- **Open issues:** `#1`, `#3`, `#27`, `#28`, `#40`, `#54`, `#55`, `#59`, `#60`, `#61`, `#63`, `#64`, `#65`, `#91`, `#92`, `#94`, `#97`, `#99`, `#105`, `#107`, `#111`, `#114`, `#116`, `#120`, `#124`, `#128`, `#139`, `#140`, `#145`, `#152`, `#156`, `#168`, `#172`, `#189`, `#193`, `#200`, `#201`, `#205`, `#215`, `#216`, `#223`, `#230`, `#232`, `#235`.
- **Closed issues:** `#39`, `#66` (duplicate of `#65`), `#101`, `#102`, `#104`, `#147`, `#233`, `#247`.
- **Open PRs:** `#81`, `#82`, `#85`, `#87`, `#88`, `#89`, `#98`, `#100`, `#108`, `#110`, `#112`, `#113`, `#118`, `#122`, `#129`, `#132`, `#133`, `#135`, `#136`, `#159`, `#171`, `#175`, `#178`, `#179`, `#180`, `#187`, `#188`, `#228`, `#239`, `#242`, `#243`, `#244`, `#250`.
- **Failing checks:** `#188` (`python-tests`); `#180` (`unittest`, `python-tests`); `#179` (`unittest`, `python-tests`); `#178` (`python-tests`); `#171` (`python-tests`); `#135` (`offline-verification`, `unittest`). Checks for `#175` are cancelled, not failed.
- **Merge conflicts:** 20 open PRs are `CONFLICTING`: `#81`, `#82`, `#85`, `#87`, `#98`, `#100`, `#110`, `#112`, `#113`, `#132`, `#135`, `#159`, `#171`, `#175`, `#179`, `#180`, `#187`, `#228`, `#244`, `#250`. All 34 open PRs have no recorded review decision or review.
- **Tracker drift:** the 2026-11-01 GitHub inventory comment in issue `#3` claims 15 issues and 63 PRs with highest number `#78`; the checked inventory is 52 issues and 203 PRs with highest PR `#255`. Issue `#3`'s body still says TikTok LIVE is the only external platform and treats PWA/web as an installation path; merged PR `#206` and the native-only decision supersede that wording. The external tracker was not edited here because an owner-reviewed update is required.
- **Local documentation drift:** PRs `#81`, `#82`, and `#85` were reported implemented in an old issue comment but remain open, draft, and conflicting; PR `#87` remains open and conflicting; PRs `#83`, `#84`, `#86`, and `#119` are merged; issue `#116` remains open even though PR `#119` was merged. The affected local notes are corrected in `docs/STATUS.md`, `docs/ai-development/bridge-smoke-test.md`, and `docs/studio/audio-engine-integration-plan.md`.
- **Superseded/open duplicates:** `#66` was closed as a duplicate of `#65`; PR `#250` duplicates merged `#251`; `#242` duplicates merged `#255`; `#243`, `#244`, `#179`, `#47/#50/#51`, `#42/#45/#48`, `#44/#49`, and the `#184/#185/#186/#187` and `#231/#234/#236/#240` chains are overlapping or superseded. They are documented, not silently discarded.
- **Priority:** first resolve failing checks and merge conflicts or close superseded PRs with owner approval; then update tracker issue `#3`; only then start new large feature work. External gates remain unchanged.

## Phase 1 – STREAMIOV Core und Plattformfundament

- Core-API, Authentifizierung, Berechtigungen, Konfiguration und Fehlerbehandlung prüfen und vervollständigen.
- Gemeinsame Event- und Nachrichtenverträge für Studio, Spiele, Geschenke und KI definieren.
- Sichere lokale und entfernte Schnittstellen, Schema-Versionierung, Rate Limits und Audit-Protokolle etablieren.
- Konfiguration und Secrets strikt von Quellcode und Client-Paketen trennen.
- Health Checks, Metriken, Logs, Backups und Wiederherstellungsabläufe aufbauen.
- Cloudflare-Deployments, D1/R2 oder andere bereits vorgesehene Cloudflare-Dienste nur anhand realer Anforderungen und Kosten-/Limitprüfungen integrieren.
- Produktionshost und Cloud-Speicher unabhängig vom Chromebook bereitstellen und verifizieren.

**Abnahme:** reproduzierbare Tests, dokumentierte Deployments, Monitoring, Backup-/Restore-Test und bestätigte Produktions-Healthchecks.

### Lokale Eventledger-Kette (lokal implementiert 2026-11-26)

- Studio-Ereignisse haben einen versionierten v1-Vertrag mit festem `source: "studio"`, Main-Process-ID/Zeitstempel, begrenzten flachen Daten und Redaktion für geheimnisähnliche Schlüssel sowie RTMP-URLs.
- Der lokale Core speichert Ereignisse idempotent und eigenerbezogen in `events.sqlite3`; `GET/POST /api/v1/events` verlangt Session, Studio-Client-Header und Origin-/Loopback-Prüfung mit Rate Limit.
- Die Regie zeigt echte Core-Ereignisse im `EREIGNISPROTOKOLL`, solange eine Core-Session besteht; ohne Session bleibt das lokale Log sichtbar und ein fehlgeschlagener Versand wird nicht als übertragen ausgegeben.
- Der externe Eventconnector ist lokal angebunden: Twitch-EventSub liefert offizielle Cheer-/Raid-Benachrichtigungen in dieselbe Regie- und Alertkette; echte Twitch-App-Freigabe und Eventzustellung sind weiterhin nicht ausgeführt.
- Offen: Kein echter Electron-/Core-Login-Lauf, kein Geschenk-, Auszahlungs- oder Plattformtransaktionsledger. Stream-Start-Ereignisse bestätigen keine Remote-Publikation.

### Dauerhaftes OAuth-Rate-Limit (lokal implementiert 2026-11-26)

- `host/auth.py` begrenzt OAuth-Callback-, Connect- und Refresh-Versuche mit einem SQLite-gestützten gleitenden Zeitfenster in der bestehenden Plattformdatenbank. Buckets sind HMAC-Hashes mit einem lokal gespeicherten Zufallsschlüssel; Klientadressen werden nicht im Klartext abgelegt.
- `host/server.py` nutzt den dauerhaften Throttler nur bei verfügbarem verschlüsseltem Connection Store. Ohne Token-Key bleibt der In-Memory-Throttler aktiv, damit der Healthcheck keine nicht initialisierte Plattformdatenbank behauptet.
- Regressionstests sichern Persistenz über Host-Neustarts, Zeitfensterablauf, getrennte Aktionen/Adressen, Bucket-Obergrenze, keine Klartextadressen und Fail-Closed bei Speicherfehlern ab.
- Offen: dies ist kein verteilter Limiter über mehrere Hosts und kein Nachweis eines echten Plattform-OAuth-Laufs; Live-Freigaben, Produktionsneustarts und Deployments bleiben extern.

### Lokale Core-Backup-/Restore-Kette (lokal implementiert 2026-11-26)

- `host/backup.py` erzeugt versionsierte Backups aus konsistenten SQLite-Snapshots der bekannten Core-Datenbanken und protokolliert fehlende Datenbanken ausdrücklich als abwesend.
- Manifest, Größen, SHA-256, SQLite-Integrität und `0600`-Rechte werden vor jeder Wiederherstellung geprüft; unbekannte oder ausgelassene Pfade, Symlinks und manipulierte Dateien werden abgelehnt.
- Die Host-CLI bietet getrennte Create-, List-, Verify-, Prune- und Restore-Aktionen. `--backup-prune --backup-keep N` löscht nur gültige Backups jenseits der N neuesten; ungültige Verzeichnisse bleiben zur Prüfung liegen.
- Restore ersetzt vorhandene Core-Dateien nur mit ausdrücklichem `--backup-force` und entfernt veraltete WAL-/SHM-/Journal-Dateien.
- Offen: Kein automatischer Zeitplan, kein Cloud-Upload, kein Produktionsdatendir-Restore und kein Musik-Audio-Einschluss. Der Token-Key liegt bewusst im lokalen Backup und erfordert einen bereits geschützten Ablageort.

### Studio-Medienquellen und Programmausgabe-Relay (lokal implementiert 2026-11-26)

- Bilder, Videos und Audiodateien werden über einen engen IPC-Vertrag in einen privaten Medienspeicher importiert und nur über eine geprüfte `streamiov-media`-Scheme aufgelöst.
- Szenen speichern validierte Einstellungen für Kamera, Bildschirm, Fenster, Bild, Video, Audio und Farbe; die Regie bearbeitet Quellen inklusive Loop, Lautstärke und Stummschaltung.
- Importierte Dateien werden in einer Medienverwaltung angezeigt; Entfernen ist nur möglich, wenn keine Szene die Datei noch verwendet.
- Capture-, Bild- und Audioelemente werden als echte Runtimes im Lokal-Canvas dargestellt, in den Mixer eingebunden, bei Änderungen freigegeben und bei Fehlern mit Retry gemeldet.
- Der Streamstart prüft sichtbare Quellen und deren geroutetes Audio in der Programmszene, nicht nur die älteren Kamera-/Bildschirm-Testbuttons.
- Während des Streams werden beendete Programmquellen erkannt; Start und Stopp werden als lokale `studio.stream.*`-Ereignisse protokolliert, ohne daraus eine Remote-LIVE-Bestätigung abzuleiten.
- Die Programmausgabe erhält Medienliste, Szenen und begrenzte JPEG-Frames über getrennte, sender-geprüfte Kanäle; sie bleibt ausdrücklich lokale Canvas-Ausgabe ohne LIVE-Behauptung.
- Offen: Kein nativer Kamera-/Bildschirm-/Fenster-Test auf echtem Gerät, keine echte Encoder-/RTMP-Ausgabe und keine Remote-LIVE-Bestätigung durch diese Kette.

### Produktive Studio-Medien-Pipeline, A/V-Sync und lokale Aufzeichnung (lokal implementiert 2026-11-26)

- Kamera, Bildschirm, Fenster und Medien speichern validierte Auflösung, Bildrate, Lautstärke, Stummschaltung, Loop und Kamera-Audio-Opt-in; die Regie wendet echte Capture-Constraints an.
- Echte Bild- und Audiotracks werden über die vier Busse in den Stream gemischt; der Programm-Canvas läuft mit festem Takt aus der gewählten Stream-Bildrate statt im UI-Animationsrhythmus.
- Die Programmausgabe erhält begrenzte binäre JPEG-Frames statt Data-URLs; der Hauptprozess prüft Größe und JPEG-Magic, die Ausgabe dekodiert mit `ImageBitmap` und Sequenzschutz.
- Der RTMP-Encoder erzwingt Video- und Audiomapping, CFR, passende GOP-/Keyint-Werte und Audio-Resampling; der MediaRecorder liefert 250-ms-WebM-Blöcke.
- Während eines Streams kann der komponierte Mediastream zusätzlich als lokale WebM-Datei im Benutzerprofil aufgezeichnet werden; Schreibzugriff ist serialisiert, auf 2 GiB begrenzt und kein Upload.
- Soundboard-Pads nutzen den privaten Medienspeicher und stellen Kategorie, Hotkey, Lautstärke, Stummschaltung und Favoriten beim nächsten Öffnen wieder her; fehlende Assets werden übersprungen.
- Offen: Echte Gerätefreigaben, Zielgeräte-Wiedergabe, RTMP-Empfang, Remote-LIVE-Bestätigung und Wiedergabe der Aufzeichnung auf einem Zielgerät bleiben extern zu prüfen.

### Persistente Streamiov Music (lokal implementiert 2026-11-26)

- Queue, Playlists, Shuffle/Repeat, Lautstärke, Stummschaltung und Routing liegen in einer privaten, benutzerbezogenen SQLite-Datenbank des lokalen Hosts.
- Playlists können gespeichert, geladen, gelöscht und kombiniert werden; lokale Audio-Importe bleiben im privaten Medienspeicher und sind nie automatisch für LIVE freigegeben.
- Das Rechtegate bleibt fail-closed: nur exakt geprüfte, kostenlose Genehmigungen für Territorium und Nutzung sowie eine vorhandene lokale Audiodatei ergeben einen abspielbaren Katalogtitel.
- Die lokale KI erstellt und pflegt Playlists ausschließlich aus freigegebenen Katalogtiteln; sie kauft, lädt oder behauptet keine Lizenzen.
- LIVE-Start und Stream-Routing blockieren ungeprüfte Musik; zwischengespeicherte oder wiederhergestellte Zustände dürfen den Schutz nicht umgehen.
- Offen: Rechtekatalog und Audiodateien müssen von einer verantwortlichen Person lokal gepflegt werden; echte Zielgeräte-Audioausgabe, Produktionsdatenbank und Remote-LIVE-Bestätigung sind nicht Teil dieser lokalen Implementierung.

### Interne Effektvorlagen statt Geschenkversand (Produktgrenze korrigiert 2026-11-26)

- Die Regie zeigt Einträge ohne TikTok-Gift-ID ausschließlich als interne Effektvorlagen aus dem read-only Rohdaten-Katalog; Einträge mit Plattform-ID werden ausgeblendet.
- Eine lokale Effektzuordnung wird gespeichert; die Vorschau wird im Overlay und im Programm-Canvas ausgelöst und über den geschützten Eventkanal als `studio.gift.effect_preview` im Core-Eventledger gespeichert, wenn eine echte Session vorhanden ist.
- Es gibt keinen Shop, keine Punktebelastung, kein Kauf, keinen Versand, keine Auszahlung und keine behauptete TikTok-Geschenkefreigabe; lokale Punktewerte sind reine Katalogangaben.
- Echte Geschenke werden ausschließlich aus autorisierten Plattformereignissen übernommen; derzeit ist dafür der offizielle Twitch-EventSub-Pfad für Gift-Subscriptions vorgesehen. TikTok LIVE stellt dafür keine offizielle Echtzeit-API bereit.
- Offen: vollständige Original-Asset-Pakete und echte plattformübergreifende Geschenkereignisse bleiben getrennt geprüfte Aufgaben.

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
- Alerts, Chat, Musik, TTS, Events, Geschenke und Spielanalyse als integrierte Module; Spiele-Downloads und -Präsentation gehören ausschließlich zur offiziellen Homepage.
- TikTok-LIVE-Anbindung ausschließlich über offiziell unterstützte und freigegebene Schnittstellen.
- Verlässliche Wiederverbindung, Fehlerzustände, Bandbreiten-/Encoderprofile und Stream-Status.
- Plattformübergreifende Pakete getrennt für Windows x64/ARM64, Linux x64/ARM64 und ChromeOS-Ziele erstellen; nur tatsächlich getestete Targets als unterstützt bezeichnen.

**Abnahme:** Studio startet reproduzierbar, Geräte werden real erkannt, Vorschau und Programmausgabe funktionieren, Audio/Video-Pipeline ist nachgewiesen und ein autorisierter Teststream wurde erfolgreich geprüft. CI-Builds allein sind keine Live-Verifikation.

## Phase 4 – Spiele auf der Homepage, Analyse im Studio

- Eigene Spiele ausschließlich auf der offiziellen Homepage präsentieren: Beschreibung, echte Screenshots, unterstützte Betriebssysteme, Version, Updates und Prüfsummen.
- Spiele-Downloads und Installation niemals im Studio anbieten, keine Browser-Spiele entwickeln und Spiele nicht innerhalb der Homepage ausführen.
- Studio: lokale Prozesslese, Gameplay-Erkennung, Statistiken, Highlights, Replay-Marker, lokalen Gaming-Assistenten und Event-/Overlay-Integration bereitstellen.
- Bestehende signierte Prototyp-Archive erhalten, aber klar als Prototyp-Pakete ohne Installer, automatische Updates und veröffentlichte Screenshots kennzeichnen.
- Automatisierte Quelltests plus echte Gameplay-, Barrierefreiheits-, Rechte- und Geräteprüfung vor einem öffentlichen Release durchführen.
- Release-Pipeline mit Version, Änderungsprotokoll, Paketen, Prüfsummen und Rückrollmöglichkeit aufbauen.

**Abnahme:** Die Homepage nennt für jedes Spiel Plattform, Version, Prüfsumme und ehrlichen Freigabestand; das Studio zeigt ausschließlich Analyse laufender Spiele und besitzt keine Galerie, keinen Download und keinen Start. Öffentliche Releases erst nach abgeschlossener Verifikation.

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

### Verbindungs- und LIVE-Statuskette (lokal implementiert 2026-11-26)

- Core-Erreichbarkeit, Twitch-/TikTok-OAuth-Status und Plattform-Ausgabezustand werden in der Regie getrennt angezeigt.
- Vorbereitete Ausgaben, Verbindungsaufbau und Ausgabefehler enthalten immer `NICHT LIVE`.
- `LIVE BESTÄTIGT` setzt eine echte Remote-Bestätigung im Plattform-Ausgabe-Registry voraus; lokaler Encoder-, RTMP- oder OAuth-Status genügt nicht.
- Der Remote-Bestätigungsconnector ist lokal verdrahtet: Twitch Helix `getLiveStatus()` und TikTok `getLiveStatus()` dürfen eine Registry nur mit plattformpassender, timestamped `remote_platform_confirmation` auf `live` setzen.
- Offen: echte Plattformfreigaben, freigegebene TikTok-LIVE-API-Zugangsdaten, RTMP-Empfang und Remote-LIVE-Bestätigung fehlen; deshalb bleibt die Produktkette lokal ehrlich, aber nicht extern LIVE-verifiziert.

### LIVE-Ausgabekette (lokal implementiert 2026-11-26)

- `engine/live-output-manager.js` startet einen eigenen FFmpeg-/RTMP-Prozess pro ausgewählter Plattform, verteilt dieselben Programm-Medioblöcke an alle aktiven Ausgänge und meldet getrennt `starting`, `connecting`, `output_ready`, `reconnecting`, `error` und `offline`.
- Fehlgeschlagene Ausgänge bleiben während des begrenzten Backoffs als `reconnecting` sichtbar und stoppbar; nach drei Fehlversuchen wird der Fehler endgültig gemeldet. Ein sauberer Stopp beendet stdin, erzwingt bei Bedarf `SIGINT`, wartet begrenzt auf `close` und setzt alle Plattformen auf `offline`.
- `main.js` akzeptiert nur Plattformnamen aus dem Registry, lehnt renderer-gelieferte Ziele ab und ermittelt Ziele ausschließlich über Twitch Helix bzw. freigegebene TikTok-Ingest-Quellen im Hauptprozess.
- Die Regie bietet getrennte Twitch-/TikTok-Ausgänge, zeigt Wiederverbindung und Output-Bereitschaft ohne LIVE-Behauptung und protokolliert Start/Stopp mit den tatsächlich ausgewählten Plattformen.
- Akzeptanz lokal erfüllt; Akzeptanz extern erst nach echtem RTMP-Empfang, bestätigter Plattform-Publikation und freigegebener TikTok-LIVE-Schnittstelle.

### Multiview, Chat und Alertregeln (lokal implementiert 2026-11-26)

- Die Regie rendert persistierte oder Demo-Szenen als echte Canvas-Thumbnails mit `VORSCHAU`/`PROGRAMM`-Kennzeichnung und direkter TAKE-/Vorschau-Auswahl.
- Twitch-Chat läuft über den offiziellen IRC-WebSocket mit `chat:read`; Nachrichten werden im Hauptprozess normalisiert, in den gemeinsamen Chat-Hub aufgenommen und an alle Studio-Fenster gesendet.
- Twitch-EventSub abonniert `channel.cheer`, `channel.raid`, `channel.follow`, `channel.subscribe` und `channel.subscription.gift` über den offiziellen WebSocket und speist bestätigte Ereignisse in denselben Hub ein. Kein Ereignis wird lokal erfunden oder als Plattformzahlung ausgegeben.
- Alertregeln werden lokal gespeichert, reagieren auf echte Chat-/Eventtexte mit Quellenfilter und Mindestabstand und lösen sichtbare Programm-Alerts aus. Der lokale Musiktest erzeugt eine echte WAV-Datei über GStreamer.
- Offen: Keine echten Twitch-Tokens, Eventzustellung, externen Plattformereignisse oder Geräteaudiotests; TikTok-Chat und Discord-Geschenke bleiben ohne autorisierte Schnittstelle.

### Chat-Moderation, Rollen-TTS und Plattform-Event-Alerts (lokal implementiert 2026-11-26)

- Der Chat speichert blockierte Wörter, Sperren, Slow-Mode und Sende-/Sprechrechte pro Rolle lokal; Nachrichten werden vor dem Hub geprüft und ausgeblendete Nachrichten werden nicht erfunden.
- Twitch-Rollen stammen aus offiziellen IRC-Badges; EventSub holt nur mit gewährten Scopes Follow-, Subscribe-, Gift-Subscribe-, Cheer- und Raid-Ereignisse und meldet fehlende Abonnements sichtbar.
- Eingehende Nachrichten können über echte TTS in den Vier-Bus-Mixer vorgelesen werden; die LIVE-Ausgabe folgt unverändert der Quellenmatrix und dem Rechte-Gate.
- Alertregeln für offizielle Plattformereignisse lösen nur aus bestätigten Twitch-Ereignissen sichtbare Alerts aus; TikTok-Chat und TikTok-Geschenke bleiben ohne autorisierte Echtzeit-API.
- Akzeptanz lokal erfüllt; Akzeptanz extern erst mit echten Twitch-Tokens, Eventzustellung, Chatverkehr und Geräteaudiotests.

### Forum-Aufbewahrungsrichtlinie (lokal implementiert 2026-11-26)

- `host/forum.py` ergänzt `deleted_at` für weich gelöschte Threads und Antworten; bestehende Einträge werden aus `created_at` nachgezogen.
- Offene Meldungen und sichtbare Beiträge bleiben dauerhaft. Gelöste/verworfene Meldungen und weich gelöschte Inhalte verfallen nach 90 Tagen, Moderationsaktionen nach 180 Tagen, gelesene Benachrichtigungen 30 Tage nach Lesen und ungelesene nach 90 Tagen.
- `retention_status()` ist ein Dry-Run; `apply_retention()` löscht transaktional und idempotent. Die CLI bietet `--forum-retention-status` und `--forum-retention-run`.
- Offen: kein automatischer Zeitplan, keine E-Mail-Benachrichtigung, kein externes Löschprotokoll, keine rechtliche Freigabe und kein Nachweis auf Produktionsdaten.

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
- [x] PR #79 zusammengeführt: optionale, auditable Lernablage für test-verifizierte Engineering-Lektionen; relevante Hinweise werden pro Spezialist als ausdrücklich unvertrauenswürdiger Referenzkontext bereitgestellt. Credential-ähnliche Inhalte und unsichere Testpfade werden abgewiesen. KI-/Cloudflare-Tests und Secret-Scan erfolgreich.
- [ ] Lernablage in echten Entwicklungsaufgaben nutzen, Regressionen erneut ausführen und veraltete/überholte Lektionen nachvollziehbar markieren; dies ist Retrieval, kein Training oder selbstständige Änderung der Modellgewichte.
- [x] PR #80 zusammengeführt: read-only Validierung für STREAMIOV-native Geschenkkataloge mit sicheren Asset-Pfaden, eindeutigen IDs, korrekter Punktwert-Semantik und strikter Trennung von TikTok-native Gift-IDs. Ein Geschenk gilt nur mit explizitem RELEASED-Status und tatsächlich vorhandener Asset-Datei als veröffentlicht. Checkout/Auszahlung bleiben deaktiviert. KI-/Cloudflare-Tests und Secret-Scan erfolgreich.
- [ ] Geschenk-Assets als vollständige Originalpakete erzeugen, rendern und auf Desktop/Mobilgeräten prüfen; Eventbus/Regie-Integration und unabhängiger Zahlungs-/Auszahlungsweg bleiben offen.
