"""Contract tests for the Studio Wunschbox panel and its host bridge."""
import unittest
from pathlib import Path


class WishboxUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1] / "dist" / "streamiov-studio-app"
        cls.ui = (root / "regie-v2.html").read_text(encoding="utf-8")
        cls.main = (root / "main.js").read_text(encoding="utf-8")
        cls.preload = (root / "preload.js").read_text(encoding="utf-8")

    def test_panel_exposes_submission_status_and_actions(self):
        for marker in ('id="wishboxPanel"', 'id="wishboxText"', 'id="wishboxActionText"',
                       'id="wishboxAgent"', 'id="wishboxSubmit"', 'id="wishboxRefresh"',
                       'id="wishboxStatus"', 'id="wishboxOrders"', 'WUNSCHBOX · MUSIK &amp; SPIELE',
                       'function refreshWishbox()', 'function submitWishbox()',
                       'wishboxActionButton(order,"clarify"',
                       'wishboxActionButton(order,"complete"',
                       'await refreshEventLedger();'):
            self.assertIn(marker, self.ui)

    def test_bridge_is_narrow_and_sender_guarded(self):
        for marker in ("wishboxOrders:", "wishboxSubmit:", "wishboxAction:",
                       "wishboxHandoffs:", "authStatus:",
                       "studio:wishbox-orders", "studio:wishbox-submit",
                       "studio:wishbox-action", "studio:wishbox-handoffs", "studio:auth-status"):
            self.assertIn(marker, self.preload)
        self.assertIn("WISHBOX_ID_PATTERN", self.main)
        for marker in ("/api/v1/wishbox/orders", "/api/v1/wishbox/handoffs",
                       "/api/v1/auth/me", "studio:wishbox-orders",
                       "studio:wishbox-submit", "studio:wishbox-action",
                       "studio:wishbox-handoffs", "studio:auth-status",
                       "wishboxActionBody", "authRequired",
                       "'X-Streamiov-Client': STREAMIOV_CLIENT_HEADER"):
            self.assertIn(marker, self.main)
        self.assertNotIn("/api/ai/wunschbox", self.main)

    def test_game_boundary_is_not_broken(self):
        for forbidden in ("game-library-panel", "SPIEL ÖFFNEN", "listGames", "openGame"):
            self.assertNotIn(forbidden, self.main)
            self.assertNotIn(forbidden, self.preload)


if __name__ == "__main__":
    unittest.main()
