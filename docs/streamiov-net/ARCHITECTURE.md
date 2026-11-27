# STREAMIOV NET – Zielarchitektur

**Status:** Architekturentwurf – noch keine produktive Implementierung oder Abnahme  
**Ziel:** Ein eigenständiges, dauerhaft nutzbares digitales Ökosystem auf Basis des bestehenden Streamiov-Projekts.

## 1. Produktziel

STREAMIOV NET soll eigene digitale Dienste, Identitäten, Adressen, Kommunikation, Suche, Entwicklerwerkzeuge und Anwendungen bereitstellen. Es nutzt zunächst das vorhandene weltweite Internet als Transportnetz. Es ersetzt weder physische Netze noch globale Internet-Provider.

Langfristige Unabhängigkeit bedeutet:
- Streamiov kann seine Dienste auf eigener oder frei wählbarer Infrastruktur betreiben.
- Kein einzelner Cloud-Anbieter ist eine zwingende Architekturabhängigkeit.
- Daten und Dienste sind exportierbar und auf alternative Hosts migrierbar.
- Nutzergeräte und insbesondere das Chromebook des Eigentümers sind keine Produktionsserver.
- Externe Anbieter können austauschbare Transport- oder Infrastrukturadapter sein, nicht die unersetzliche Produktlogik.

## 2. Architekturprinzipien

1. **Bestehendes zuerst:** Vorhandene Core-, AI-, Studio-, Konto-, Forum- und Speicherkomponenten inventarisieren und wiederverwenden. Keine Parallelimplementierung ohne belegten Grund.
2. **Free-first:** Keine kostenpflichtige Ressource automatisch aktivieren. Quoten, Lastgrenzen und Betriebszustände transparent behandeln. Bei erschöpften kostenlosen Kapazitäten Aufgaben sicher puffern, drosseln oder pausieren.
3. **Portabilität:** Infrastrukturadapter hinter stabilen internen Schnittstellen; Konfiguration statt fest verdrahteter Anbieter-APIs.
4. **Offene Standards zuerst:** Bewährte Protokolle und geprüfte Open-Source-Bausteine verwenden. Eigene Protokolle nur bei konkretem Bedarf, dokumentierter Bedrohungsanalyse und Interoperabilitätstests.
5. **Sicherheit standardmäßig:** Least privilege, serverseitige Autorisierung, verschlüsselte Verbindungen, Secret-Trennung, Audit-Logs, Backups und Wiederherstellungstests.
6. **Nachweis statt Behauptung:** Ein Modul gilt erst nach passenden automatisierten und externen Tests als funktionsfähig.
7. **Sichere Änderungen:** Feature-Branches, Reviews, CI und Rollback. Produktive Daten, OAuth, TikTok-App-Einstellungen und Secrets bleiben geschützt.

## 3. Logische Ebenen

### A. Control Plane – Streamiov Core
- API-Einstieg und Dienstregistrierung
- Konten, Identitäten, Sitzungen und Berechtigungen
- interne Namens- und Dienstauflösung
- Konfiguration, Feature- und Kapazitätsstatus
- Ereignis- und Aufgabensteuerung
- Audit, Monitoring und Wiederherstellungskoordination

### B. Data Plane – Daten und Kommunikation
- relationale Daten und transaktionale Metadaten
- Datei-/Objektspeicher über austauschbare Adapter
- Nachrichten, Benachrichtigungen und Ereignisse
- Suchindex und öffentliches/internes Verzeichnis
- Export-, Backup- und Restore-Schnittstellen

### C. Execution Plane – Dienste und Agenten
- kurzlebige API-/Worker-Aufgaben
- persistente, wiederaufnehmbare Missionen
- isolierte Build- und Test-Runner
- Ressourcenquoten, Abbruch und Retry
- getrennte Entwicklungs-, Test- und Produktionsumgebungen

### D. Client Plane – Nutzergeräte
- Streamiov Studio als lokale Desktop-Regie
- Web-/PWA-Oberflächen und mobile Clients
- lokale Kamera-, Mikrofon-, Audio- und Gerätezugriffe
- Offline-Puffer und sichere Synchronisierung
- keine Pflicht, dass ein Client dauerhaft online bleibt

### E. Federation Plane – spätere Dezentralisierung
- optionale, ausdrücklich registrierte Community-/Partner-Nodes
- gegenseitige Authentifizierung und signierte Dienstmetadaten
- klar definierte Datenhoheit, Replikation und Widerruf
- Nodes sind optional; Kernfunktionen dürfen nicht von fremden Privatgeräten abhängen

## 4. Eigener Namensraum

Zunächst erhält Streamiov einen eigenen internen Namensraum für Dienste, Nutzerprofile und Ressourcen. Öffentlich erreichbare Dienste verwenden zunächst normale DNS-Domains und HTTPS. Eine eigene globale DNS-Wurzel oder ein Ersatz für das öffentliche Internet ist kein Startvoraussetzung und wäre ohne breite Interoperabilität nicht weltweit erreichbar.

