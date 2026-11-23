# STREAMIOV Studio – unabhängige Audio-Busse

Die Regie enthält eine lokale Web-Audio-Engine mit vier voneinander getrennten Ausgängen:

- **Stream / Programm** – eigener MediaStreamDestination-Bus, der in den lokalen MediaRecorder-/Encoder-Eingang eingespeist wird.
- **Monitor** – separat aktivierbare lokale Wiedergabe mit optionaler Auswahl eines Audioausgabegeräts.
- **Kopfhörer** – eigener Wiedergabestream und eigener Gain-/Mute-Regler.
- **Kommunikation** – eigener Wiedergabestream und eigener Gain-/Mute-Regler, standardmäßig ohne Quellenrouting.

## Angeschlossene Quellen

- **Mikrofon:** lokaler MediaStream mit eigenem Quellen-Gain, Routing und den zusätzlichen Mikrofon-Fadern.
- **Bildschirm-Systemton:** wird nur verbunden, wenn die ausgewählte Bildschirmfreigabe tatsächlich einen aktiven Audiotrack liefert.
- **Musik:** der lokale Musikplayer wird über eine MediaStream-Brücke in die Audio-Bus-Matrix eingespeist. Musik-Fader und Mute bleiben eigenständig; Stream- und Monitor-Routing laufen über die Busse.
- **Soundboard:** jedes geladene Pad erhält einen eigenen Kanal und wird über eine MediaStream-Brücke in Stream und Monitor geroutet. Pad-Lautstärke und Mute bleiben pro Datei unabhängig.
- **TTS:** die lokale deutsche espeak-ng-Ausgabe wird als WAV erzeugt und anschließend über einen eigenen TTS-Kanal in Stream und Monitor geroutet. Ein separater TTS-Fader sowie einstellbare Sprechgeschwindigkeit (80–300 Wörter/Minute) und Sprachlautstärke (0–200) sind vorhanden; Audioausgabe wird nicht allein durch den IPC-Erfolg als verifiziert markiert.
- **Alerts:** visuelle lokale Alerts erhalten zusätzlich einen kurzen generierten Zweiton-Alert über einen eigenen Stream-/Monitor-Kanal und einen separaten Alert-Fader. Plattform-Events lösen diese Alerts derzeit noch nicht automatisch aus.

Der Stream-Ausgang verwendet den Stream-Bus als Audioquelle und nicht mehr die bisherigen direkten Mikrofon-/Systemton-Eingänge. Der Stream-Audiomodus begrenzt, welche Live-Quellen in den Stream-Bus gelangen. Bus-Pegel und Bus-Mute wirken unabhängig von Quellen-Fadern.

## Noch nicht angebunden

- Spiel-/Desktop-Audio außerhalb des vom Bildschirmteilen gelieferten Systemtons
- Voice-Räume und die automatische Zuordnung externer Plattformereignisse zu Alert-Aktionen
- Native Windows-Audiotreiber-/Loopback-Routing außerhalb der vom Capture bereitgestellten Tracks

## Gerätegrenzen und Status

- Physische Wiedergabe erfordert die Aktivierung des jeweiligen Ausgangs und hängt von `HTMLMediaElement.setSinkId`, Betriebssystem, Browser/Electron und Berechtigungen ab.
- „Systemstandard“ bestätigt kein bestimmtes physisches Gerät.
- Ein lokaler Encoder-Feed bestätigt weder RTMP-Serverempfang noch eine veröffentlichte LIVE-Ausgabe.
- Es wurden für diese Änderung keine manuellen Tests oder Hardware-/LIVE-Prüfungen gestartet; der PR bleibt deshalb Draft und unverifiziert.

Die Engine läuft lokal in der Electron-Regie. Sie benötigt keinen externen Dienst, kein Abo und keine OBS-Komponente.
