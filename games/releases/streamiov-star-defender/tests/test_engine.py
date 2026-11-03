import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import Entity, Game


class GameEngineTests(unittest.TestCase):
    def test_intro_start_and_pause_resume(self):
        game = Game(seed=1)
        game.step({"return"})
        self.assertEqual(game.phase, "playing")
        game.step({"p"})
        self.assertEqual(game.phase, "paused")
        frame = game.frame
        game.step({"space"})
        self.assertEqual(game.frame, frame)
        game.step({"p"})
        self.assertEqual(game.phase, "playing")

    def test_controls_stay_inside_playfield(self):
        game = Game(seed=2, player_x=30, player_y=40)
        game.phase = "playing"
        game.step({"left", "up"})
        self.assertGreaterEqual(game.player_x, 25)
        self.assertGreaterEqual(game.player_y, 35)
        game.player_x, game.player_y = 790, 590
        game.step({"right", "down"})
        self.assertLessEqual(game.player_x, game.width - 25)
        self.assertLessEqual(game.player_y, game.height - 30)

    def test_kill_scores_and_increases_difficulty_level(self):
        game = Game(seed=3)
        game.phase = "playing"
        game.frame = 8
        game.player_x, game.player_y = 400, 300
        game.enemies = [Entity(400, 270, 1)]
        game.step({"space"})
        self.assertEqual(game.score, 10)
        self.assertEqual(game.level, 1)
        game.score = 90
        game.frame = 8
        game.enemies = [Entity(400, 270, 1)]
        game.step({"space"})
        self.assertEqual(game.score, 100)
        self.assertEqual(game.level, 2)

    def test_player_collision_ends_round_and_restart_resets_state(self):
        game = Game(seed=4)
        game.phase = "playing"
        game.enemies = [Entity(game.player_x, game.player_y - 2)]
        game.step(set())
        self.assertEqual(game.lives, 2)
        game.lives = 1
        game.enemies = [Entity(game.player_x, game.player_y - 2)]
        game.step(set())
        self.assertEqual(game.phase, "game_over")
        game.step({"r"})
        self.assertEqual(game.phase, "playing")
        self.assertEqual(game.lives, 3)
        self.assertEqual(game.score, 0)

    def test_escape_shows_credits_and_enter_returns_to_title(self):
        game = Game(seed=5)
        game.start()
        game.step({"escape"})
        self.assertEqual(game.phase, "credits")
        game.step({"return"})
        self.assertEqual(game.phase, "intro")
        game.step({"return"})
        self.assertEqual(game.phase, "intro")
        game.step(set())
        game.step({"return"})
        self.assertEqual(game.phase, "playing")


if __name__ == "__main__":
    unittest.main()
