# STREAMIOV: die elf KI-Spezialisten

Der AI Chief Developer ist der übergeordnete Planer und Koordinator. Er zerlegt einen Auftrag in eigenständige Arbeitspakete und weist sie anhand ihrer fachlichen Verantwortung zu. Die elf Spezialisten sollen nicht dieselbe Aufgabe parallel wiederholen.

## Die elf Arbeitsbereiche

1. **Code & Product Engineering** – allgemeine Produktfunktionen, gemeinsame Verträge, Modulimplementierung und technische Refactorings, wenn kein spezialisierter Bereich der bessere Eigentümer ist.
2. **Studio & Broadcast Direction** – Electron-Studio, Regie, Szenen, Preview/Program/TAKE, Kamera, Quellen, Medienaufnahme und Geräteintegration.
3. **Music & Audio Systems** – Musikwiedergabe, Playlists, Audiodekodierung, Mixer, Busse, Routing, Monitoring und Audio-Geräte.
4. **Speech & TTS Systems** – deutsche Sprachausgabe, Stimmen, Aussprache, TTS-Warteschlangen, Unterbrechung, Lautstärke und Geschwindigkeit.
5. **Events, Alerts & Automation** – interne Ereignisse, TikTok-LIVE-Event-Mapping, Alerts, Trigger, Weiterleitung und reproduzierbare Event-Tests.
6. **Homepage & Download Delivery** – öffentliche Informationsseite, Downloadangebote, Betriebssystem-Auswahl, Release-Informationen und Download-Manifeste. Die Homepage ist kein Studio und kein Produktionshost.
7. **Backend, Core & Own Infrastructure** – Core-APIs, Datenbanken, Speicher, Netzwerk, Service Discovery, Backups, Observability und der stufenweise Aufbau eigener Streamiov-Infrastruktur.
8. **AI Research & Model Engineering** – Modell- und Laufzeitarchitektur, unabhängige Inferenzschnittstellen, lokale/self-hosted Modelle, Agentenarchitektur, Wissenssysteme, Evaluation und reproduzierbare Experimente.
9. **Game Development** – originäre Streamiov-Spiele, Gameplay, UI, Builds, Paketierung, Performance und Release-Nachweise.
10. **Gifts & Creator Economy** – eigenständige Streamiov-Geschenke, 3D-Assets, Animationen, Effekte, Geschenkdefinitionen und nachvollziehbare Event-/Abrechnungslogik.
11. **Quality, Verification & Security Testing** – unabhängige Teststrategie, Unit-/Integrations-/E2E-Tests, Regression, Build-Prüfung, Sicherheitsprüfung und evidenzbasierte Abschlusskontrolle.

## Zusammenarbeit und Aufgabentrennung

- Der Chief erstellt für jede Mission einen gemeinsamen Zielzustand und konkrete, voneinander abgrenzbare Lieferergebnisse.
- Jeder Spezialist erhält pro Planungszyklus höchstens ein Arbeitspaket. So bekommen die elf KIs unterschiedliche, klar abgegrenzte Lieferergebnisse statt mehrfach dieselbe Aufgabe. Weitere Arbeit desselben Spezialisten kommt in einen späteren Zyklus.
- Jeder Spezialist erhält nur Arbeitspakete, für die seine Fachverantwortung passt. Querschnittsarbeit wird ausdrücklich zugewiesen und mit den betroffenen Eigentümern abgestimmt.
- Parallel laufende Aufgaben müssen unterschiedliche Dateien oder klar definierte Schnittstellen besitzen. Bei unvermeidbaren Überschneidungen plant der Chief Reihenfolge und Integration.
- Spezialisten können projektweit implementieren, wenn die Aufgabe es erfordert. Fachverantwortung ist keine künstliche Dateisperre.
- Der Testing-Spezialist prüft Ergebnisse unabhängig und darf nicht seine eigene Implementierung als bestanden bestätigen.
- Fehler werden an den zuständigen Spezialisten zurückgegeben; der Chief koordiniert Reparatur, erneute Tests und Integration.
- Rollen, Prompts, Werkzeuge, Fähigkeiten und die Aufteilung der elf Arbeitsbereiche dürfen vom Chief weiterentwickelt oder neu geschrieben werden. Änderungen an der zentralen Berechtigungsdurchsetzung, Secrets, OAuth, Produktionszugängen sowie geschützten Workflow-/Runner-Kontrollen bleiben davon getrennt und benötigen die vorgesehenen Freigaben.

## Ehrliche technische Einordnung

Die elf Spezialisten sind derzeit elf getrennt konfigurierte Rollen und Arbeitsprofile innerhalb des gemeinsamen Modell-/Agenten-Runtimes. Das bedeutet nicht, dass bereits elf unabhängig gehostete oder separat trainierte Sprachmodelle laufen. Die Architektur soll die spätere getrennte Ausführung mit eigenen Modellkonfigurationen ermöglichen, wenn sie technisch und wirtschaftlich sinnvoll ist.

## Verbindliche Streamiov-Rahmenbedingungen

- Chromebook ist Entwicklungsgerät, kein Produktionshost.
- Streamiov Core und die langfristig eigene Infrastruktur werden serverseitig betrieben.
- TikTok LIVE ist die vorgesehene externe Streamingplattform; keine OBS-, Twitch-, YouTube-, Kick- oder Facebook-Adapter.
- Keine kostenpflichtigen Nutzerstufen, Abos oder künstlichen Paywalls.
- Open-Source-Bausteine sind nach Lizenz-, Sicherheits- und Wartbarkeitsprüfung zulässig.
- Produktivdeployments, öffentliche Veröffentlichungen, externe Konten, bezahlte Ressourcen und irreversible Aktionen benötigen weiterhin die vorgesehenen Freigaben.
