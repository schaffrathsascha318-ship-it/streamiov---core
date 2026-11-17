# Streamiov: unabhängige Web-Grundlage

**Status:** vorbereitet, nicht produktiv aktiviert  
**Arbeitszweig:** `prep/independent-web-foundation`  
**Ziel:** Eine dauerhaft kostenlose Nutzung von Streamiov ermöglichen, ohne die Nutzerfinanzierung an kostenpflichtige Abos, Premium-Stufen oder künstliche Bezahlschranken zu koppeln.

## Verbindliche Architekturziele

1. Die öffentliche Streamiov-Webseite ist statisch und portabel (HTML, CSS, JavaScript, Medien und Downloads); sie darf keine Cloudflare-spezifische Laufzeit voraussetzen.
2. Domain und DNS bleiben logisch vom Hosting getrennt. DNS-Zonen und Records werden dokumentiert und exportierbar gehalten.
3. Das Hosting kann gewechselt werden, ohne URL-Struktur, Inhalte oder Build-Prozess neu zu entwickeln.
4. Die bestehende Seite unter `dist/streamiov-homepage-worker/public/` bleibt die Ausgangsbasis. Keine bestehende Veröffentlichung wird überschrieben, bis eine neue Variante geprüft und ausdrücklich freigegeben wurde.
5. Core, Konten, Uploads, LIVE, Videoverarbeitung und Community werden nicht als statische Webseite ausgegeben. Sie benötigen getrennte, sichere Backend-Dienste.
6. Keine Zugangsdaten, API-Tokens, privaten Schlüssel oder personenbezogenen Produktionsdaten in öffentliche Webseiten-Dateien oder Git-Historie schreiben.

## Vorgesehene öffentliche Adressen

Die folgenden Hostnamen sind Architekturvorschläge. Sie sind **nicht registriert, nicht auf DNS gelegt und nicht als verfügbar geprüft**.

| Hostname | Zweck | Startverhalten |
| --- | --- | --- |
| `streamiov.com` | Öffentliche Hauptseite | Statische Webseite |
| `www.streamiov.com` | Kanonische Weiterleitung auf Hauptseite | Redirect |
| `studio.streamiov.com` | Studio-Einstieg / Download / späterer Login | Nur tatsächlich verfügbare Funktionen anzeigen |
| `core.streamiov.com` | Öffentliche API-Basis | Erst aktivieren, wenn API und Authentifizierung geprüft sind |
| `community.streamiov.com` | Community-Einstieg | Vorschau bis zur produktiven Freigabe |
| `games.streamiov.com` | Spielekatalog | Nur veröffentlichte und geprüfte Spiele |
| `status.streamiov.com` | Dienststatus | Nur echte Health- und Verfügbarkeitsdaten |

## Hostingstrategie

### Phase A – sicherer Übergang
- Bestehende Veröffentlichung `https://streamiov.pages.dev/` unverändert weiterbetreiben.
- Die Website bleibt statisch und ohne zwingende Bindung an Workers, Functions, D1 oder proprietäre Build-Laufzeiten.
- Cloudflare Pages ist nur ein Übergangshost. Die dokumentierten Limits des Free-Tarifs sind einzuhalten.
- Build-Artefakte müssen unabhängig vom Anbieter lokal erzeugbar sein.

### Phase B – portable Bereitstellung
- Einen reproduzierbaren Build-Schritt für die statische Website dokumentieren.
- Deployment-Adapter getrennt vom Website-Inhalt halten.
- Einen zweiten Hostingweg in einer Vorschau testen, bevor ein Wechsel beschlossen wird.
- HTTPS, Redirects, Security-Header, Cache-Verhalten, Download-Prüfsummen und Wiederherstellung testen.

