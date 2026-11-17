# Streamiov Domain- und Hosting-Checkliste

**Status:** Vorbereitung; keine Domain gekauft und keine DNS-Änderung durchgeführt.

## Vor dem Kauf

1. Wunschdomain bestätigen: bevorzugt `streamiov.com`.
2. Verfügbarkeit beim Registrar prüfen (Domainstatus, nicht nur eine Suchmaschinenanzeige).
3. Gesamtkosten für Erstregistrierung und Verlängerung prüfen; Aktionspreise nicht als Dauerpreis behandeln.
4. Registrar, DNS-Funktionen, Transfer-Lock, 2FA, Wiederherstellung und DNSSEC-Unterstützung vergleichen.
5. Eigentümer bleibt der Streamiov-Projektinhaber. Zugangsdaten und Wiederherstellungscodes niemals in Repository oder Chat hinterlegen.

## Vor der DNS-Konfiguration

- Hostingziel und dessen aktuelle Custom-Domain-Anleitung bestätigen.
- Bestehende DNS-Zone vollständig exportieren.
- MX-, TXT-, SPF-, DKIM-, DMARC- und Verifizierungsrecords nicht versehentlich entfernen.
- Apex-/Root-Domain-Verfahren (A/AAAA, ALIAS/ANAME oder Anbieter-spezifisch) prüfen.
- CNAME-Konflikte und TTL beachten.
- HTTPS-Zertifikat, HTTP-zu-HTTPS und www-/Apex-Weiterleitung prüfen.
- Rollback-Records bereithalten.

## Vor der Veröffentlichung

- Vorschau-URL testen.
- Mobilgeräte und Desktop testen.
- Accessibility, Ladezeit, Security-Header und kaputte Links prüfen.
- Download-Artefakte und Prüfsummen vergleichen.
- Status- und Produktreife-Angaben auf Wahrheitsgehalt prüfen.
- Erst danach Freigabe für DNS und produktive Veröffentlichung einholen.

## Nicht versprechen

- Kein kostenloser Domainkauf auf Dauer.
- Keine unbegrenzte kostenlose Bandbreite oder Speicherung.
- Keine garantierte 100-%-Verfügbarkeit durch einen Gratisanbieter.
- Keine kostenlosen LIVE-Transcodes oder KI-Rechenleistung ohne überprüfte Limits.
