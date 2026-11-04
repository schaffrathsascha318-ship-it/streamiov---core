# Externe Abnahmeprüfung (Hardware, TikTok, Audio, Signierung)

Diese Datei ist die verbindliche Checkliste für die Punkte, die **nicht** in der
Entwicklungsumgebung geprüft werden können. Ein Punkt gilt erst als erledigt,
wenn er mit Datum, Gerät/Version, Commit und Nachweis dokumentiert ist. Bis
dahin bleibt er in `docs/STATUS.md` unter „Externally gated“ bzw. „Built, but
not verified on real target hardware“.

Grundregel: Ein erfolgreicher lokaler Start, ein grüner Test oder die Meldung
`Output #0, flv` im Encoder ist **kein** Nachweis, dass eine Plattform den
Stream angenommen oder veröffentlicht hat.

## Statusübersicht

| # | Punkt | Ohne wen nicht möglich | Status |
|---|-------|------------------------|--------|
| 1 | TikTok-Freigabe (App-Review, Scopes) | TikTok + Owner-Account | offen |
| 2 | Echter TikTok-LIVE-Broadcast | freigeschalteter LIVE-Zugang + Stream-Key | offen |
| 3 | Test auf echter Hardware | Windows-/Linux-/Chromebook-Geräte | offen |
| 4 | Vollständige Audioausgabe | Audio-Hardware + lokaler RTMP-Empfänger | offen |
| 5 | Code-Signierung | Zertifikat + Owner-Entscheidung | offen |

Empfohlene Reihenfolge: **4 → 3 → 1 → 2 → 5**. Audio und Hardware lassen sich
ohne TikTok-Freigabe prüfen; die Signierung ist eine Kosten-/Vertrauensfrage
und keine Funktion.

## Nachweisformat

Pro Test festhalten:

- Datum, Commit (`git rev-parse --short HEAD`), Studio-Version
- Gerät, Betriebssystem/Build, Installer-Dateiname und SHA-256
- Ergebnis pro Prüfschritt (bestanden/fehlgeschlagen) und Beobachtung
- Screenshot/Video oder Log-Auszug – **ohne** Stream-Keys, Tokens oder
  personenbezogene Daten
- Bei Audio: aufgezeichnete Datei plus `ffprobe`-Ausgabe

## 1. TikTok-Freigabe

Voraussetzung: bestehende App „Streamiov“ (App ID `7694133030948177927`),
keine neue App anlegen.

1. Im TikTok-Developer-Konsolen-Login den Status von Login Kit und
   `user.info.basic` prüfen.
2. Für LIVE relevante Produkte/Scopes nur über den offiziellen Review-Prozess
   beantragen. Nichts beantragen, was nicht gebraucht wird.
3. Genehmigte Scopes in `config/platforms/tiktok/oauth.json` auf `approved`
   bzw. `verified` setzen – nur wenn die Konsole das sichtbar bestätigt.
4. Produktions-Credentials getrennt von Sandbox halten und erst nach
   bestandenem Sandbox-Test aktivieren.

Bestanden, wenn: Die Konsole zeigt die Freigabe sichtbar, die Scopes sind
exakt dokumentiert, und es gibt keinen behaupteten Status ohne Screenshot.
Nicht bestanden, wenn: nur der Antrag gestellt wurde oder die Konsole
„pending“ zeigt.

## 2. Echter TikTok-LIVE-Broadcast

Voraussetzungen: freigeschalteter LIVE-Zugang, gültiger Stream-Key,
FFmpeg mit `libx264`, AAC und RTMP/RTMPS auf dem Testgerät.

1. Studio starten, Systemdiagnose öffnen und den FFmpeg-RTMP-Check auf grün
   prüfen.
2. Kamera und Mikrofon aktivieren, Szene wählen, Pegel prüfen.
3. RTMP-Ziel inklusive Stream-Key eintragen und Sendung starten.
4. Status muss auf „live“ wechseln. Parallel im TikTok-Creator-Center und in
   der TikTok-App prüfen, ob der Stream wirklich ankommt.
5. Mindestens 5 Minuten senden: Bild-Ton-Sync, Auflösung, Bitrate,
   Verbindungsabbrüche beobachten.
6. Sendung stoppen und prüfen, dass der Encoder sauber beendet und der Status
   „offline“ gemeldet wird.
7. Negativtest: falscher Stream-Key → verständliche Fehlermeldung, kein
   Absturz, kein Key in Logs oder Oberfläche.

Bestanden, wenn: Der Stream in der TikTok-App sichtbar ist, Ton und Bild
synchron ankommen, der Stopp sauber funktioniert und keine Zugangsdaten
geloggt werden. Nicht bestanden, wenn: nur FFmpeg „Output #0, flv“ meldet.

## 3. Test auf echter Hardware

Matrix (jeweils Installer-Hash vor der Installation prüfen):

- Windows x64 (NSIS) und Windows ARM64
- Linux x64 (DEB und AppImage) und Linux ARM64 (DEB und AppImage)
- Chromebook mit Crostini (Linux-DEB)

Pro Gerät zuerst einen Bericht erzeugen und an diesen Abschnitt anhängen:

```bash
python3 scripts/collect-hardware-report.py --markdown <installer-datei>
```

Der Bericht enthält OS/Build, CPU/RAM, Tool-Versionen, FFmpeg-Fähigkeiten,
Commit und Installer-SHA-256 – ohne Zugangsdaten oder Stream-Keys.

Dann:

