# STREAMIOV – All-in-One Studio und geräteübergreifende Architektur

**Status:** Architekturauftrag / Umsetzung in Arbeit  
**Branch:** `work/all-in-one-device-studio-architecture`  
**Leitbild:** Ein Studio, das die benötigten Creator-Funktionen integriert, statt mehrere vollständige Streaming-Programme vorauszusetzen.

## 1. Verbindliche Produktziele

- STREAMIOV Studio ist die zentrale Regie- und Medienanwendung.
- TikTok LIVE ist die einzige externe Streaming-Zielplattform im aktuellen Produktumfang.
- Discord ist eine zusätzliche Community- und Voice-Integration, kein Streaming-Ziel.
- Szenen, Quellen, Compositing, Audio-Mixer, Monitoring und Encoder bleiben STREAMIOV-eigene Komponenten.
- Keine OBS-Laufzeit, kein OBS-Frontend und keine Abhängigkeit von TikTok LIVE Studio, Streamlabs oder einer zusätzlichen vollständigen Discord-Desktop-App als Voraussetzung.
- Bestehende TikTok-App-, OAuth-, Redirect-, Scope- und Creator-Verbindungen bleiben unverändert, sofern eine separat geprüfte, zwingend notwendige Änderung nicht ausdrücklich freigegeben wurde.
- Keine produktive Veröffentlichung, Cloud-Konfigurationsänderung oder Zugangsdatenmigration im Rahmen dieses Architekturauftrags.

## 2. Geräte- und Betriebssystemziele

Die Oberfläche und die unterstützten Funktionen passen sich an die tatsächlichen Gerätefähigkeiten an. Ein gemeinsamer Produktkern bedeutet nicht, dass jedes Betriebssystem dieselben Capture-, Audio- oder Encoder-APIs bereitstellt.

| Zielgerät | Zielrolle | Abnahmekriterien |
|---|---|---|
| Windows 11 x64 | Primäre vollständige Desktop-Regie | Kamera-/Capture-Geräte, Audio-Routing, GPU-Encoding, mehrere Displays, TikTok-LIVE-Ausgabe |
| Linux x64 | Desktop-Regie | Geräteerkennung, Audio-Backends, Encoder und Paketierung auf realen Distributionen geprüft |
| macOS | Desktop-Regie | Berechtigungen, Kamera-/Audio-Capture, Bildschirmaufnahme, Encoder und Paketierung geprüft |
| ChromeOS / Chromebook | Angepasster Studio-Client und Regie | ChromeOS-/Linux-Container-Grenzen dokumentiert; reale Geräte- und Audiofunktionen geprüft |
| Android | Mobile Studio-/Regie-Begleitfunktionen | Kamera, Chat, Monitoring und Fernsteuerung gemäß Android-Hintergrund- und Berechtigungsgrenzen |
| iPhone / iPad | Mobile Studio-/Regie-Begleitfunktionen | Kamera, Chat, Monitoring und Fernsteuerung gemäß iOS-/iPadOS-Berechtigungs- und Hintergrundgrenzen |

Ein Gerät wird erst dann als vollständig unterstützt bezeichnet, wenn ein reproduzierbarer Installations-, Geräte-, Audio-/Video- und Laufzeittest auf realer Hardware vorliegt. Mobile Betriebssysteme dürfen nicht als gleichwertige Desktop-Encoding-Hosts dargestellt werden, wenn Systemrestriktionen das verhindern.

## 3. Chromebook mit zwei Displays

Standardlayout für das vorhandene Chromebook-Setup:

- **Chromebook-Display:** vollständige Regie mit Szenen, Preview/Program-Steuerung, TikTok-Status und Chat, Discord-Status/Voice-Steuerung, Audio-Mixer, Quellen und Einstellungen.
- **Externer Monitor:** große Program-/LIVE-Vorschau oder konfigurierbares Multiview.
- Fenster- und Layoutzustand wird gespeichert und nach Display-Neuverbindung wiederhergestellt.
- Display-Auflösung, Skalierung, Rotation und Verbindungswechsel werden erkannt.
- Bei nur einem Display fällt die Oberfläche in ein nutzbares Ein-Bildschirm-Layout zurück.
- Der externe Monitor zeigt nur dann eine echte Program-Ausgabe, wenn die lokale Medienpipeline diese tatsächlich liefert; eine UI-Vorschau darf nicht als bestätigter Live-Stream ausgegeben werden.

