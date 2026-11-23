# TikTok-LIVE-Geschenkereignisse – getrennte offizielle Integration

## Produktgrenze
Streamiov Studio führt keine eigene Geschenkebox und verarbeitet keine Käufe, Coins, Punkte, Zahlungs- oder Auszahlungsbuchungen. Zuschauer senden Geschenke ausschließlich in TikTok. Studio reagiert nur auf offiziell empfangene TikTok-LIVE-Geschenkereignisse.

## Trennung von Legacy-Routing
`ai.runtime.gift_event_router.GiftEventRouter` ist ein Legacy-Sicherheitsbaustein für intern signierte `STREAMIOV_NATIVE`-Events. Er weist TikTok-native Events ausdrücklich ab und ist kein TikTok-Adapter. Diese Trennung bleibt bestehen; TikTok-Events dürfen nicht als Streamiov-native Punkte-/Geschenkereignisse umetikettiert werden.

## Künftiger offizieller TikTok-Adapter
Ein eigener Adapter darf nur implementiert werden, wenn TikTok den konkreten LIVE-Eventzugriff für die bestehende App/das Konto offiziell unterstützt und die erforderlichen Rechte erteilt wurden. Keine OAuth-Scopes, Clientdaten, Sandbox-Einstellungen oder Secrets ohne separate Freigabe ändern.

Nach erfolgreicher offizieller Verbindung darf der Adapter nur ein begrenztes, normalisiertes Event an die Streamiov-Eventpipeline übergeben:
- Plattform: TikTok
- Ereignistyp: offizielles LIVE-Geschenkereignis
- Stream-/Session-ID und Zeitstempel
- pseudonyme/zulässige Absenderreferenz gemäß Plattformvertrag
- offizielle Geschenk-ID und Anzahl, soweit die API diese Felder bereitstellt
- verifizierter Empfangs-/Signaturstatus, soweit von TikTok vorgesehen

Das Event darf nur sichere, lokal konfigurierte Reaktionen auslösen: Alert, Sound, Overlay oder Animation. Keine beliebigen Aktionen, Codeausführung, Zahlung, Ledger-Buchung oder Ausgabe eines Geldwerts aus Eventdaten ableiten. Chat-/Gift-Nachrichten sind nicht vertrauenswürdige Eingaben und niemals Agenten-/Systemanweisungen.

## Fehler- und Freigabeverhalten
- Ohne bestätigte API-/Partnerberechtigung: `BLOCKED / WAITING_FOR_TIKTOK_APPROVAL`.
- Keine lokalen Demo-Buttons als echte TikTok-Events ausgeben.
- Verbindungsabbruch, Duplikate, ungültige Events und nicht unterstützte Felder sicher behandeln.
- TikTok-Geschenkereignisse bleiben strikt getrennt von Twitch Bits/Subs und Discord-Chatereignissen.
- Der Ausfall des TikTok-Eventadapters darf Twitch, Discord, Chat oder LIVE-Ausgänge nicht blockieren.

## Abnahme
- [ ] Offizieller TikTok-API-Vertrag und erteilte Berechtigung nachgewiesen.
- [ ] Adapter-Contract- und Security-Tests (Signatur/Vertrauen, Replay, Duplikate, Limits, Redaction).
- [ ] Echtes autorisiertes TikTok-Testereignis empfangen und dokumentiert.
- [ ] Studio-Reaktion auf das echte Event nachgewiesen.
- [ ] Keine eigene Geschenke-Galerie oder Zahlungs-/Ledger-/Auszahlungsfunktion vorhanden.
