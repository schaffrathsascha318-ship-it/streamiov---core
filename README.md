# STREAMIOV – Core

**Von Streamern für Streamer. Zum Nulltarif.**

Der vollständige STREAMIOV-Projektstand ist jetzt in diesem Standardbranch `main` integriert.
Der Integrations-Commit `ed075fb91667b573c9586fd57883db57b6b6e19a` verbindet die ursprüngliche
Repository-Historie mit dem vollständigen bisherigen Entwicklungszweig, ohne die Historie
per Force-Push zu ersetzen.

## Projektbereiche

- **Studio:** Electron-Desktop-Regie und Geräte-/Medienintegration.
- **Mobile und Chromebook:** gemeinsame installierbare Web-Regie/PWA unter `/app/`.
- **Core:** Plattformdienste, sichere Konten und Cloud-Anbindung.
- **Geschenke:** STREAMIOV-native Geschenklogik und getrennte Ledger-Basis.
- **Spiele:** eigenständige Spielebibliothek und kontrollierte Veröffentlichungen.

## Verbindliche Statusregeln

Ein grüner Build beweist nur, dass der Build erfolgreich war. Er beweist nicht automatisch,
dass ein Paket auf echter Hardware installiert wurde, dass Mediengeräte funktionieren oder
dass ein Live-Stream produktiv läuft. Solche Abnahmen werden separat dokumentiert.

Eine installierbare PWA ist keine native Android-APK oder iOS-App. Ein TikTok-Sandbox-OAuth-Test
ist keine echte TikTok-Autorisierung. Ein Geschenk-Ledger ist keine Zahlungsanbieter- oder
Auszahlungslösung.

Keine Zugangsdaten, Tokens oder privaten Schlüssel in Issues, Commits oder Chatnachrichten
einfügen.

## Sicherheit und Laufzeitdaten

Lokale Secrets, Token-Dateien, Wunschbox-Anfragen, Laufzeitprotokolle und PID-Dateien gehören
nicht in das öffentliche Repository. Die Ignore-Regeln sind dafür eingerichtet. Bereits
historisch eingecheckte Geheimnisse müssen unabhängig davon widerrufen/rotiert und ihre
Historie gesondert bereinigt werden.

## Gesamtprojekt und Abnahme

Der verbindliche Fertigstellungs- und Abnahmestand wird in
[Issue #3](https://github.com/schaffrathsascha318-ship-it/streamiov---core/issues/3) geführt.
Die verbleibenden Integrations- und Sicherheitsarbeiten sind dort einzeln dokumentiert.
