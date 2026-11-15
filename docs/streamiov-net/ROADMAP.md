# STREAMIOV NET – Arbeitsplan und Abnahme

Dieser Plan ergänzt die Zielarchitektur in [ARCHITECTURE.md](ARCHITECTURE.md). Er ist ein Arbeitsplan, keine Fertigmeldung.

## Arbeitsblock 0 – sichere Bestandsaufnahme
- [ ] Quellpfad und Konfiguration der Core API finden
- [ ] Tatsächliche Deployments und öffentliche Health-Endpunkte prüfen
- [ ] D1-Bindings, Tabellen, Migrationen und Datenflüsse inventarisieren
- [ ] Konto-/Session-/Autorisierungsimplementierung prüfen
- [ ] Storage-Adapter und Remote-Implementierungen prüfen
- [ ] AI-Task-Route und tatsächlichen Runner-Pfad verfolgen
- [ ] Secrets nur nach Namen/Existenz inventarisieren; niemals Werte ausgeben
- [ ] offene lokale Änderungen und Branches berücksichtigen

**Abnahme:** nachvollziehbare Komponentenmatrix mit Datei-/Testbelegen, Risiken und konkreten Blockern.

## Arbeitsblock 1 – Core-Verträge
- [ ] Versionierte interne API-Verträge
- [ ] stabile Fehlerantworten und Request-IDs
- [ ] Dienstregistrierung und Health-/Readiness-Verträge
- [ ] einheitliche serverseitige Identitäts- und Berechtigungsprüfung
- [ ] Audit-Events ohne Secrets oder unnötige personenbezogene Daten

**Abnahme:** Contract-Tests und Negativtests für unberechtigte Zugriffe.

## Arbeitsblock 2 – persistente Datenbasis
- [ ] versionierte Datenbankmigrationen
- [ ] getrennte Testdatenbank
- [ ] Backup- und Restore-Befehl
- [ ] Integritätsprüfung nach Restore
- [ ] Datenexport in dokumentierten Formaten

**Abnahme:** Wiederherstellung in eine leere Testumgebung mit belegter Datenintegrität.

## Arbeitsblock 3 – Aufgaben- und Agentenlaufzeit
- [ ] dauerhafte Queue und Missionszustände
- [ ] Idempotenz, Lease/Timeout, Retry und Abbruch
- [ ] isolierte Runner mit minimalen Rechten
- [ ] Checkpoints und Wiederaufnahme nach Neustart
- [ ] unabhängige Qualitätsprüfung und Ergebnisbericht

**Abnahme:** derselbe Auftrag wird nach Runner-Neustart sicher fortgesetzt; keine Doppelverarbeitung und keine Secret-Ausgabe.

## Arbeitsblock 4 – erste Streamiov-Net-Dienste
- [ ] interne Identitäten und Aliase
- [ ] Dienst-/Ressourcenverzeichnis
- [ ] Nutzerprofile und Berechtigungen
- [ ] Such-/Verzeichnisdienst
- [ ] Nachrichten-/Ereignisgrundlage

**Abnahme:** echte Ende-zu-Ende-Tests über die öffentliche Core-API.

## Arbeitsblock 5 – Portabilität und Unabhängigkeit
- [ ] Anbieteradapter hinter internen Schnittstellen
- [ ] lokaler Ersatzadapter für Entwicklung und Tests
- [ ] dokumentierter Datenexport
- [ ] Migrationstest zu einem zweiten Host
- [ ] Wiederanlauf- und Rollback-Test

**Abnahme:** ein Dienst und seine Daten werden ohne Anbieter-spezifische Datenverluste migriert.

## Sicherheits- und Veröffentlichungsregeln
- Arbeit zunächst auf Feature-Branches.
- Keine produktiven Datenbanken als Testumgebung verwenden.
- Keine Secrets, OAuth-Tokens oder privaten Schlüssel lesen/ausgeben/committen.
- Keine kostenpflichtigen Ressourcen aktivieren oder Kosten auslösen.
- Keine Änderungen an TikTok-App, OAuth, produktiven Credentials oder Kontosicherheit ohne separate Freigabe.
- Keine produktiven Deployments aus diesem Architekturstart.
- Bestehende Änderungen erhalten; keine blinden Überschreibungen.
- Tests und externe Abnahmen getrennt dokumentieren.
