# Streamiov Gift Creator – laufender Scheduler

## Was dieser Schritt tatsächlich bereitstellt

- Persistente, idempotente Planung eines wöchentlichen Batches aus drei Originalkonzept-Aufträgen.
- Saisonale Vorplanung anhand des rollierenden Vorschaufensters aus `ai/config/gift_creator_agent.json`.
- Weihnachts-/Winteraufträge werden 60 Tage vor dem Ereignis eingeplant (konfigurierbar).
- Aufträge laufen über die vorhandene SQLite-`SpecialistTaskQueue` und den vorhandenen least-privilege-`gifts`-Agenten.
- Wiederholte Scheduler-Aufrufe erzeugen für denselben Wochen-/Saison-Schlüssel keine neuen Duplikate.
- Automatische Veröffentlichung, Katalogaktivierung und TikTok-Einreichung sind ausdrücklich ausgeschlossen.

## Lokal starten

Voraussetzungen: Streamiov-Repository als `--project-root`, vorhandene Modellkonfiguration gemäß `ai/providers/local_http.py` und ein erreichbarer lokaler Modellserver oder der bereits konfigurierte Streamiov-Cloudflare-AI-Provider.

Einmaliger Funktionslauf:

```bash
python -m ai.runtime.gift_creator_daemon \
  --queue-db data/db/gift-creator-queue.sqlite3 \
  --schedule-db data/db/gift-creator-schedule.sqlite3 \
  --project-root . --once
```

Dauerbetrieb im Vordergrund:

```bash
python -m ai.runtime.gift_creator_daemon \
  --queue-db data/db/gift-creator-queue.sqlite3 \
  --schedule-db data/db/gift-creator-schedule.sqlite3 \
  --project-root . --poll-seconds 30
```

Der Prozess beendet sich kontrolliert mit SIGINT/SIGTERM. Für echten Dauerbetrieb muss er durch den jeweiligen Host-Supervisor (z. B. systemd oder einen vorhandenen Prozessmanager) gestartet und überwacht werden. Ein Merge oder Deployment dieses PR startet ihn nicht automatisch.

## Produktionsgrenzen – noch nicht fertig

Dieser Scheduler ist die Ablaufsteuerung, nicht die vollständige Geschenkfabrik. Noch zu implementieren und separat zu testen sind:

1. Ein echter 3D-Asset-Generator (glTF 2.0 oder gleichwertig), Material-/Rig-Erzeugung und individuelle Runtime-Animationen.
2. Renderer für Galerie-Thumbnail und Studio-Vorschau.
3. Asset-Speicher, Metadaten-/Versionsverwaltung und Duplikatprüfung auf gerenderten Geometrien/Animationen.
4. Eine Studio-Review-Oberfläche mit Freigabe, Ablehnung und Audit-Protokoll.
5. Host-Supervisor-Konfiguration, Monitoring, Backoff und Wiederanlauf für die Zielumgebung.

Die KI-Aufträge dürfen Produktionsbriefings und Entwürfe vorbereiten. Sie dürfen keine fertigen 3D-Assets vortäuschen, SVGs als 3D ausgeben oder Geschenke ohne menschliche Freigabe aktivieren/veröffentlichen. Die bestehende Rose bleibt unverändert.
