# StreamioV Studio 1.0.4

**Nur installierbare Anwendungen. Kein Browser-Studio und keine PWA als Ersatz.**

## Enthalten

- Windows x64 und Windows ARM64 als NSIS-Installer
- Linux x64 und Linux ARM64 als AppImage und DEB
- ChromeOS x64/ARM64 über die Linux-DEB-Pakete unter Crostini, soweit die Umgebung sie unterstützt
- `SHA256SUMS.txt` für alle in diesem Release veröffentlichten Dateien
- `ffmpeg-source-bundle.tar.xz` als vollständiges, Corresponding-Source-Paket für die mitgelieferten GPLv3-FFmpeg-Binärdateien
- Signiertes `studio-update.json` mit Ed25519-Signatur für den Studio-Updateprüfer

Für macOS, Android, iPhone und iPad sind in diesem Release keine installierbaren Anwendungen enthalten. Eine Web-App oder PWA wird nicht als Ersatz angeboten; diese Ziele bleiben offen, bis eigene Builds und Gerätetests vorliegen.

## Verbesserungen seit 1.0.1

- **Schutzregie / Privacy Shield:** `Ctrl+Shift+P` oder der Button in der Übergangssteuerung fordert bei aktivem Stream den Stopp des lokalen Encoders und einer aktiven lokalen Aufzeichnung an, schaltet das Programm auf die eingebaute PAUSE-Szene und den lokalen Mikrofon-Mix auf 0 %. Beim Aufheben werden nur die vorherige Programmszene und der exakte Mikrofonpegel wiederhergestellt; der Broadcast startet nicht automatisch neu. Ein fehlgeschlagener Stopp wird protokolliert und muss manuell geprüft werden. Der Mikrofonregler bleibt während der Schutzregie gesperrt; TAKE ist gesperrt.
- **Gerätefähigkeiten:** Die Regie zeigt einen schreibgeschützten Bericht zu API-Verfügbarkeit und Layoutdichte. API-Vorhandensein oder `navigator.userAgent` werden nicht als geprüfte Gerätefähigkeit ausgegeben.
- **Programmausgabe:** Ein separates Fenster zeichnet die gespeicherte Szene auf einer lokalen 1280×720-Canvas. Der Status lautet ausdrücklich `LOKALE CANVAS · NOCH KEIN LIVE-VIDEO`; Kamera und Bildschirm sind dort Platzhalter.
- **Übergänge und Overlays:** Die Regie speichert CUT/FADE inklusive Dauer dauerhaft und blendet beim TAKE im lokalen Programmfenster und im Stream-Canvas nur bei echtem Szenenwechsel über. Standard- und eigene Overlays werden pro Szene gespeichert und in Vorschau, Programmausgabe und Stream-Canvas gezeichnet; Plattform-Live und echte Geräte bleiben ungeprüft.
- **Chief-Retry-Diagnose:** Fehlermeldungen aus Wiederholungen bleiben über Checkpoints erhalten und werden als nicht vertrauenswürdige Referenz genau einmal injiziert.
- **SQLite-Zustand:** `/healthz` und `/api/v1/status` melden beschädigte oder veraltete Stores als `degraded` statt Erfolg zu behaupten. Legacy-Forenspalten werden vor der Indexerzeugung migriert.
- **Native-only-Kurs:** Die generierte Browser-Regie, ihr Manifest, Service Worker und die zugehörigen Build-/Testskripte wurden entfernt. Die öffentliche Seite ist nur Informations- und Downloadseite.
- **Lokale Aufzeichnung:** Studio zeichnet Programm und Ton direkt im lokalen Prozess auf, ohne RTMP-Ziel. Aufzeichnungen werden im Studio aufgelistet und können geöffnet, im Dateimanager angezeigt und gelöscht werden; Pfad-Traversal wird abgewiesen.

## Ehrliche Grenzen

Die Schutzregie fordert den Stopp des lokalen Encoders und einer aktiven lokalen Aufzeichnung an und protokolliert das Ergebnis; ein fehlgeschlagener Stopp ist **kein** bestätigter Stopp. Sie startet danach nichts automatisch wieder und garantiert **keine Plattform-Privatsphäre**. Plattformseitige Erfassung bleibt außerhalb der Reichweite der lokalen Schutzregie.

Ein erfolgreicher Build ist kein Nachweis für eine funktionierende Live-Ausgabe. FFmpeg mit `libx264`, AAC und RTMP/RTMPS muss weiterhin separat installiert sein. Ein RTMP-Start beweist nicht, dass ein Dienst den Stream empfangen oder veröffentlicht hat.

Erststart und Funktion auf echter Windows-, Linux-, Chromebook- und ARM-Hardware sind nicht vollständig geprüft. Kamera-, Bildschirm-, Mikrofon-, GPU- und Encoding-Verhalten bleiben geräteabhängig. Ein real von einem Streamingdienst empfangener und veröffentlichter Livestream ist nicht nachgewiesen. TikTok-App-Review, genehmigte Scopes und offizielle Geschenk-Funktionen fehlen; es wird keine Freigabe behauptet.

## Signatur ohne Zertifikatskauf

- Die Prüfsummen (`SHA256SUMS.txt`, `SHA256SUMS-games.txt`) sind mit einem projekt-eigenen Ed25519-Schlüssel signiert. Öffentlicher Schlüssel, Signaturdateien und Fingerabdruck liegen im Download-Bereich.
- Prüfen mit `node scripts/release-signing.mjs verify-release`; nach jeder Änderung an einer geprüften Datei schlägt die Prüfung fehl.
- Das ist eine Integritäts- und Herkunftssignatur, **keine** Windows-/macOS-Code-Signatur. SmartScreen-/Gatekeeper-Vertrauen bräuchte ein kostenpflichtiges Zertifikat einer Zertifizierungsstelle und wird nicht behauptet oder automatisch gekauft.

## Klarstellung der Download-Texte

Homepage und Download-Hub bezeichnen die Spiel-Prototypen jetzt als Prototyp-Archive mit signierten Prüfsummen-Dateien statt als signierte ZIPs. Vier Archive sind Browser-Archive (HTML/JavaScript), eines benötigt Python 3 und Tkinter; der Quellcode-Snapshot ist vom 03.11.2026. Ein Installer oder ein automatischer Update-Kanal für die Spiele wird nicht behauptet.

## Dauerhaft kostenlos

StreamioV bleibt ein kostenloses Angebot für alle: **keine Abos, keine Pro-Stufen, keine Werbung, keine Verkäufe und keine Zahlungspflicht**. Es gibt keine künstlichen Bezahlschranken und keinen automatischen kostenpflichtigen Fallback. Internet, Strom, Geräte und externe Plattformen haben eigene Bedingungen und können außerhalb StreamioVs Kosten verursachen.

## Quellcode

Der Quellcode-Snapshot wird mit `scripts/build-source-snapshot.py` reproduzierbar aus den Repository-Quellen gebaut, in größen- und SHA-256-geprüfte Teile zerlegt und im Download-Hub verlinkt. Er ist kein Installer und enthält keine Zugangsdaten, Produktionsdatenbanken, Installer, Caches oder binären Download-Artefakte. Der Quellcode-Snapshot vom 03.11.2026 liegt unter `https://streamiov.pages.dev/download/`.