## 4. Gemeinsame Studio-Architektur

1. **Studio Shell:** plattformangepasste UI, Fenster- und Displayverwaltung.
2. **Regie-Engine:** Szenen, Quellen, Preview, Program, TAKE und Statusmaschine.
3. **Medienpipeline:** Capture, Compositing, Audio-Mix, Monitoring und Encoder.
4. **Geräteabstraktion:** Kamera, Mikrofon, Capture-Karten, Displays, Audio-Endpunkte und Berechtigungen.
5. **Audio-Routing:** getrennte Busse für Mikrofon, Spiel/System, Musik, Alerts, TTS, Discord und TikTok-bezogene Audioquellen, soweit rechtlich und technisch verfügbar.
6. **Integrationsadapter:** klar getrennte, austauschbare Adapter mit dokumentierten Berechtigungen und Fähigkeitserkennung.
7. **Eventbus:** versionierte Ereignisse für Chat, Alerts, Gifts, Szenen und Community-Aktionen.
8. **Core-Verbindung:** Authentifizierung, Profile, Konfiguration, Synchronisierung und zentrale Dienste; Echtzeit-Audio/Video wird nicht unnötig über den Cloud-Core geleitet.
9. **Ressourcenmanager:** bedarfsgesteuertes Laden, begrenzte Hintergrundarbeit, Messung von RAM/CPU/GPU und sauberes Freigeben inaktiver Module.

## 5. TikTok LIVE

- TikTok bleibt das einzige externe Streamingziel.
- Bestehende TikTok-App und OAuth-Konfiguration zuerst inventarisieren und erhalten.
- Adapter zeigt nur Funktionen an, die durch aktuelle offizielle API-Freigaben und vorhandene Berechtigungen tatsächlich unterstützt werden.
- Login, LIVE-Berechtigung, Chat-/Event-Verfügbarkeit und Encoder-Ausgabe sind getrennte Zustände.
- Kein falscher LIVE-Status: Ein lokaler Encoderstart oder eine Szenenbezeichnung beweist nicht, dass TikTok den Stream angenommen oder veröffentlicht hat.
- Keine inoffiziellen Endpunkte, Scraping- oder nicht autorisierten Login-Verfahren.
- Keine neue TikTok-App anlegen und keine bestehende App-Konfiguration eigenmächtig ersetzen.

## 6. Discord Community und Voice

- Discord ist eine optionale, integrierte Community-/Voice-Funktion innerhalb von Streamiov Studio.
- Ziel: Server-/Community-Kontext, unterstützte Nachrichten-/Interaktionsfunktionen und Voice-Steuerung in einer Oberfläche.
- Voice-Audio soll – sofern eine offiziell unterstützte Discord-Schnittstelle den jeweiligen Anwendungsfall erlaubt – als eigener Eingang in den Streamiov-Audio-Mixer gelangen.
- Pro Eingang: Pegel, Mute, Monitoring, Zielbus und sichtbarer Verbindungsstatus.
- Keine Discord-Selbstbots, keine Weitergabe von Benutzerpasswörtern, keine Umgehung von Discord-Berechtigungen oder Voice-API-Beschränkungen.
- Discord Social SDK Voice/Lobbies sind nicht automatisch gleichbedeutend mit dem Beitritt zu beliebigen normalen Server-Sprachkanälen. Vor Implementierung muss der konkrete gewünschte Ablauf gegen die aktuellen Discord-Entwicklerbedingungen und SDK-Funktionen geprüft werden.
- Wenn ein gewünschter Server-Voice-Anwendungsfall nicht offiziell unterstützt wird, wird er klar als nicht verfügbar markiert; keine vorgetäuschte Integration.

## 7. RAM-, CPU- und GPU-Effizienz

