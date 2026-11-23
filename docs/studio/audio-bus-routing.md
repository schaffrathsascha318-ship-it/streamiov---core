# STREAMIOV Studio – unabhängige Audio-Busse

Die Regie enthält eine lokale Web-Audio-Engine mit vier voneinander getrennten logischen Ausgängen:

- **Stream / Programm** – eigener MediaStreamDestination-Bus als vorgesehener Encoder-Feed. Der Encoder ist in diesem Arbeitspaket noch nicht angeschlossen.
- **Monitor** – separat aktivierbare lokale Wiedergabe mit optionaler Auswahl eines Audioausgabegeräts.
- **Kopfhörer** – eigener Wiedergabestream und eigener Gain-/Mute-Regler.
- **Kommunikation** – eigener Wiedergabestream und eigener Gain-/Mute-Regler, standardmäßig ohne Quellenrouting.

## Aktuell angebundene echte Quellen

- Mikrofon: lokaler MediaStream mit eigenem Gain, Mute und auswählbaren Bus-Routen.
- Bildschirm-Systemton: wird nur dann als Quelle verbunden, wenn die ausgewählte Bildschirmfreigabe tatsächlich einen aktiven Audiotrack liefert.

Quellen-Gain und Ausgangs-Gain sind getrennte Stufen. Das Ändern oder Stummschalten eines Ausgangsbusses verändert nicht die Einstellungen der anderen Busse. Das Routing kann während der lokalen Vorschau angepasst werden.

## Gerätegrenzen und ehrlicher Status

- Physische Wiedergabe erfordert die Aktivierung des jeweiligen Ausgangs und hängt von HTMLMediaElement.setSinkId, Betriebssystem, Browser/Electron und Berechtigungen ab.
- „Systemstandard“ ist keine Bestätigung eines bestimmten physischen Geräts.
- Der Stream-Bus ist ein lokaler Audio-Stream, aber noch nicht mit dem Produktionsencoder verbunden.
- Musikplayer, Soundboard/Alerts, Spielton, TTS und Voice-Räume sind in diesem Arbeitspaket noch nicht an diese Bus-Matrix angeschlossen.
- Die Engine behauptet weder eine native Windows-Audiotreiberintegration noch eine verifizierte LIVE-Ausgabe.

Die Engine wird lokal in der Electron-Regie geladen. Sie benötigt keinen externen Dienst, kein Abo und keine OBS-Komponente.