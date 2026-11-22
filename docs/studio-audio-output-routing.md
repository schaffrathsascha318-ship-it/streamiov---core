# STREAMIOV Studio – Audio-Ausgangs-Routing

## Ziel

Mikrofon, Musik, Spielton, Alerts und TTS werden als getrennte Quellen geführt. Jeder logische Ausgang hat einen eigenen Pegel, Mute-Zustand und ein auswählbares Geräte-Ziel. Eine Änderung an einem Ausgang darf keinen anderen Ausgang verändern.

## Logische Ausgänge

- **Stream:** Mischung, die später dem TikTok-LIVE-Encoder zugeführt wird.
- **Monitor:** Regie-Abhörmix.
- **Kopfhörer:** Separat auswählbares physisches Gerät.
- **Kommunikation:** Separater Ausgang für Gesprächs-/Systemkommunikation.

## Quellen und Routing

Quellen: Mikrofon, Musik, Spiel, Alerts und TTS. Jede Quelle besitzt eine explizite Liste von Ausgängen. Die Routing-Konfiguration darf eine Quelle an mehrere Ausgänge senden oder sie gezielt von einem Ausgang ausschließen.

## Implementierter Stand dieses Commits

- Plattformneutraler, unveränderlicher Zustandsvertrag in `engine/audio-routing.js`.
- Unabhängige Lautstärke-, Mute- und Geräte-ID-Felder pro Ausgang.
- Explizite Quell-Routen, Validierung und serialisierbare Nutzereinstellungen.
- Automatisierte Tests für Isolation, Grenzwerte, Routing und Serialisierung.

**Wichtig:** Dies ist noch kein Audio-Mixer. Alle Ausgänge melden `not_connected`, der Gesamtstatus lautet `configuration_only`. Der bestehende Studio-Mixer ist weiterhin UI-only. Es wird weder behauptet, dass Audio bereits getrennt ausgegeben wird, noch wird ein physisches Gerät angesprochen.

## Nächste Integrationsschritte

1. Geräteadapter pro Plattform: echte Ausgänge erkennen und Geräte-IDs stabil zuordnen.
2. Native Audio-Engine mit getrennten Bussen und Gain/Mute pro Bus.
3. Quellen-Capture und Routing in die Busse integrieren.
4. Monitor-/Kopfhörer-Ausgabe mit Echo-/Feedback-Schutz testen.
5. Stream-Bus mit Encoder verbinden; erst danach TikTok-LIVE-End-to-End prüfen.
6. Windows 11 x64 als Referenz, danach Linux, ChromeOS und mobile Adapter getrennt abnehmen.

Keine Änderung an TikTok-OAuth, Cloudflare-Produktivressourcen oder Live-Ausgabe ist Bestandteil dieses Commits.