### Phase C – Anbieterunabhängigkeit
- DNS-Verwaltung außerhalb des Hosting-Anbieters ermöglichen, sofern der gewählte DNS-Anbieter dies unterstützt.
- Zonenexport, DNS-Änderungsprotokoll und dokumentierte TTL-/Rollback-Schritte pflegen.
- Keine produktiven DNS-Änderungen ohne Domaininhaber-Zugang und Freigabe.
- Für Backend-Dienste eigene, portable Container-/Servicepakete und Datenexporte vorsehen.

## DNS-Zielbild – nur Vorlage, nicht anwenden

| Typ | Name | Ziel | Hinweis |
| --- | --- | --- | --- |
| A / AAAA oder ALIAS | `@` | Ziel des ausgewählten Hostings | Erst nach Hostauswahl setzen |
| CNAME | `www` | `streamiov.com` oder Hostingziel | Redirect/Kanonisierung prüfen |
| CNAME | `studio` | Hostingziel | Erst bei fertiger Studio-Einstiegsseite |
| CNAME oder A/AAAA | `core` | API-Gateway | Nicht auf statisches Hosting zeigen |
| CNAME | `community` | Hostingziel | Erst bei fertiger Community-Seite |
| CNAME | `games` | Hostingziel | Erst bei veröffentlichtem Katalog |
| CNAME | `status` | Status-Hosting | Nur echte Statusdaten anzeigen |

Die tatsächlichen Records hängen vom Domain-Registrar, DNS-Anbieter und gewählten Hostingziel ab. Keine Platzhalterwerte veröffentlichen.

## Kosten- und Gratisversprechen

- Für Nutzer bleibt Streamiov nach Produktgrundsatz kostenlos: keine Abonnements, Premium-Stufen oder künstlichen Paywalls.
- Eine eigene `.com`-Domain ist normalerweise nicht dauerhaft kostenlos. Registrierung und Verlängerung müssen vor Kauf geprüft werden.
- Kostenlose Hostingtarife haben Limits, können Bedingungen ändern und sind keine unbegrenzte Betriebs- oder Verfügbarkeitsgarantie.
- LIVE-Video, Speicherung, Transcodierung, KI-Inferenz, Bandbreite, Missbrauchsschutz und Support verursachen reale Kosten.
- Deshalb darf Streamiov nicht behaupten, die gesamte Infrastruktur sei garantiert kostenlos. Das belastbare Versprechen lautet: keine verpflichtenden Nutzergebühren; Betrieb durch effiziente Technik, transparente Limits und nachhaltige Einnahmen finanzieren.
- Keine kostenpflichtigen Ressourcen, Domainkäufe, Tarifwechsel oder Werbeausgaben ohne ausdrückliche Freigabe.

## Sicherheits- und Freigabegrenzen

- Entwicklungsarbeiten, Dokumentation, lokale Builds und Tests dürfen auf diesem Vorbereitungszweig erfolgen.
- Keine produktive Domain registrieren, DNS-Zone ändern, Produktionsdeployment auslösen oder bestehende Pages-/Worker-Konfiguration ersetzen.
- Keine Secrets in Commits oder Logs.
- Vor einer Umschaltung: Backup, DNS-Export, TLS-Prüfung, Link-/Download-Prüfung, Verfügbarkeitstest und dokumentierter Rollback.
- Produktive Veröffentlichung bleibt owner-approved.

## Abnahmekriterien vor Aktivierung

- [ ] Domainname ausgewählt und Verfügbarkeit geprüft
- [ ] Preis für Erstregistrierung und Verlängerung geprüft und vom Eigentümer freigegeben
- [ ] Registrar und DNS-Anbieter ausgewählt; Inhaberzugang gesichert
- [ ] Statischer Build lokal reproduzierbar
- [ ] Zweites Hostingziel getestet
- [ ] HTTPS, Redirects und Security-Header geprüft
- [ ] Alle Downloadlinks und SHA-256-Prüfsummen geprüft
- [ ] Keine nicht fertigen Funktionen als live dargestellt
- [ ] Backup und Rollback getestet
- [ ] Explizite Freigabe für DNS-Änderung und Produktivumschaltung erteilt
