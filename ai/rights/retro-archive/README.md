# Streamiov Retro-Archiv (1996–2026)

## Auftrag

Plattformübergreifend nach Spielen aus dem Zeitraum 1996 bis heute suchen, deren konkrete Bestandteile für Streamiov rechtmäßig archiviert und für eine Neuauflage genutzt werden dürfen. Hersteller und Plattformen umfassen ausdrücklich SEGA, Nintendo, Sony/PlayStation, Microsoft/Xbox, Atari, PC, Arcade und Handhelds.

Das Archiv ist ein Rechte- und Provenienzregister, kein ROM-Downloadverzeichnis. Es werden keine fremden ROMs, ISOs, BIOS-Dateien, Quellcodes oder Assets gespiegelt, solange die jeweilige Beschaffung, Speicherung und geplante Nutzung nicht belegt erlaubt ist.

## Aufnahmebedingungen

Ein Spiel wird erst als **RECHTE GEKLÄRT / ARCHIVIERBAR** markiert, wenn für jede benötigte Komponente und jede geplante Aktivität ein belastbarer Nachweis vorliegt. Das umfasst mindestens:

- Spielcode/Engine
- Grafiken, Figuren, Animationen und sonstige audiovisuelle Inhalte
- Musik, Soundeffekte und Sprachaufnahmen
- Titel, Logos, Marken und sonstige Kennzeichen
- Handbücher, Texte, Karten und Zusatzmaterial
- Drittanbieter-Middleware, Fonts und Bibliotheken

Ein öffentliches Repository, eine kostenlose Downloadmöglichkeit, ein eingestellter Betrieb, eine verwaiste Marke oder eine ausgelaufene Vertriebs-/Nutzungslizenz beweisen keine Gemeinfreiheit. Eine Code-Lizenz deckt nicht automatisch Assets, Musik, Marken oder Spieldaten ab. Rechteablauf und Lizenzfreigabe sind getrennte Rechtsgrundlagen und werden getrennt erfasst.

## Statuswerte

- `DISCOVERY`: Fund entdeckt, noch nicht geprüft.
- `SOURCE_VERIFIED`: offizielle/ursprüngliche Quelle geprüft.
- `CODE_LICENSE_VERIFIED`: Code-Lizenz und Umfang belegt.
- `ASSET_LICENSE_VERIFIED`: benötigte Asset-Rechte belegt.
- `PUBLIC_DOMAIN_VERIFIED`: Gemeinfreiheit für die konkreten Bestandteile und Nutzungsgebiete belegt.
- `RIGHTS_CLEARED`: alle für den konkreten Streamiov-Arbeitsauftrag benötigten Rechte geklärt.
- `PARTIAL_CLEARANCE`: nur bestimmte Bestandteile nutzbar; klare Allowlist.
- `BLOCKED`: Rechte unklar, widersprüchlich oder nicht ausreichend.
- `ARCHIVED`: rechtmäßig gesicherte Dateien mit Hash, Quelle und Lizenznachweis archiviert.
- `REMAKE_CANDIDATE`: zusätzlich als Remake/Remaster/3D-Modernisierung vorgemerkt.

Nur `RIGHTS_CLEARED` oder `PUBLIC_DOMAIN_VERIFIED` mit komponentenbezogener Freigabe dürfen in die Sicherungswarteschlange. `ARCHIVED` setzt einen erfolgreichen, rechtmäßigen Download/Import und Hashprüfung voraus. `REMAKE_CANDIDATE` setzt eine dokumentierte Freigabe für die geplante Bearbeitung voraus.

## Remake-Vormerkung

Für jeden freigegebenen Titel werden getrennt vorgemerkt:

- Original unverändert erhalten
- Restaurierung/Kompatibilitäts-Port
- Remaster
- Remake
- Fortsetzung/Erweiterung
- 2D-zu-3D-Neuentwicklung (echte 3D-Umgebung, Modelle, Kamera, Beleuchtung, Animation, Steuerung und Gameplay-Anpassung)
- Streamiov-eigene Neuinterpretation, falls nur Mechanik/Idee frei nutzbar ist

