# STREAMIOV 2.0 – verbindliche Produkt- und Plattformgrenze

**Stand:** 18.11.2026  
**Status:** maßgebliche Produktvorgabe für neue Architektur- und Entwicklungsentscheidungen

Dieses Dokument konkretisiert die aktuelle Produktentscheidung. Bei Widersprüchen haben diese Vorgaben Vorrang vor älteren Masterplänen, README-Abschnitten, TikTok-spezifischen Studio-Konzepten oder historischen Implementierungsannahmen.

## 1. Eigenständige Plattform statt TikTok-Frontend

STREAMIOV 2.0 wird eine eigene, unabhängige Streaming- und Community-Plattform. TikTok ist weder die Streamingplattform von STREAMIOV noch eine notwendige Laufzeitabhängigkeit.

STREAMIOV besitzt und betreibt als eigene Produktbereiche:
- Benutzerkonten, Anmeldung, Sitzungen, Profile und Berechtigungen
- Live-Übertragung und Stream-Lifecycle
- Zuschauererlebnis und Zuschauerstatus
- integrierten Chat und Moderation
- Geschenke, Alerts, TTS und Interaktionen
- Games und Community-Funktionen
- Creator Studio, Regie, Szenen, Medien- und Audio-Pipeline
- zentrale Core/API-, Event-, Speicher- und Betriebsdienste

Externe Plattformen können später optionale, klar abgegrenzte Adapter erhalten. Sie dürfen weder das Datenmodell noch die Produktarchitektur bestimmen. Vorhandene TikTok-OAuth-, Event- oder sonstige Integrationen werden nicht ungeprüft gelöscht, deaktiviert oder umgebaut. Zuerst sind Zweck, Abhängigkeiten, Berechtigungen, Datenflüsse und Sicherheitsfolgen zu inventarisieren.

## 2. Zielarchitektur

### STREAMIOV Core
Der serverseitige Core ist die zentrale Instanz für Konten, Identitäten, Sessions, Rollen, Berechtigungen, Stream-Metadaten, Chat, Geschenke, Alerts, Community, Moderation, Event-Verarbeitung, APIs und persistente Daten. Autorisierungsregeln müssen serverseitig durchgesetzt werden; der Client darf sie nicht selbst festlegen.

### STREAMIOV Studio
Das Studio ist eine eigene Electron-Desktopanwendung und die lokale Regie. Es verantwortet lokale Geräte- und Medienzugriffe wie Kamera, Mikrofon, Bildschirm-/Spielaufnahme, Audio-Routing, Szenen, Preview/Program/TAKE und Encoder-Steuerung. Es verbindet sich authentifiziert mit dem Core. OBS ist keine Laufzeit- oder Frontend-Abhängigkeit.

Windows 11 x64 ist das primäre Desktopziel. Linux, ChromeOS und geeignete mobile Geräte bleiben zusätzliche Zielplattformen mit eigener Build- und Hardwareprüfung. Ein Chromebook ist Entwicklungsumgebung, kein Produktionsserver.

### Eigene Live-Übertragung
Die Plattform erhält einen eigenen Stream-Lifecycle mit Start, Verbindung, Live-Bestätigung, Zuschauerbeitritt, Status, Wiederverbindung, Ende und Fehlerzuständen. Ein UI-Status oder Szenenname darf niemals einen tatsächlich aktiven Stream vortäuschen. Ingest, Encoding, Weiterleitung/Distribution, Bandbreite, Skalierung, Missbrauchsschutz und Betriebskosten müssen vor einer Produktionsarchitektur technisch und wirtschaftlich geprüft werden. Keine kostenpflichtige Infrastruktur oder externe Veröffentlichung ohne Freigabe.

### Gemeinsame Ereignisarchitektur
Chat, Streamstatus, Zuschaueraktionen, Geschenke, Alerts, TTS, Games und Regie-Aktionen laufen über gemeinsame, versionierte Event-Verträge. Erforderlich sind mindestens:
- eindeutige Event-IDs und Idempotenz/Deduplizierung
- definierte Reihenfolge bzw. Zeitstempel und nachvollziehbare Korrelation
- serverseitige Validierung und Berechtigungsprüfung
- begrenzte Wiederholungen, Rate Limits und Schutz gegen Replay/Spam
- persistente, auditierbare Verarbeitung ohne Geheimnisse
- klare Fehler-, Retry- und Dead-Letter-Behandlung

Der Chat ist ein integriertes Kernmodul des Core und kein isoliertes Chatfenster.

## 3. Geschenke und finanzielle Schutzregeln

Streamiov-eigene visuelle Geschenke und Effekte sind von Geldgeschenken und externen Plattformgeschenken technisch und in der Oberfläche eindeutig zu unterscheiden.

