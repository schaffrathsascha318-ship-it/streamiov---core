"""Static contract tests for the Studio event ledger bridge."""
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STUDIO = ROOT / "dist" / "streamiov-studio-app"


class StudioEventContractTests(unittest.TestCase):
    def setUp(self):
        self.main = (STUDIO / "main.js").read_text(encoding="utf-8")
        self.preload = (STUDIO / "preload.js").read_text(encoding="utf-8")
        self.ui = (STUDIO / "regie-v2.html").read_text(encoding="utf-8")
        self.client = (STUDIO / "engine" / "studio-event-client.js").read_text(encoding="utf-8")

    def test_main_builds_events_without_renderer_controlled_fields(self):
        self.assertIn("const { createStudioEvent } = require('./engine/studio-event-client');", self.main)
        self.assertIn("ipcMain.handle('studio:event-publish'", self.main)
        self.assertIn("ipcMain.handle('studio:event-list'", self.main)
        self.assertIn("eventId: randomUUID()", self.main)
        self.assertIn("occurredAt: new Date().toISOString()", self.main)
        self.assertNotIn("options.source", self.main)
        self.assertNotIn("options.eventId", self.main)
        self.assertNotIn("options.occurredAt", self.main)

    def test_preload_exposes_only_narrow_event_methods(self):
        self.assertIn("eventPublish: (payload) => ipcRenderer.invoke('studio:event-publish'", self.preload)
        self.assertIn("eventList: (payload) => ipcRenderer.invoke('studio:event-list'", self.preload)
        self.assertIn("type: payload?.type", self.preload)
        self.assertIn("limit: Number.isInteger(payload?.limit) ? payload.limit : 50", self.preload)
        self.assertNotIn("event_id: payload", self.preload)
        self.assertNotIn("source: payload", self.preload)

    def test_regie_shows_core_ledger_and_only_labels_delivered_events(self):
        self.assertIn('id="eventLedger"', self.ui)
        self.assertIn('id="refreshEvents"', self.ui)
        self.assertIn("async function refreshEventLedger()", self.ui)
        self.assertIn("window.streamiovStudio?.eventList?.({limit:20})", self.ui)
        self.assertIn("CORE-EREIGNISPROTOKOLL · NICHT VERBUNDEN · lokales Log bleibt erhalten.", self.ui)
        self.assertIn("async function recordEvent(type,data={},severity=\"info\")", self.ui)
        self.assertIn("window.streamiovStudio?.eventPublish?.({type,data,severity})", self.ui)
        self.assertIn("Ereignis nur lokal: ", self.ui)
        self.assertIn('recordEvent("studio.scene.take"', self.ui)
        self.assertIn('recordEvent("studio.shield.changed"', self.ui)
        self.assertIn('recordEvent("studio.gameplay.observation"', self.ui)
        self.assertIn('recordEvent("studio.game.replay_marker"', self.ui)
        self.assertIn('recordEvent("studio.stream.started"', self.ui)
        self.assertIn('recordEvent("studio.stream.stopped"', self.ui)
        self.assertIn('recordEvent("studio.stream.started",{platform:platforms.join(","),localOnly:true})', self.ui)
        self.assertIn("async function stopBroadcast(preserveStatus=false,wasConfirmed=false)", self.ui)
        self.assertIn("Boolean(wasConfirmed||recorder||rendererOwnsStream)", self.ui)
        self.assertIn("stopBroadcast(true,true)", self.ui)
        self.assertIn("programSceneHasStaticVisualSource", self.ui)
        self.assertIn("runtimeEntries.some(entry=>sourceRuntimeHasStreamAudio(entry))", self.ui)
        self.assertIn("runtimeEndTargets", self.ui)
        self.assertNotIn("Veröffentlichung auf TikTok sind noch nicht bestätigt", self.ui)

    def test_client_contract_is_versioned_and_redacting(self):
        self.assertIn("const EVENT_SCHEMA_VERSION = 1;", self.client)
        self.assertIn("source: 'studio'", self.client)
        self.assertIn("SENSITIVE_KEY_PATTERN", self.client)
        self.assertIn("RTMP_PATTERN", self.client)
        self.assertIn("[RTMP-URL REDACTED]", self.client)
        self.assertIn("window.StreamioVStudioEventClient = api", self.client)
        for invalid in ("platform.gift", "twitch.gift", "live.confirmed"):
            self.assertNotIn(invalid, self.client)


if __name__ == "__main__":
    unittest.main()
