"""Tests for external game orders from intake to a verifiable test build."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ai.game_studio.orders import (
    bind_task_workspace,
    create_order,
    order_summary,
)
from ai.game_studio.test_build import (
    TestBuildError,
    build_order_test_build,
    verify_order_test_build,
)
from tests.test_game_studio_orders import order


class GameOrderTestBuildTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.order_id = create_order(order(), self.root)["order_id"]
        self.workspace = self.root / "games" / "ai_created" / self.order_id
        self.build_dir = self.workspace / "test_builds" / "tb1"

    def tearDown(self):
        self.directory.cleanup()

    def bind(self):
        return bind_task_workspace(
            self.root, self.order_id, "build", "build-task-1",
            database_path=self.root / ".streamiov" / "workspaces.sqlite3",
        )

    def test_intake_to_bound_task_to_verified_test_build(self):
        bound = self.bind()
        self.assertEqual(bound["mission_id"], "build")
        self.assertEqual(bound["integration_status"], "pending")

        built = build_order_test_build(self.root, self.order_id, build_id="tb1")
        self.assertEqual(built["status"], "TEST_BUILD_CREATED")
        self.assertEqual(built["files"], 5)
        self.assertTrue((self.build_dir / "test-build-manifest.json").is_file())
        self.assertTrue((self.build_dir / (self.order_id + "-tb1-test-build.zip")).is_file())

        verified = verify_order_test_build(self.root, self.order_id, build_id="tb1")
        self.assertEqual(verified["status"], "TEST_BUILD_VERIFIED", verified)
        self.assertEqual(verified["errors"], [])
        self.assertIn("zip_integrity", verified["checks"])
        self.assertFalse(verified["claim_boundary"]["playability_verified"])
        self.assertFalse(verified["claim_boundary"]["release_ready"])
        self.assertFalse(verified["claim_boundary"]["published"])

        summary = order_summary(self.root, self.order_id)
        self.assertEqual(summary["mission_counts"]["verified"], 1)
        self.assertFalse(summary["published"])
        self.assertEqual(summary["independent_release_gate"], "not_recorded")

    def test_same_build_id_is_deterministic_and_requires_force_to_replace(self):
        first = build_order_test_build(self.root, self.order_id, build_id="tb1")
        with self.assertRaises(TestBuildError):
            build_order_test_build(self.root, self.order_id, build_id="tb1")
        again = build_order_test_build(self.root, self.order_id, build_id="tb1", force=True)
        self.assertEqual(first["package_sha256"], again["package_sha256"])

    def test_tampered_package_is_rejected(self):
        build_order_test_build(self.root, self.order_id, build_id="tb1")
        package = self.build_dir / (self.order_id + "-tb1-test-build.zip")
        package.write_bytes(package.read_bytes() + b"tamper")
        result = verify_order_test_build(self.root, self.order_id, build_id="tb1")
        self.assertFalse(result["ok"])
        self.assertIn("package_sha256_mismatch", result["errors"])
        self.assertEqual(order_summary(self.root, self.order_id)["mission_counts"]["blocked"], 1)

    def test_release_claim_in_manifest_is_rejected(self):
        build_order_test_build(self.root, self.order_id, build_id="tb1")
        manifest_path = self.build_dir / "test-build-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["published"] = True
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        result = verify_order_test_build(self.root, self.order_id, build_id="tb1")
        self.assertFalse(result["ok"])
        self.assertTrue(any("published" in item for item in result["errors"]))

    def test_cli_builds_and_verifies_test_build(self):
        commands = [
            [sys.executable, "-m", "ai.game_studio.test_build", "--repository-root", str(self.root),
             "--order-id", self.order_id, "--build-id", "tb1", "--build"],
            [sys.executable, "-m", "ai.game_studio.test_build", "--repository-root", str(self.root),
             "--order-id", self.order_id, "--build-id", "tb1", "--verify"],
        ]
        outputs = []
        for command in commands:
            completed = subprocess.run(command, cwd=Path(__file__).resolve().parents[1],
                                       capture_output=True, text=True, timeout=30)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            outputs.append(json.loads(completed.stdout))
        self.assertEqual(outputs[0]["status"], "TEST_BUILD_CREATED")
        self.assertEqual(outputs[1]["status"], "TEST_BUILD_VERIFIED")


if __name__ == "__main__":
    unittest.main()
