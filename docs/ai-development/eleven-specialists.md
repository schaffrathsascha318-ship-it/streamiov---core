# STREAMIOV: die siebzehn KI-Agenten

Der AI Chief Developer ist der übergeordnete Planer und Koordinator. Er zerlegt einen Auftrag in eigenständige Arbeitspakete und weist sie anhand ihrer fachlichen Verantwortung zu. Die Agenten sollen nicht dieselbe Aufgabe parallel wiederholen.

## Die siebzehn Rollen

1. **AI Chief** – gemeinsames Ziel, Aufgabenteilung, Abhängigkeiten, Reparaturen, unabhängige Verifikation und Weiterarbeit am nächsten offenen Ziel.
2. **AI Architect** – Modulgrenzen, Schnittstellen, Datenverträge, Abhängigkeiten, Laufzeitarchitektur und Migrationspläne.
3. **AI Developer** – cross-cutting Umsetzung, Integration der Spezialistenarbeit und regressionssichere Codeänderungen.
4. **AI Code Agent** – konkrete Quellcodeänderungen, exakte Edits und reproduzierbare Testergebnisse.
5. **AI Repair Agent** – Diagnose und Reparatur verifizierter Fehler ohne Abschwächung von Tests oder Schutzmechanismen.
6. **AI Testing Agent** – unabhängige Testausführung und evidenzbasierte Abschlusskontrolle.
7. **AI Design Agent** – visuelle und Interaktionsgestaltung für native Studio-Oberflächen und öffentliche Seiten.
8. **AI Studio Agent** – natives Studio, Regie, Szenen, Quellen, Preview/Program/TAKE und getrennte LIVE-Output-Adapter.
9. **AI Audio Agent** – Audioaufnahme, Monitoring, Dekodierung, Mischung, Routing, Geräte und Stabilität.
10. **AI Music Agent** – Musikbibliothek, Warteschlangen, Playlists, Presets, Lizenzen und Wiedergabe.
11. **AI Games Agent** – originäre Streamiov-Spiele, Gameplay, Builds, Rechteprovenienz und Release-Nachweise.
12. **AI Mobile Agent** – ehrliche Android-/iOS-Machbarkeit, Gerätegrenzen, Packaging und Teststrategie.
13. **AI Gifts Agent** – eigenständige Streamiov-Geschenke für TikToks offizielle LIVE-Geschenke-Galerie, nur nach Freigabe.
14. **AI Integration Agent** – TikTok LIVE, Twitch LIVE, Discord-Community, lokale Host-APIs, Datenbanken und Event-Brücken.
15. **AI Security Agent** – Threat Models, Berechtigungsgrenzen, Secrets, OAuth-Trennung, Sandbox und Sicherheitsregressionstests.
16. **AI Release Agent** – native Installer, Versionen, Manifeste, Checksums, Lizenznachweise, Publish-Gates und Rollback.
17. **AI Support Agent** – Dokumentation, Download-Hilfe, troubleshooting und ehrliche Status-/Plattformangaben.

Zusätzlich bleiben die bestehenden Arbeitsrollen `code`, `studio`, `music`, `tts`, `events`, `homepage`, `server`, `research`, `game`, `gifts` und `testing` registriert, damit persistierte Missionen und bestehende Werkzeugaufrufe weiterhin funktionieren. Neue Missionen können die siebzehn expliziten Rollen verwenden.

## Zusammenarbeit und Aufgabentrennung

