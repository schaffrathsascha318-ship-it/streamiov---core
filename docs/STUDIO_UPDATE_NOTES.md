# StreamioV Studio 1.0.4

Kostenlose, installierbare Regie ohne Abo. Kein Browser-Studio und keine PWA als Ersatz.

- Windows x64/ARM64 als NSIS-Installer; Linux x64/ARM64 als AppImage und DEB; ChromeOS/Crostini über Linux-DEB, soweit die Umgebung sie unterstützt.
- Szenen- und Quellenmodell mit Vorschau, Programmausgabe, TAKE, lokalen Audio-Mixern und Übergängen.
- Lokale Aufzeichnung ohne RTMP mit Dateiansicht sowie Öffnen/Anzeigen/Löschen im Studio.
- Schutzregie: `Ctrl+Shift+P` fordert Stopp von Encoder und lokaler Aufzeichnung an, schaltet Programm auf PAUSE und lokales Mikrofon auf 0 %. Beim Aufheben kehren nur Szene und Mikrofonpegel zurück.
- Signierte Update-Manifeste mit Ed25519 und SHA-256 für unterstützte Installationsziele.

Grenzen: Ein Build ist kein Nachweis für echten Livestream, Hardware, Kamera- oder Plattformfunktion. Die Schutzregie garantiert keine Plattform-Privatsphäre. FFmpeg mit libx264, AAC und RTMP/RTMPS wird separat benötigt. Keine Behauptung von App-Review, TikTok-Freigabe, Code-Signatur oder vollständiger Gerätetests.
