"""Tests for external game-order intake, isolation and publication gates."""
import json
import tempfile
import unittest
from pathlib import Path

from ai.game_studio.orders import (
    OrderIntakeError,
    authorize_publication,
    bind_task_workspace,
    create_order,
    missing_requirements,
    order_summary,
    record_client_approval,
    record_release_gate,
    record_rights_review,
    update_mission,
)


def order():
    return {
        "title": "Crystal Frontier",
        "genre": "3D action adventure",
        "vision": "Explore a living alien frontier and defend its settlements.",
        "core_gameplay": "Traversal, tactical combat and resource discovery.",
        "progression": "Unlock abilities and new regions through meaningful choices.",
        "art_direction": "Original stylized sci-fi world with readable silhouettes.",
        "audio_direction": "Adaptive orchestral-electronic score and spatial effects.",
        "accessibility": "Remappable controls, subtitles, scalable UI and difficulty aids.",
        "test_plan": "Automated gameplay simulation plus real device playthroughs.",
        "target_platforms": ["Windows 11 x64", "Linux x86_64", "Android ARM64"],
        "signature_mechanics": ["Gravity-shift traversal", "Reactive settlement defence"],
        "core_loop": ["Explore a region", "Discover resources", "Defend an outpost"],
        "level_plan": ["Frontier arrival", "Storm ravine", "Crystal citadel"],
        "controls": {"keyboard": "WASD move; mouse aim", "touch": "Virtual stick and action buttons"},
        "rights": {"original_concept": True, "third_party_components": []},
        "client": {"name": "Example Studio", "reference": "order-2026-01",
                   "confidential": True},
        "purpose": "Promotional mini game for a creator event.",
        "target_audience": "Twitch and TikTok viewers aged 16 and older.",
        "scope": "One playable vertical slice with three challenges.",
        "materials": ["Client logo supplied under written licence", "Original colour palette"],
    }


class GameOrderTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)

    def tearDown(self):
        self.directory.cleanup()

    def created(self, payload=None):
        result = create_order(payload or order(), self.root)
        self.assertEqual(result["status"], "WORKSPACE_CREATED")
        return result

    def test_incomplete_order_returns_targeted_questions_without_workspace(self):
        payload = order()
        for field in ("vision", "target_platforms", "client", "materials"):
            payload.pop(field)
        result = create_order(payload, self.root)
        self.assertEqual(result["status"], "NEEDS_INPUT")
        fields = {item["field"] for item in result["missing"]}
        self.assertTrue({"vision", "target_platforms", "client", "materials"}.issubset(fields))
        self.assertTrue(all(item["question"] for item in result["missing"]))
        self.assertFalse((self.root / "games" / "ai_created" / "crystal-frontier").exists())

    def test_non_original_order_is_rejected(self):
        payload = order()
        payload["rights"]["original_concept"] = False
        result = create_order(payload, self.root)
        self.assertEqual(result["status"], "REJECTED")
        self.assertFalse((self.root / "games" / "ai_created").exists())

    def test_workspace_is_isolated_with_permissions_missions_and_no_release_claim(self):
        result = self.created()
        target = self.root / result["workspace"]
        for name in ("design-brief.json", "order.json", "missions.json",
                     "progress.json", "access.json", "builder-audit.json"):
            self.assertTrue((target / name).is_file(), name)
        order_data = json.loads((target / "order.json").read_text())
        self.assertFalse(order_data["publication_approved"])
        self.assertFalse(order_data["published"])
        self.assertTrue(order_data["client"]["confidential"])
        access = json.loads((target / "access.json").read_text())
        self.assertFalse(access["external_actions_allowed"])
        summary = order_summary(self.root, result["order_id"])
        self.assertEqual(summary["mission_counts"]["pending"], len(
            json.loads((target / "missions.json").read_text())["missions"]))
        self.assertFalse(summary["published"])

    def test_missions_require_evidence_for_verification(self):
        order_id = self.created()["order_id"]
        with self.assertRaises(OrderIntakeError):
            update_mission(self.root, order_id, "graphics", "verified")
        self.assertEqual(update_mission(self.root, order_id, "graphics", "in_progress",
                                        actor="graphics-ki")["status"], "in_progress")
        update_mission(self.root, order_id, "graphics", "verified",
                       evidence_ref="reviews/graphics-assets.json", actor="qa")
        summary = order_summary(self.root, order_id)
        self.assertEqual(summary["mission_counts"]["verified"], 1)
        with self.assertRaises(OrderIntakeError):
            update_mission(self.root, order_id, "unknown", "verified", evidence_ref="x")

    def test_mission_uses_the_isolated_task_workspace_architecture(self):
        order_id = self.created()["order_id"]
        result = bind_task_workspace(
            self.root, order_id, "programming", "order-task-1", worker_id="code",
            database_path=self.root / "state" / "workspaces.sqlite3",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["integration_status"], "pending")
        self.assertTrue((self.root / result["workspace"]).is_dir())
        summary = order_summary(self.root, order_id)
        self.assertEqual(summary["mission_counts"]["in_progress"], 1)
        with self.assertRaises(OrderIntakeError):
            bind_task_workspace(self.root, order_id, "programming", "../escape",
                                database_path=self.root / "state" / "workspaces.sqlite3")

    def test_publication_is_blocked_until_all_independent_gates_exist(self):
        order_id = self.created()["order_id"]
        blocked = authorize_publication(self.root, order_id)
        self.assertEqual(blocked["status"], "PUBLICATION_BLOCKED")
        self.assertEqual(set(blocked["missing"]),
                         {"release_gate", "rights_approval", "client_approval"})
        record_release_gate(self.root, order_id, {
            "status": "RELEASE_REVIEW_READY", "release_ready": True,
            "independent_review_confirmed": True, "missing_gates": [],
        })
        record_rights_review(self.root, order_id, {
            "status": "approved", "reviewer": "rights-reviewer",
            "review_ref": "reviews/rights-2026-01.pdf",
            "asset_inventory": ["Client logo licence", "Original audio"],
        })
        record_client_approval(self.root, order_id, {
            "approved_by": "Example Studio Owner", "reference": "mail-2026-01",
            "scope": "Windows and Linux download, no store listing",
        })
        approved = authorize_publication(self.root, order_id)
        self.assertEqual(approved["status"], "PUBLICATION_AUTHORIZED")
        self.assertTrue(approved["approved"])
        self.assertFalse(approved["published"])
        summary = order_summary(self.root, order_id)
        self.assertTrue(summary["publication_approved"])
        self.assertFalse(summary["published"])
        self.assertEqual(summary["rights_status"], "approved")

    def test_invalid_release_gate_cannot_be_recorded(self):
        order_id = self.created()["order_id"]
        with self.assertRaises(OrderIntakeError):
            record_release_gate(self.root, order_id, {"release_ready": False})
        with self.assertRaises(OrderIntakeError):
            record_rights_review(self.root, order_id, {"status": "approved", "reviewer": "x"})

    def test_path_traversal_and_symlink_workspaces_are_rejected(self):
        self.created()
        with self.assertRaises(OrderIntakeError):
            order_summary(self.root, "../outside")
        with self.assertRaises(OrderIntakeError):
            update_mission(self.root, "../outside", "graphics", "pending")
        target = self.root / "games" / "ai_created" / "crystal-frontier"
        replacement = self.root / "elsewhere"
        replacement.mkdir()
        target.rename(replacement)
        target.symlink_to(replacement, target_is_directory=True)
        with self.assertRaises(OrderIntakeError):
            order_summary(self.root, "crystal-frontier")


if __name__ == "__main__":
    unittest.main()
