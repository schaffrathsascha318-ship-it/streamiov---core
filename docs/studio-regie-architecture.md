# STREAMIOV Studio – eigene Regie-Engine

## Verbindliche Produktgrenze (Eigentümerentscheidung, 23.11.2026)
- Streamiov Studio ist eine eigenständige installierbare Broadcast-Anwendung und die gemeinsame Regie – keine Videoplattform und keine browserbasierte Studio-Webseite.
- Ein gemeinsames Streamiov-Programm (Preview/Program/TAKE, Szenen, Medien, Audio und Overlays) kann zwei getrennte LIVE-Ausgänge bedienen: TikTok LIVE und Twitch LIVE.
- TikTok und Twitch haben jeweils eigene offizielle Authentifizierung, Berechtigungen, Output-Adapter, Verbindungszustände, Fehlerbehandlung, Wiederverbindung und LIVE-Bestätigung. Der Ausfall eines Ausgangs darf den anderen nicht stoppen oder fälschlich als LIVE markieren.
- Discord ist ausschließlich Community-/Chat-Integration, kein Streaming-Ausgang.
- Keine OBS-Laufzeitabhängigkeit, kein OBS-Frontend und kein kostenpflichtiger Multistream-Dienst.
- TikTok OAuth-Client, bestehende Scopes, Sandbox und Secrets werden ohne separate ausdrückliche Freigabe nicht verändert.

## TikTok-Geschenke – ausschließlich TikToks offizielle Galerie
- Eigene Streamiov-Geschenke sollen ausschließlich für die offizielle TikTok-LIVE-Geschenke-Galerie vorbereitet werden; Aufnahme setzt TikToks tatsächlich unterstützten Einreichungs-/Partnerprozess und Freigabe voraus.
- Zuschauer wählen und senden Geschenke ausschließlich in TikTok.
- Studio empfängt nur offizielle TikTok-Geschenkereignisse und darf darauf mit Alerts, Animationen/Overlays, Sounds und AI-Reaktionen antworten.
- Kein Geschenkeshop, keine Geschenkegalerie, kein Kaufbutton, keine eigene Währung, Zahlung, Ledger- oder Auszahlungsfunktion in Streamiov Studio oder auf der Streamiov-Homepage.
- Twitch Bits, Subs und andere Twitch-Events bleiben native Twitch-Ereignisse und werden nicht als Streamiov-Geschenke umetikettiert.
- TikTok-Preise, Coins, Gebühren, Creator-Auszahlungen und Regeln werden nicht durch Streamiov festgelegt. Keine Behauptung über Annahme, 0%-Provision oder Auszahlung ohne verifizierbare Grundlage.

## Desktop-Ziel
Windows 11 x64 ist die primäre Referenzplattform. Windows ARM64, Linux x64/ARM64 und ChromeOS/Crostini sind getrennte Zielpfade und werden nur für tatsächlich getestete Funktionen unterstützt. Chromebook ist Entwicklungs-/Nutzergerät, niemals Produktionshost.

## Regie-Aufteilung
1. Regie-Zentrale und getrennte Plattform-Ausgangsstatus
2. Szenenbibliothek, Preview und Program/TAKE
3. Quellen- und Multiview-Verwaltung
4. Kamera-/Capture-Geräte
5. Audio-Mixer, Monitoring und Routing
6. TikTok- und Twitch-Verbindung mit getrennten Berechtigungen
7. Gemeinsamer chronologischer Chat: TikTok, Twitch und Discord, jede Nachricht klar gekennzeichnet
8. Alerts, Ereignisverarbeitung und Moderation gemäß Plattformrechten
9. Musikplayer, Bibliothek, Queue/Playlists und Rechteprüfung
10. Soundboard mit lokalen Dateien, Pads, Hotkeys und Stream-/Monitor-Routing
11. TTS
12. KI-Regieassistent
13. Encoder, Netzwerk und Diagnose
14. Profile, Einstellungen und Updates

## Engine-Verträge
- Preview und Program sind getrennte Zustände. Nur TAKE übernimmt Preview nach Program.
- Eine Szene mit dem Namen LIVE beweist keinen aktiven Stream.
- Jeder Plattformausgang besitzt einen unabhängigen Lifecycle. Nur die jeweilige offizielle Plattform-/Ingest-Bestätigung darf diesen Ausgang als LIVE markieren.
- Login/OAuth ist keine LIVE-Berechtigung. Ein lokaler Encoderstart oder initialisiertes RTMP-Ausgabeformat ist keine Bestätigung des Remote-Empfangs.
- Chatadapter und Discord dürfen bei Ausfall keine anderen Chats oder LIVE-Ausgänge blockieren.
- Studio verwaltet keine eigenen Geschenk-Käufe oder Auszahlungen; es reagiert nur auf offizielle TikTok-Geschenkereignisse.
- Persistenz und privilegierte IPC bleiben im Electron-Hauptprozess/Core; Renderer erhalten nur eng begrenzte Aktionen über Preload.

## Entwicklungs- und Abnahmereihenfolge
1. Regie-Kern und gemeinsame Szenen-/Medienproduktion
2. Audio-/Video-Capture, Compositing, Encoder und getrennte Output-Lifecycles
3. Offizielle TikTok- und Twitch-Authentifizierung/Output-Adapter
4. Einheitlicher TikTok-/Twitch-/Discord-Chat mit getrennten Plattformadaptern
5. Musikplayer, Soundboard, Audio-Routing, Alerts und TTS als echte Medien-/Ereignismodule
6. TikTok-Geschenk-Eventreaktionen und externe Vorbereitung offizieller Geschenk-Galerie-Einreichungen
7. KI-Regieassistent, Diagnose, Profile und Updateprozess
8. Windows-11-x64-Hardwareabnahme; danach weitere Zielplattformen

Jede Komponente erhält automatisierte Tests. Hardware-, externe Berechtigungs- und echte LIVE-Abnahme werden getrennt dokumentiert. Ein Unit-Test, Build, Mock, Preview oder lokaler Encoderstart ist kein Nachweis eines echten Streams.
