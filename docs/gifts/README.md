# Streamiov-Geschenke – ausschließlich TikToks offizielle LIVE-Geschenke-Galerie

## Verbindliche Eigentümerentscheidung (23.11.2026)
- Eigene Streamiov-Geschenke sind ausschließlich als originale Einreichungs-Assets für TikToks offizielle LIVE-Geschenke-Galerie vorgesehen.
- Ob TikTok eigene Drittanbieter-Geschenke unterstützt, welche Partner-/Creator-Bedingungen gelten und ob Streamiov zugelassen wird, muss über TikToks offiziellen Prozess bestätigt werden. Ohne ausdrückliche Freigabe gibt es keine Veröffentlichung und keine Verfügbarkeitsbehauptung.
- Zuschauer entdecken, wählen und senden Geschenke ausschließlich innerhalb von TikTok.
- Streamiov Studio ist keine zweite Geschenkebox: keine Geschenke-Galerie, kein Shop, Kaufbutton, eigene Währung/Punkte, Checkout, Zahlungsabwicklung, Geschenk-Ledger oder Auszahlungsfunktion.
- Studio darf ausschließlich echte, offiziell empfangene TikTok-Geschenkereignisse verarbeiten und darauf mit Alerts, Sounds, Overlays oder Animationen reagieren.
- Twitch Bits, Subs, Gift Subs und andere Twitch-Ereignisse bleiben native Twitch-Ereignisse und werden nicht in Streamiov-Geschenke umgewandelt.
- Keine Behauptung über TikTok-Preise, Coins, Gebühren, Creator-Auszahlungen oder eine 0%-Auszahlungsgarantie. Diese Regeln liegen bei TikTok und den jeweils geltenden Bedingungen.

## Legacy-Code und Daten
Die früheren STREAMIOV-internen Punkte-/GiftCatalog-/GiftLedger-Module und `data/game_actions/gift_catalog.json` sind historische Entwicklungsartefakte. Sie sind kein aktives Creator-Geschenkprodukt, dürfen nicht in der Studio-Regie als Geschenkebox angeboten und nicht mit TikTok-Geschenken oder TikTok-Coins gleichgesetzt werden. Sie bleiben bis zu einer gesonderten sicheren Daten-/Code-Migration unangetastet und gelten nicht als freigegebene Veröffentlichung.

Der alte `GiftEventRouter` akzeptiert nur intern signierte `STREAMIOV_NATIVE`-Events und weist TikTok-native Events ab. Er ist kein TikTok-Adapter und darf nicht als Beleg für offiziellen TikTok-LIVE-Geschenkzugriff verwendet werden.

## Technische Grenzen
Die vorhandene TikTok-App-Konfiguration mit `user.info.basic` beweist weder einen API-Zugriff auf LIVE-Geschenkereignisse noch eine Möglichkeit, eigene Geschenke in TikToks Galerie einzureichen. Keine Änderung an bestehendem OAuth-Client, Scopes, Sandbox oder Secrets ohne separate Freigabe.

## Abnahme
- [ ] Offiziellen TikTok-Einreichungs-/Partnerweg und Anforderungen dokumentiert.
- [ ] TikTok hat die Einreichung/Veröffentlichung für Streamiov tatsächlich freigegeben.
- [ ] Original-Assets und Rechte/Lizenzen sind dokumentiert.
- [ ] Studio enthält keine eigene Geschenkegalerie, Kauf-/Währungs-/Zahlungs-/Ledger-/Auszahlungsfunktion.
- [ ] Nur echte autorisierte TikTok-Geschenkereignisse lösen Studio-Reaktionen aus.
- [ ] Fehlende Freigabe/API wird als `BLOCKED / WAITING_FOR_TIKTOK_APPROVAL` angezeigt.
- [ ] Keine Tests oder Demo-Buttons simulieren Käufe, Coins, Auszahlungen oder echte TikTok-Geschenke.
