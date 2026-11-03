# StreamioV Studio 1.0.1

**Schutzregie / Privacy Shield ist jetzt in den Installern enthalten.**

## Neu

- **Schutzregie:** `Ctrl+Shift+P` oder der Button in der Übergangssteuerung schaltet das Programm sofort auf die eingebaute PAUSE-Szene und den lokalen Mikrofon-Mix auf 0 %.
- Beim Aufheben werden die vorherige Programmszene und der exakte Mikrofonpegel wiederhergestellt.
- Der Mikrofonregler ist während der Schutzregie gesperrt; TAKE ist gesperrt, solange die Schutzregie aktiv ist.
- Der Zustand wird lokal gespeichert und nach einem Neustart sicher wiederhergestellt.
- Die Web-Regie/PWA enthält die Schutzregie ebenfalls; dort bleiben Szenen- und Medienfunktionen ohne verbundenen Core als lokale Demo gekennzeichnet.
- Die Szenen-Engine kann die Programmszene direkt wechseln, ohne die Vorschau zu verändern.

## Ehrliche Grenze

Die Schutzregie stoppt **weder den Encoder noch eine laufende Aufnahme** und garantiert **keine Plattform-Privatsphäre**. Sie schaltet ausschließlich die Programmszene und den lokalen Mikrofon-Mix. Plattform- und Aufnahme-Privatsphäre müssen separat geprüft werden.

## Enthaltene Downloads

- Windows x64 und Windows ARM64 (NSIS)
- Linux x64 und Linux ARM64 (AppImage und DEB)
- `SHA256SUMS.txt` für alle veröffentlichten Dateien

ChromeOS/Crostini nutzt die Linux-DEB-Pakete. Die Web-Regie steht zusätzlich als PWA unter `https://streamiov.pages.dev/app/` bereit.

## Noch extern blockiert

- Ein real von einem Streamingdienst empfangener und veröffentlichter Livestream ist nicht nachgewiesen.
- TikTok-App-Review, genehmigte Scopes und offizielle Geschenk-Funktionen fehlen; es wird keine Freigabe behauptet.
- Erststart und Funktion auf echter Windows-, Linux-, Chromebook- und ARM-Hardware sind nicht vollständig geprüft.
- Code-Signierung/Notarisierung, eine eigene Domain und die vollständige Rechtsprüfung stehen aus.
- FFmpeg mit `libx264`, AAC und RTMP/RTMPS wird weiterhin separat auf dem Computer benötigt; es ist nicht gebündelt.

## Quellcode

Der aktuelle Quellcode-Snapshot liegt auf dem Download-Hub unter `https://streamiov.pages.dev/download/`.