Jede interne Adresse benötigt:
- eindeutige stabile ID
- lesbaren Namen/Alias
- Eigentümer und Zugriffsrichtlinie
- Dienst-/Ressourcentyp
- Versions- und Lebenszyklusstatus
- nachvollziehbare Auflösung und Widerrufsmöglichkeit

## 5. Anbieterunabhängigkeit

Cloudflare kann vorerst ein austauschbarer Host für bestehende Worker-/API-Komponenten bleiben. Die fachliche Logik darf jedoch nicht von Cloudflare-spezifischen Funktionen abhängen.

Jeder Infrastrukturadapter erhält:
- ein internes Interface und einen lokalen Testadapter
- einen dokumentierten Produktionsadapter
- Integrations- und Fehlerfalltests
- Export-/Migrationsweg
- klare Quoten- und Kostenkontrolle

Ein selbst betriebener Host oder ein anderer Anbieter darf später eingesetzt werden, ohne Konten, Identitäten oder fachliche Daten neu zu entwickeln.

## 6. Sicherheit und Datenschutz

- Passwörter nur mit etabliertem Passwort-Hashing; Sitzungen kurzlebig und widerrufbar.
- Service-zu-Service-Zugriff über eng begrenzte Identitäten.
- Keine Tokens, privaten Schlüssel oder personenbezogenen Laufzeitdaten in Git.
- Verschlüsselung bei Übertragung; Verschlüsselung ruhender Daten je nach Speicher- und Bedrohungsmodell.
- Backups regelmäßig erstellen und Restore tatsächlich testen.
- Rate Limits, Missbrauchsschutz, Protokollierung mit Datenminimierung.
- Datenexport, Löschfristen und Rechte pro Dienst festlegen.
- Eigene Kryptografie oder selbst erfundene Authentifizierungsverfahren vermeiden.

## 7. Umsetzungsreihenfolge

1. **Inventar und Ist-Zustand:** Core-API-Quelle, Worker-Konfiguration, Bindings, D1-Schema, Auth, Speicheradapter, AI-Auftragsroute, Deploy- und Recovery-Pfade prüfen.
2. **Core-Vertrag:** API-Versionierung, Identitätsmodell, Dienstregistrierung, Fehlerformat und Berechtigungsmodell dokumentieren.
3. **Persistenz:** Datenbankschema, Migrationen, Backup und Restore mit Testdaten nachweisen.
4. **Auftragsausführung:** AI-/Entwicklungsaufträge dauerhaft speichern, sicher einreihen, isoliert ausführen und wiederaufnehmen.
5. **Namensraum und Verzeichnis:** interne IDs, Aliase, Dienstauflösung und Berechtigungen umsetzen.
6. **Erste Net-Dienste:** Nutzerprofile, Verzeichnis/Suche und Nachrichten auf dem Core aufbauen.
7. **Portabilität:** zweiten lokalen oder alternativen Infrastrukturadapter als Migrationsnachweis testen.
8. **Federation:** optionale Nodes erst nach stabilen Identitäten, Signaturen, Widerruf und Replikationsregeln ergänzen.

## 8. Abnahmekriterien

STREAMIOV NET gilt nicht als betriebsbereit, bis mindestens Folgendes nachgewiesen ist:
- Core API extern erreichbar und mit Negativ-/Positivtests abgesichert
- Identitäten und serverseitige Berechtigungen funktionieren
- Datenbankmigration und Backup/Restore erfolgreich getestet
- Aufgaben überleben Prozessneustarts und werden nicht doppelt ausgeführt
- ein Dienst kann ohne Datenverlust auf einen anderen Host migriert werden
- Kosten-/Quotenlimits verhindern unbeabsichtigte Ausgaben
- Monitoring erkennt Fehler und dokumentiert Wiederherstellung
- produktive Dienste benötigen weder Chromebook noch GitHub als Laufzeitserver

## 9. Offene technische Prüfungen

Die Statusdokumentation vom 2026-11-03 nannte eine nicht produktiv verifizierte Core-API, einen AI-Auftrags-Endpunkt im Fail-Closed-Platzhalterzustand, nicht abgenommenen Remote-Speicher und fehlende Restore-Nachweise. Der aktuelle Quellstand zeigt dauerhaft gespeicherte, eigenerbezogene AI-Aufträge mit weiterhin nur lesender lokaler Inferenz, lokale OAuth-Routen mit dauerhaftem Rate-Limit sowie geprüfte lokale Backup-/Restore-Ketten; Produktions- und Remote-Abnahmen fehlen weiterhin. Diese Punkte müssen vor Implementierungsentscheidungen gegen die jeweils aktuelle Quelle und den aktuellen Status geprüft werden.

**Wichtig:** Dieses Dokument legt das Ziel fest. Es behauptet nicht, dass die beschriebenen Dienste bereits implementiert, deployed oder abgenommen sind.
