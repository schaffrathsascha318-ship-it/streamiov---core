import shutil
import unittest
from pathlib import Path

from ai.runtime.project_tools import ProjectTools


@unittest.skipUnless(shutil.which("node"), "Node.js is required for local browser-game tests")
class GamesSpecialistCheckTests(unittest.TestCase):
    def test_bounded_runner_audits_every_local_game_and_runs_its_tests(self):
        repository = Path(__file__).resolve().parents[1]
        tools = ProjectTools(
            repository,
            writable_prefixes=("games/", "tests/", "docs/"),
            allow_game_checks=True,
        )
        output = tools.run_game_checks()
        self.assertTrue(output.startswith("exit_code=0\n"), output)
        for game_id in (
            "streamiov-neon-relay",
            "streamiov-echo-grid",
            "streamiov-pulse-defender",
            "streamiov-signal-weave",
            "streamiov-star-defender",
        ):
            self.assertIn(game_id, output)
        self.assertIn("Node game tests: exit_code=0", output)


if __name__ == "__main__":
    unittest.main()
