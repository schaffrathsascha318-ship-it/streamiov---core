# STREAMIOV Studio – eigene Regie-Engine

## Produktgrenze
- Einzige externe Live-Plattform zum Start: **TikTok LIVE**.
- Regie, Szenenverwaltung, Medienpipeline, Quellen-, Audio- und Geräteverwaltung sind STREAMIOV-Eigenentwicklung.
- Keine OBS-Laufzeitabhängigkeit, kein OBS-Frontend und keine Twitch-/YouTube-/Kick-/Facebook-Adapter im Startumfang.
- TikTok-Zugriff nur über tatsächlich erlaubte/offizielle Schnittstellen und erteilte Berechtigungen. Nicht verfügbare Schnittstellen werden als nicht verfügbar ausgewiesen.

## Desktop-Ziel
Windows 11 x64 ist die primäre Referenzplattform für leistungsstarke Desktop-PCs und Laptops. GPU-Encoding, Mehrkamera-/Capture-Setups, mehrere Monitore und professionelle Audiointerfaces werden in einer Hardware-Testmatrix geprüft. ARM64 und weitere Betriebssysteme bleiben getrennte zusätzliche Build-Ziele.

## Regie-Aufteilung
1. Regie-Zentrale und Streamstatus
2. Szenenbibliothek, Preview und Program/TAKE
3. Quellen- und Multiview-Verwaltung
4. Kamera-/Capture-Geräte
5. Audio-Mixer, Monitoring und Routing
6. TikTok LIVE Verbindung und Berechtigungen
7. Chat und Moderation
8. Alerts und Ereignisverarbeitung
9. Musik und Soundeffekte
10. TTS
11. Geschenke-Galerie und interaktive Effekte
12. KI-Regieassistent
13. Encoder, Netzwerk und Diagnose
14. Profile, Einstellungen und Updates

## Engine-Verträge
- engine/scene-engine.js ist die erste isolierte Engine-Komponente und wird in den Electron-Build aufgenommen.
- Preview und Program sind getrennte Zustände. Nur TAKE übernimmt Preview nach Program.
- Ein Szenenname LIVE beweist keinen aktiven Stream. liveConfirmed ist nur wahr, wenn Verbindung und aktive Ausgabe von einer später integrierten Stream-Runtime bestätigt werden.
- Szenen-Engine und UI dürfen niemals selbst einen erfolgreichen TikTok-Live-Start vortäuschen.
- Persistenz und IPC bleiben im Electron-Hauptprozess; Renderer erhalten nur eng begrenzte Aktionen über Preload.

## Entwicklungsreihenfolge
1. Regie-Kern (Szenen, Preview/Program, Quellenmodell, Statusmaschine)
2. Eigene Medienpipeline (Capture, Audio, Compositing, Encoder)
3. TikTok LIVE-Adapter mit Berechtigungs-/Verbindungsprüfung
4. Chat, Alerts, TTS, Musik und Geschenke als echte Ereignis-Module
5. KI-Regieassistent, Profile, Telemetrie und Updateprozess
6. Windows-11-x64-Hardwareabnahme und erst danach weitere Zielplattformen

Jede Komponente erhält automatisierte Tests. Hardware- und echte Live-Abnahme werden getrennt dokumentiert; ein Unit-Test oder Build ist kein Nachweis eines echten Streams.