1. `SHA256SUMS.txt` prüfen und Installer-Hash vergleichen.
2. Installieren, starten, Version 1.0.1 anzeigen lassen.
3. Kamera, Mikrofon und Bildschirmfreigabe erlauben; Geräteauswahl testen.
4. Szene wechseln, Quelle hinzufügen/entfernen, Einstellungen neu starten.
5. Schutzregie mit `Ctrl+Shift+P` an/aus: Szene → PAUSE, Mikrofon-Mix → 0 %,
   danach Rückkehr zu den vorherigen Werten.
6. RTMP-Check ausführen (ohne echten Stream).
7. Deinstallieren und prüfen, dass keine Reste oder offenen Prozesse bleiben.

Chromebook/Crostini: Audio- und Kameradurchreichung sowie
Fenstergröße/Fullscreen separat festhalten.

Bestanden, wenn: Installation, Erststart, Medienzugriff, Szenenwechsel,
Schutzregie und Deinstallation auf dem jeweiligen Gerät nachvollziehbar
funktionieren.

## 4. Vollständige Audioausgabe

Getestet wird die **gesendete** Audiospur, nicht nur der lokale Pegel.

Aufbau ohne Plattform (kostenlos, lokal) mit dem mitgelieferten Prüfwerkzeug:

```bash
# Startet den lokalen RTMP-Empfänger und prüft danach die Aufnahme mit ffprobe
python3 scripts/stream-audio-check.py
```

Danach in Studio `rtmp://127.0.0.1:1935/live/test` als Ziel verwenden, senden
und wieder stoppen. Das Skript beendet sich nach dem Stopp und meldet
`ok: true/false`. Eine vorhandene Aufnahme lässt sich erneut prüfen mit:

```bash
python3 scripts/stream-audio-check.py --analyze /tmp/stream-test.flv
```

Alternativ manuell:

```bash
ffmpeg -listen 1 -i rtmp://127.0.0.1:1935/live/test -c copy /tmp/stream-test.flv
```

Testmatrix:

1. Nur Mikrofon: Sprache deutlich hörbar, Pegel folgt dem Regler.
2. Nur Systemton: Musik/Testton hörbar (Systemfreigabe mit Audio erlauben).
3. Mikrofon + System: beide gleichzeitig, keine Verzerrung/Übersteuerung.
4. Master 0 % → Stille, Master 100 % → voller Pegel.
5. Schutzregie aktiv → Mikrofon stumm, Systemton bleibt gemäß Mixer.
6. 60 Sekunden aufnehmen: Bild-Ton-Sync, keine Aussetzer, kein Drift.

Auswertung:

```bash
ffprobe -hide_banner -show_streams -show_format /tmp/stream-test.flv
```

Bestanden, wenn: Beide Quellen im aufgezeichneten Stream ankommen, die Regler
und die Schutzregie wirken, AAC 48 kHz stereo vorliegt und Bild/Ton synchron
bleiben. Nicht bestanden, wenn: nur der lokale Meter ausschlägt, Systemton
fehlt oder der Ton nach einigen Minuten auseinanderläuft.

Bekannte Grenze: Systemton ist nur verfügbar, wenn das jeweilige Betriebssystem
ihn bei der Bildschirmfreigabe anbietet.

## 5. Code-Signierung und Release-Signatur

Ausgangslage: Die NSIS-/AppImage-Builds sind nicht mit einem
Zertifizierungsstellen-Zertifikat signiert; Windows SmartScreen und
Linux-Paketprüfungen können warnen. macOS wird derzeit nicht gebaut.

**Bereits selbst umgesetzt und kostenlos:** Die Prüfsummen-Dateien werden mit
einem projekt-eigenen Ed25519-Schlüssel signiert
(`scripts/release-signing.mjs`). Öffentlicher Schlüssel, Signaturen und
Fingerabdruck liegen unter `/downloads/`. Das ist eine
Integritäts-/Herkunftssignatur, **keine** Betriebssystem-Code-Signatur.

Prüfen:

```bash
node scripts/release-signing.mjs verify-release
node scripts/release-signing.mjs fingerprint
```

Bestanden (Projekt-Signatur): `verify-release` meldet `ok: true`, der
Fingerabdruck stimmt mit dem veröffentlichten Wert
`5aba9e30b37a060505470483673bf6b44b66e12bf050edb4fd57415f29f7d2bc`
überein, und nach einer Änderung an einer Datei schlägt die Prüfung fehl.

**Weiterhin offen (OS-Vertrauen):** Damit Windows SmartScreen oder macOS
Gatekeeper ohne Warnung vertrauen, ist ein Zertifikat einer Zertifizierungsstelle
nötig. Das kostet Geld und widerspricht dem Zero-Cost-Grundsatz; es wird nichts
automatisch gekauft. Alternativen sind eine selbst erzeugte, vom Nutzer manuell
installierte Vertrauensstellung (unüblich und warnungsanfällig) oder das
Akzeptieren der Warnung zusammen mit veröffentlichten Prüfsummen und
Signaturen.

Bestanden (falls je ein CA-Zertifikat beschafft wird): `signtool verify /pa`
bzw. `osslsigncode verify` erfolgreich, Inhaber und Zeitstempel korrekt, kein
Secret im Repository. SmartScreen-Reputation bleibt davon unabhängig.

## Was OpenCode dabei übernehmen kann

- Checklisten, Testbefehle und Auswerteskripte vorbereiten
- Logs und `ffprobe`-Ausgaben prüfen, ohne Secrets zu speichern
- Hashes, Builds und Dokumentation konsistent halten
- Ergebnisse in `docs/STATUS.md` und `docs/RELEASE_NOTES.md` nachtragen

Nicht möglich: Hardware anschließen, TikTok-Review erhalten, Zertifikate
kaufen. Diese Schritte bleiben beim Owner.