- Der Chief erstellt für jede Mission einen gemeinsamen Zielzustand und konkrete, voneinander abgrenzbare Lieferergebnisse.
- Jeder Agent erhält pro Planungszyklus höchstens ein Arbeitspaket. So bekommen die KIs unterschiedliche, klar abgegrenzte Lieferergebnisse statt mehrfach dieselbe Aufgabe.
- Jeder Agent erhält nur Arbeitspakete, für die seine Fachverantwortung passt. Querschnittsarbeit wird ausdrücklich zugewiesen.
- Parallel laufende Aufgaben müssen unterschiedliche Dateien oder klar definierte Schnittstellen besitzen.
- Agenten können projektweit implementieren, wenn die Aufgabe es erfordert. Fachverantwortung ist keine künstliche Dateisperre.
- Der Testing-Agent und der AI Testing Agent prüfen Ergebnisse unabhängig und dürfen nicht ihre eigene Implementierung als bestanden bestätigen.
- Ein Abschluss gilt nur mit tatsächlich ausgeführten Werkzeugen und beobachteten Testergebnissen. Models dürfen Ergebnisse nicht nur behaupten.
- Fehler werden an den zuständigen Agenten zurückgegeben; der Chief koordiniert Reparatur, erneute Tests und Integration.
- Rollen, Prompts, Werkzeuge, Fähigkeiten und Aufgabenteilung dürfen vom Chief weiterentwickelt werden. Änderungen an zentraler Berechtigungsdurchsetzung, Secrets, OAuth, Produktionszugängen sowie geschützten Workflow-/Runner-Kontrollen benötigen weiterhin Freigaben.

## Eigenständige Produktentwicklung und Integration

Der AI Chief arbeitet nicht nur eine statische Aufgabenliste ab. Er untersucht das Repository und den dokumentierten Produktzustand fortlaufend, erkennt fehlende Fähigkeiten, technische Schulden, Sicherheits- und Zuverlässigkeitsrisiken und erstellt daraus priorisierte Arbeitspakete.

Er darf neue Module, interne Dienste, Werkzeuge, Tests, Dokumentation, Build- und Diagnosefunktionen sowie Produktverbesserungen hinzufügen, wenn sie dem Streamiov-Ziel dienen. Ergebnisse müssen mit unabhängigen, beobachteten Tests belegt werden. Nach Abschluss einer Aufgabe beginnt er den nächsten sinnvollen, nicht blockierten Punkt.

Erfolgreich geprüfte Änderungen dürfen über den geschützten Integrationsworkflow in den Hauptzweig übernommen werden, sobald alle erforderlichen Prüfungen erfolgreich sind. Produktionsbereitstellungen und Releases dürfen nur über vorgesehene Deployment- und Release-Pipelines mit passenden Zugangsdaten, Prüfungen, Gesundheitskontrollen und Rollback-Möglichkeit erfolgen. Fehlende Zugangsdaten oder fehlende sichere Infrastruktur sind als Blockade zu melden, nicht zu umgehen.

## Ehrliche technische Einordnung

Die siebzehn Agenten sind derzeit getrennt konfigurierte Rollen und Arbeitsprofile innerhalb des gemeinsamen Modell-/Agenten-Runtimes. Das bedeutet nicht, dass bereits siebzehn unabhängig gehostete oder separat trainierte Sprachmodelle laufen. Die Architektur soll eine spätere getrennte Ausführung mit eigenen Modellkonfigurationen ermöglichen, wenn sie technisch und wirtschaftlich sinnvoll ist.

## Verbindliche Streamiov-Rahmenbedingungen

- Chromebook ist Entwicklungsgerät, kein Produktionshost.
- Streamiov Core und die langfristig eigene Infrastruktur werden serverseitig betrieben.
- TikTok LIVE und Twitch LIVE sind die beiden externen Streamingziele mit strikt getrennten Authentifizierungs- und Output-Adaptern. Discord ist ausschließlich Community-/Chat-Integration. Keine OBS-Abhängigkeit und kein kostenpflichtiger Multistream-Dienst.
- Eigene Streamiov-Geschenke sind ausschließlich für TikToks offizielle LIVE-Geschenke-Galerie vorgesehen und stehen unter TikToks Freigabe. Studio enthält keine eigene Geschenkegalerie, keinen Shop, Kauf-/Zahlungs-/Währungs- oder Auszahlungsfluss.
- Keine kostenpflichtigen Nutzerstufen, Abos oder künstlichen Paywalls.
- Open-Source-Bausteine sind nach Lizenz-, Sicherheits- und Wartbarkeitsprüfung zulässig.
- Produktivdeployments, öffentliche Veröffentlichungen, externe Konten, bezahlte Ressourcen und irreversible Aktionen benötigen weiterhin die vorgesehenen Freigaben.