- Keine zweite vollständige Streaming- oder Community-Desktop-App als Voraussetzung.
- Module und Ansichten bei Bedarf laden und bei Inaktivität entladen, sofern dies ohne Verbindungsabbrüche möglich ist.
- Eine gemeinsame Medienpipeline statt mehrfacher Capture-/Decode-/Encode-Kopien.
- Hardware-Encoding bevorzugen, wenn verfügbar und stabil; Software-Fallback mit klaren Leistungsindikatoren.
- Audio möglichst ohne unnötige Resampling- und Loopback-Ketten routen.
- Hintergrundpolling, Animationen und Vorschau-Decoding begrenzen, wenn Ansichten verborgen oder pausiert sind.
- Speicherverbrauch nicht pauschal versprechen: Vorher-/Nachher-Benchmarks auf definierten Referenzgeräten mit identischen Szenen, Quellen, Auflösungen, Bildraten und aktiven Integrationen dokumentieren.
- Metriken: Leerlauf-RAM, Studio-RAM, RAM pro aktiver Integration, CPU/GPU-Auslastung, Encoder-Drops, Audio-Underruns und Startzeit.

## 8. Sicherheit und Privatsphäre

- Tokens und Secrets bleiben aus Renderer, Logs, Quellcode und Client-Paketen heraus.
- Minimale OAuth-Scopes und Berechtigungen; keine Erweiterung ohne nachvollziehbaren Bedarf.
- Geräteberechtigungen pro Betriebssystem transparent anfordern.
- Discord- und TikTok-Verbindungen separat widerrufbar und mit eigenständigen Statusanzeigen.
- Lokale Medienverarbeitung bleibt lokal, sofern kein explizit aktivierter Cloud-Dienst sie benötigt.
- Schutzregie/Privacy Shield muss Mikrofon- und Programmausgabezustände korrekt anzeigen; UI-Status darf keine nicht tatsächlich erfolgte Encoder-/Plattformaktion behaupten.

## 9. Umsetzung in sicheren Phasen

### Phase A – Bestandsaufnahme
- Tatsächlichen Recovery-Arbeitsbaum und den GitHub-Stand vergleichen.
- Bestehende Studio-, Audio-, Geräte-, Display-, TikTok- und Discord-Dateien inventarisieren.
- Vorhandene Tests, Workflows, offene PRs und bekannte Einschränkungen erfassen.
- Keine Dateien löschen oder vorhandene Integrationen ersetzen.

### Phase B – Plattform- und Integrationsverträge
- Capability-Matrix je Betriebssystem definieren.
- Display-/Fenstervertrag und Zwei-Monitor-Layout testen.
- TikTok-Adapter anhand bestehender Capability-Audits absichern.
- Discord-Funktionen und Voice-Use-Cases anhand offizieller SDK/API-Dokumentation prüfen.

### Phase C – Gemeinsamer Regie- und Medienkern
- Bestehende Szenen-Engine weiterverwenden.
- Audio-Busse und Quellenmodell um optionale Integrationsquellen erweitern.
- Geräte- und Displaywechsel robust behandeln.
- Tests für Verbindungsabbrüche, fehlende Geräte, Mute, Routing und Wiederherstellung ergänzen.

### Phase D – Integration und Effizienz
- Nur offiziell unterstützte TikTok-/Discord-Funktionen implementieren.
- Integrationen isoliert aktivieren/deaktivieren.
- RAM-/CPU-/GPU-Benchmarks und Regressionstests hinzufügen.

### Phase E – Hardware-Abnahme und gestufte Releases
- Windows 11 x64 zuerst als Referenz abnehmen.
- Danach Linux, macOS, ChromeOS und mobile Begleitfunktionen jeweils separat testen.
- Release nur mit dokumentierten Build-, CI-, Hardware- und – falls zutreffend – echten LIVE-Nachweisen.

## 10. Definition of Done

Eine Funktion gilt erst als fertig, wenn:
- sie im passenden Gerät/OS real funktioniert,
- Berechtigungen und Fehlerzustände korrekt behandelt werden,
- automatisierte Tests und Regressionstests bestanden sind,
- Ressourcenverbrauch gemessen wurde, sofern Effizienz betroffen ist,
- keine bestehenden TikTok-Verbindungen oder Audiofunktionen beschädigt wurden,
- die Dokumentation den tatsächlichen Funktionsumfang und offene Plattformgrenzen korrekt wiedergibt.

**Wichtig:** Dieser Architekturauftrag ändert noch keine produktiven Einstellungen, veröffentlicht keine Installer und behauptet keine bereits implementierte Discord-Voice- oder plattformübergreifende Funktion. Er legt die sichere Umsetzungsgrundlage fest.
