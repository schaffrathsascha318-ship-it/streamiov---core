# STREAMIOV Studio – unabhängige Audio-Busse

Die Regie enthält eine lokale Web-Audio-Engine mit vier voneinander getrennten Ausgängen und einen plattformneutralen Geräteadapter (`engine/audio-device-adapter.js`) für Geräteinventar, Mikrofonöffnung, Ausgabeverbindung und Hot-plug-Beobachtung:

- **Stream / Programm** – eigener MediaStreamDestination-Bus, der in den lokalen MediaRecorder-/Encoder-Eingang eingespeist wird.
- **Monitor** – separat aktivierbare lokale Wiedergabe mit optionaler Auswahl eines Audioausgabegeräts.
- **Kopfhörer** – eigener Wiedergabestream und eigener Gain-/Mute-Regler.
- **Kommunikation** – eigener Wiedergabestream und eigener Gain-/Mute-Regler, standardmäßig ohne Quellenrouting.

## Angeschlossene Quellen

- **Mikrofon:** lokaler MediaStream mit eigenem Quellen-Gain und Routing, einstellbarem Hochpass (20–250 Hz), optionalem Sprachkompressor, Pan, Solo und live RMS-/Peak-/Clipping-Anzeige.
- **Bildschirm-/Spielton:** wird nur verbunden, wenn die ausgewählte Fenster-/Bildschirmfreigabe tatsächlich einen aktiven Audiotrack liefert. Unter Windows fordert Electron für die ausgewählte Capture-Quelle Loopback-Audio an; ob ein Spiel-/Fenster-Audiotrack geliefert wird, entscheidet die Laufzeit und wird zur Laufzeit geprüft.
- **Musik:** der lokale Musikplayer wird über eine MediaStream-Brücke in die Audio-Bus-Matrix eingespeist. Musik-Fader und Mute bleiben eigenständig; Stream- und Monitor-Routing laufen über die Busse.
- **Soundboard:** jedes geladene Pad erhält einen eigenen Kanal und wird über eine MediaStream-Brücke in Stream und Monitor geroutet. Pad-Lautstärke und Mute bleiben pro Datei unabhängig.
- **TTS:** die lokale deutsche Sprachausgabe wird als WAV erzeugt (espeak-ng, unter Windows mit nativer System.Speech-Fallback-Ausgabe) und anschließend über einen eigenen TTS-Kanal in Stream und Monitor geroutet. Ein separater TTS-Fader, eine Warteschlange mit bis zu 20 Texten, Abbruch der Wiedergabe/Warteschlange sowie konfigurierbares Musik-Ducking während TTS/Alerts (25 % Restpegel) sowie einstellbare Sprechgeschwindigkeit (80–300 Wörter/Minute) und Sprachlautstärke (0–100) sind vorhanden; Audioausgabe wird nicht allein durch den IPC-Erfolg als verifiziert markiert.
- **Alerts:** visuelle lokale Alerts erhalten zusätzlich einen kurzen generierten Zweiton-Alert über einen eigenen Stream-/Monitor-Kanal und einen separaten Alert-Fader. Plattform-Events lösen diese Alerts derzeit noch nicht automatisch aus.

Der Stream-Ausgang verwendet den Stream-Bus als Audioquelle und nicht mehr die bisherigen direkten Mikrofon-/Systemton-Eingänge. Bei aktivem Fenster-/System-Loopback wird Monitor-Routing standardmäßig blockiert, um Rückkopplung zu vermeiden; der Nutzer kann es bewusst mit einer sichtbaren Warnung freigeben. Der Stream-Audiomodus begrenzt, welche Live-Quellen in den Stream-Bus gelangen. Bus-Pegel und Bus-Mute wirken unabhängig von Quellen-Fadern. Jeder Ausgang besitzt zusätzlich einen Dynamik-Limiter (−1 dBFS Zielschwelle); alle Quellenkanäle und der Stream-Ausgang liefern Live-RMS-/Peak-Messwerte mit Clipping-Hinweis. Solo schaltet andere Quellenkanäle temporär stumm, ohne deren gespeicherte Mute-Einstellungen zu überschreiben.

## Noch nicht angebunden

- Separater Anwendungs-Audiocapture unabhängig von der ausgewählten Fenster-/Bildschirmfreigabe
- Voice-Räume und die automatische Zuordnung externer Plattformereignisse zu Alert-Aktionen
- Native Geräteauswahl und separate Loopback-Kanäle pro Anwendung außerhalb des Capture-Tracks

## Gerätegrenzen und Status

- Physische Wiedergabe erfordert die Aktivierung des jeweiligen Ausgangs und hängt von `HTMLMediaElement.setSinkId`, Betriebssystem, Browser/Electron und Berechtigungen ab. Gerätewechsel werden über `devicechange` erkannt; aktive Ausgänge werden erneut verbunden, entfernte Geräte als nicht verfügbar markiert.
- „Systemstandard“ bestätigt kein bestimmtes physisches Gerät.
- Ein lokaler Encoder-Feed bestätigt weder RTMP-Serverempfang noch eine veröffentlichte LIVE-Ausgabe.
- Es wurden für diese Änderung keine manuellen Tests oder Hardware-/LIVE-Prüfungen gestartet; der PR bleibt deshalb Draft und unverifiziert.

Die Engine läuft lokal in der Electron-Regie. Sie benötigt keinen externen Dienst, kein Abo und keine OBS-Komponente.