Eine offene Engine oder ein Source-Port ist nicht automatisch eine Freigabe für Originalspielinhalte. Bei unklaren Rechten wird stattdessen eine eigenständige Clean-Room-Neuentwicklung ohne geschützte Assets, Code, Figuren oder Marken geplant.

## Plattform- und Herstellerabdeckung

N64, PlayStation 1–5, SEGA Saturn/Dreamcast und weitere SEGA-Plattformen, GameCube/Wii/Wii U/Switch, Xbox-Generationen, Atari, PC, Arcade, Handhelds und Mobile (1996–2026). Die Plattformliste ist ein Suchraster, keine Rechteannahme.

## Recherchequellen und Grenzen

Startpunkte für Discovery (keine pauschalen Rechtefreigaben):

- [Awesome Open Source Games](https://github.com/smshahbaj/awesome-open-source-games) – kuratierter Index, trennt Spiele, Reimplementierungen, Engines und Tools.
- [OpenSourceVideoGames/list](https://github.com/OpenSourceVideoGames/list) – breite Fundstellenliste, jede Projektlizenz einzeln prüfen.
- [Trilarion/opensourcegames](https://github.com/Trilarion/opensourcegames) – technische Datenbank und Hinweise auf Wiederbelebung inaktiver Projekte; Einträge unabhängig verifizieren.
- [Commercial games with later released source code](https://en.wikipedia.org/wiki/List_of_commercial_video_games_with_later_released_source_code) – nur Recherchehinweis; Leaks und unklare Veröffentlichungen ausdrücklich ausschließen.
- [Free Game Dev Assets](https://github.com/TMHSDigital/Free-Game-Dev-Assets) – nur Asset-Quellen, keine automatische Freigabe für ein bestimmtes Spiel.

Die Listen sind Discovery-Einstiege. Vor jeder Übernahme wird die kanonische Quelle (Rechteinhaber/Entwickler/Original-Repository/amtliches Register) geöffnet und der Lizenztext in der zum Zeitpunkt der Prüfung geltenden Fassung dokumentiert.

## Archivablage

Nach Freigabe werden Dateien nach Plattform und Titel abgelegt, zum Beispiel:

`archive/<platform>/<title-slug>/original/`
`archive/<platform>/<title-slug>/source/`
`archive/<platform>/<title-slug>/assets/`
`archive/<platform>/<title-slug>/documentation/`
`archive/<platform>/<title-slug>/provenance/`

Keine Archive werden in Git eingecheckt, wenn sie groß, binär, redistributiv unklar oder nicht für öffentliche Ablage freigegeben sind. In Git liegen zunächst nur Metadaten, Lizenzbelege/URLs, Prüfsummenmanifest und KI-Aufträge. Binärdateien werden nur in einen dafür vorgesehenen, zugriffsgeschützten Speicher kopiert, wenn die Lizenz das erlaubt.

## Pflichtfelder je Eintrag

Siehe `catalogue.schema.json` und `catalogue.json`. Kein Eintrag darf ohne Quell-URL, Zugriffsdatum, Lizenztext/Beleg, Komponenten-Scope, Gebiete, erlaubte Aktivitäten, Einschränkungen und Review-Status auf freigegeben gesetzt werden.


## Rechte-Akquise statt Unternehmenskauf

Streamiov verfolgt standardmäßig keinen Kauf ganzer Studios oder Spielekataloge. Ziel ist die gezielte, schriftliche Entwicklungs- und Veröffentlichungserlaubnis der aktuellen Rechteinhaber oder autorisierten Rechtsnachfolger für Remakes, Remaster, Ports, Fortsetzungen und echte 2D-zu-3D-Neuentwicklungen. Inaktive, eingestellte, delistete oder vergessene Spiele werden als Erwerbs-/Verhandlungskandidaten aufgenommen; dieser Zustand begründet für sich allein keine Nutzungsrechte. Verstorbene Urheber, geschlossene Studios und nicht auffindbare Ansprechpartner lösen eine Recherche der Erben, Rechtsnachfolger und Rechtekette aus – keine automatische Freigabe.

Der vollständige Ablauf, die Statuswerte, Rechteinhaber-Recherche und Dossier-Vorlage stehen in [RIGHTS_ACQUISITION_PIPELINE.md](./RIGHTS_ACQUISITION_PIPELINE.md).
