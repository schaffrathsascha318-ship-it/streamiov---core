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

## Release-Signatur ohne Zertifikatskauf

- Die Prüfsummen (`SHA256SUMS.txt`, `SHA256SUMS-games.txt`) sind mit einem projekt-eigenen Ed25519-Schlüssel signiert. Öffentlicher Schlüssel, Signaturdateien und Fingerabdruck liegen im Download-Bereich.
- Prüfen mit `node scripts/release-signing.mjs verify-release`; nach jeder Änderung an einer Datei schlägt die Prüfung fehl.
- Das ist eine Integritäts- und Herkunftssignatur, **keine** Windows-/macOS-Code-Signatur. SmartScreen-/Gatekeeper-Vertrauen bräuchte ein kostenpflichtiges Zertifikat einer Zertifizierungsstelle und wird nicht behauptet oder automatisch gekauft.

## Dauerhaft kostenlos

StreamioV bleibt ein kostenloses Angebot für alle: **keine Abos, keine Pro-Stufen, keine Werbung, keine Verkäufe und keine Zahlungspflicht**. Es gibt keine künstlichen Bezahlschranken und keinen automatischen kostenpflichtigen Fallback. Internet, Strom, Geräte und externe Plattformen haben eigene Bedingungen und können außerhalb StreamioVs Kosten verursachen.

## Promo und Quellcode

- Die Promo-Seite unter `https://streamiov.pages.dev/promo/` zeigt echte Screenshots der laufenden Web-Regie, einen kurzen Clip der Schutzregie und vorbereitete Social-Texte.
- Der Quellcode-Snapshot wird mit `scripts/build-source-snapshot.py` reproduzierbar aus den Repository-Quellen gebaut, in sieben größen- und SHA-256-geprüfte Teile zerlegt und im Download-Hub verlinkt. Ein erneuter Lauf auf demselben Commit erzeugt byte-identische Teile samt Prüfsummen.
- Der Snapshot enthält keine Zugangsdaten, Produktionsdatenbanken, Installer, Caches, binären Download-Artefakte oder generierten Download-Metadaten (Teile, Prüfsummen, `combine.js`, Download-Seite).

## Noch extern blockiert

- Ein real von einem Streamingdienst empfangener und veröffentlichter Livestream ist nicht nachgewiesen.
- TikTok-App-Review, genehmigte Scopes und offizielle Geschenk-Funktionen fehlen; es wird keine Freigabe behauptet.
- Erststart und Funktion auf echter Windows-, Linux-, Chromebook- und ARM-Hardware sind nicht vollständig geprüft.
- Code-Signierung/Notarisierung, eine eigene Domain und die vollständige Rechtsprüfung stehen aus.
- FFmpeg mit `libx264`, AAC und RTMP/RTMPS wird weiterhin separat auf dem Computer benötigt; es ist nicht gebündelt.

## Quellcode

Der aktuelle Quellcode-Snapshot liegt auf dem Download-Hub unter `https://streamiov.pages.dev/download/`.