Falls Geldgeschenke umgesetzt werden, gelten mindestens:
- maximal **500 € je Einzelgeschenk**
- eine zusätzliche monatliche Einzahlungs-/Aufladegrenze nur dann, wenn tatsächlich ein aufladbares Guthaben eingeführt wird
- ein verpflichtendes Streamiov-Wallet ist zu vermeiden, wenn direkte, sichere Zahlungsabläufe möglich sind
- Betrugsprävention, Rückabwicklung, Streitfälle, Alters-/Identitätsanforderungen, Empfängerprüfung, Gebühren und gesetzliche Pflichten müssen vor Aktivierung vollständig geprüft werden
- keine Zahlungsfunktion, Geldbewegung oder produktive Aktivierung ohne gesonderte technische, rechtliche und ausdrückliche Freigabe

Diese Vorgaben sind keine Behauptung, dass Zahlungsabwicklung bereits implementiert oder freigegeben ist.

## 4. Event Guard und Gewinnspiele

Vor Veröffentlichung müssen sowohl der Veranstalter als auch jedes einzelne Event geprüft werden. Die Prüfung umfasst – soweit für das Event relevant – Identität und Verantwortlichkeit des Veranstalters, verständliche Eventbeschreibung, Teilnahmebedingungen, Gewinnermittlung, konkreten Sach- oder Geldpreis, echte Gewinnfotos sowie Eigentums-/Verfügbarkeits- und Liefer-/Zahlungsnachweise.

Widersprüche, Manipulationshinweise oder fehlende wesentliche Nachweise führen zu einer Sperre bzw. manuellen Prüfung. Die KI darf keine fehlenden Belege erfinden und keine ungeklärten Verdachtsmomente als verifiziert einstufen. Prüfentscheidungen müssen mit Belegen, Zeitstempel und nachvollziehbarem Status dokumentiert werden.

## 5. Werbung und Sponsoring

- Keine automatische Werbung vor, während oder nach LIVE-Streams.
- Unternehmen können Werbevideos und Aufträge in einem separaten Streamiov-Werbemarkt anbieten.
- Streamer entscheiden freiwillig über Kooperationen.
- Ein dezentes Sponsor-Banner im Stream ist nur bei einer aktiven und gültigen Sponsoring-Kooperation zulässig, muss als Sponsoring gekennzeichnet sein und darf wichtige Inhalte, Chat oder Regie nicht verdecken.
- Keine Werbung darf stillschweigend in den Stream oder die Wiedergabe eingefügt werden.

## 6. Produkt- und Sicherheitsprinzipien

- Kernfunktionen bleiben dauerhaft ohne Abonnements, Pro-Stufen oder künstliche Bezahlschranken nutzbar.
- Bestehende Daten, Creator-Verbindungen, OAuth-Konfigurationen und funktionierende Integrationen werden vor jeder Migration inventarisiert und geschützt.
- Keine unkontrollierten Löschungen, Überschreibungen oder Datenmigrationen.
- Keine Secrets in Repository, Logs, Renderer oder Builds.
- Rollen, Rechte, Moderation, Rate Limits, Abuse-Schutz, Backups und Wiederherstellung gehören zur Plattformgrundlage.
- Externe Dienste und optionale Adapter dürfen den eigenen Kern nicht unbrauchbar machen, wenn sie ausfallen oder nicht freigegeben sind.
- Geplante, mock-basierte, implementierte, CI-geprüfte, hardware-geprüfte und produktiv verifizierte Funktionen sind strikt zu unterscheiden.
- Produktive Deployments, externe Veröffentlichungen, Zahlungen und sicherheitskritische Änderungen benötigen die jeweils erforderliche ausdrückliche Freigabe.

## 7. Migrations- und Entwicklungsreihenfolge

1. Repository, Issues, PRs, Datenbanken, Deployments und vorhandene TikTok-/OAuth-Komponenten vollständig inventarisieren.
2. Ist-Architektur und Abhängigkeiten dokumentieren; keine Altintegration vorschnell entfernen.
3. Zielverträge für Identität, Sessions, Core-API, Events, Chat, Live-Lifecycle und Berechtigungen definieren.
4. Core und zentrale Event-Verarbeitung implementieren und mit Regressionstests absichern.
5. Eigenen Live-Transport samt Betriebs-, Sicherheits- und Kapazitätsprüfung entwickeln.
6. Studio/Regie mit dem eigenen Core und der eigenen Live-Übertragung verbinden.
7. Chat, Zuschauer, Geschenke, Alerts, TTS, Games und Moderation als integrierte Module vervollständigen.
8. Event Guard, Sponsoring-Markt und weitere Community-Funktionen integrieren.
9. Hardware-, Last-, Sicherheits-, Wiederherstellungs- und Ende-zu-Ende-Prüfungen durchführen.
10. Erst nach unabhängiger Abnahme und ausdrücklicher Freigabe produktiv veröffentlichen.

Jede Phase muss konkrete Implementierungen, Tests, Dokumentation und belegte Akzeptanzkriterien liefern. Ein Research-Bericht oder grüner CI-Lauf allein bedeutet keine Fertigstellung.
