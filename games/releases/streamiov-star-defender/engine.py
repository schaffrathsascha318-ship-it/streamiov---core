"""Deterministic, dependency-free gameplay model for StreamioV Star Defender."""
from __future__ import annotations

from dataclasses import dataclass, field
import random


WIDTH = 800
HEIGHT = 600


@dataclass
class Entity:
    x: float
    y: float
    health: int = 1


@dataclass
class Game:
    """Small fixed-step arcade game model; rendering and input live in game.py."""

    seed: int | None = None
    width: int = WIDTH
    height: int = HEIGHT
    phase: str = "intro"
    score: int = 0
    lives: int = 3
    level: int = 1
    frame: int = 0
    player_x: float = WIDTH / 2
    player_y: float = HEIGHT - 65
    bullets: list[Entity] = field(default_factory=list)
    enemies: list[Entity] = field(default_factory=list)
    stars: list[Entity] = field(default_factory=list)
    blocked_keys: set[str] = field(default_factory=set)
    rng: random.Random = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.rng = random.Random(self.seed)
        if not self.stars:
            self.stars = [Entity(self.rng.randrange(self.width), self.rng.randrange(self.height))
                          for _ in range(90)]

    def start(self) -> None:
        if self.phase in {"intro", "game_over", "credits"}:
            self.reset()
            self.phase = "playing"

    def reset(self) -> None:
        self.score = 0
        self.lives = 3
        self.level = 1
        self.frame = 0
        self.player_x = self.width / 2
        self.player_y = self.height - 65
        self.bullets.clear()
        self.enemies.clear()

    def step(self, keys: set[str]) -> None:
        """Advance one 60 Hz step with normalized key names."""
        self.blocked_keys.intersection_update(keys)
        pressed = keys - self.blocked_keys
        if self.phase == "intro":
            if pressed & {"return", "space"}:
                self.start()
            return
        if self.phase == "credits":
            if pressed & {"return", "space"}:
                self.phase = "intro"
                self.blocked_keys.update(pressed & {"return", "space"})
            return
        if self.phase == "game_over":
            if "r" in pressed:
                self.start()
            elif "escape" in pressed or "return" in pressed:
                self.phase = "credits"
                self.blocked_keys.update(pressed & {"escape", "return"})
            return
        if "escape" in pressed:
            self.phase = "credits"
            self.blocked_keys.add("escape")
            return
        if "p" in pressed:
            self.phase = "paused" if self.phase == "playing" else "playing"
            return
        if self.phase == "paused":
            return

        self.frame += 1
        dx = int(bool(pressed & {"right", "d"})) - int(bool(pressed & {"left", "a"}))
        dy = int(bool(pressed & {"down", "s"})) - int(bool(pressed & {"up", "w"}))
        self.player_x = min(self.width - 25, max(25, self.player_x + dx * 6))
        self.player_y = min(self.height - 30, max(35, self.player_y + dy * 6))

        if "space" in pressed and self.frame % 9 == 0:
            self.bullets.append(Entity(self.player_x, self.player_y - 22))
        spawn_every = max(12, 38 - self.level * 2)
        if self.frame % spawn_every == 0:
            self.enemies.append(Entity(self.rng.randint(30, self.width - 30), -20,
                                       self.rng.choice((1, 1, 2))))

        for star in self.stars:
            star.y = (star.y + 2) % self.height
        for bullet in self.bullets[:]:
            bullet.y -= 10
            if bullet.y < -10:
                self.bullets.remove(bullet)

        for enemy in self.enemies[:]:
            enemy.y += 2 + min(4, self.level // 2)
            if abs(enemy.x - self.player_x) < 23 and abs(enemy.y - self.player_y) < 25:
                self.enemies.remove(enemy)
                self.lives -= 1
                if self.lives <= 0:
                    self.phase = "game_over"
                continue
            if enemy.y > self.height + 20:
                self.enemies.remove(enemy)
                continue
            for bullet in self.bullets[:]:
                if abs(bullet.x - enemy.x) < 18 and abs(bullet.y - enemy.y) < 18:
                    self.bullets.remove(bullet)
                    enemy.health -= 1
                    if enemy.health <= 0:
                        self.enemies.remove(enemy)
                        self.score += 10
                        self.level = 1 + self.score // 100
                    break

