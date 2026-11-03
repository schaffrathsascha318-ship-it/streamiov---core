"""StreamioV Star Defender. Run with: python3 game.py"""
from __future__ import annotations

import tkinter as tk

from engine import Game, HEIGHT, WIDTH


BG = "#070b16"
CYAN = "#42e8ff"
MINT = "#74ffd1"
VIOLET = "#a88bff"
WHITE = "#f4f7ff"


class StarDefender:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("StreamioV Original — Star Defender")
        self.root.geometry("960x720")
        self.root.minsize(640, 480)
        self.root.configure(bg=BG)
        self.canvas = tk.Canvas(self.root, width=WIDTH, height=HEIGHT, bg=BG,
                                highlightthickness=0, takefocus=True)
        self.canvas.pack(fill="both", expand=True)
        self.game = Game()
        self.keys: set[str] = set()
        self.root.bind("<KeyPress>", self.on_key_down)
        self.root.bind("<KeyRelease>", self.on_key_up)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.draw()
        self.root.after(16, self.tick)

    def close(self) -> None:
        if self.game.phase in {"playing", "paused"}:
            self.game.phase = "credits"
        self.root.destroy()

    def on_key_down(self, event: tk.Event) -> None:
        key = event.keysym.lower()
        if key in self.keys:  # Ignore OS key-repeat events for edge-triggered actions.
            return
        self.keys.add(key)
        if key == "p" and self.game.phase in {"playing", "paused"}:
            self.game.step({"p"})

    def on_key_up(self, event: tk.Event) -> None:
        self.keys.discard(event.keysym.lower())

    def tick(self) -> None:
        self.game.width = WIDTH
        self.game.height = HEIGHT
        # P toggles on key-down only; holding it must not toggle every frame.
        self.game.step(self.keys - {"p"})
        self.draw()
        self.root.after(16, self.tick)

    def draw(self) -> None:
        c = self.canvas
        c.delete("all")
        for star in self.game.stars:
            c.create_oval(star.x, star.y, star.x + 2, star.y + 2, fill="#607397", outline="")
        if self.game.phase in {"playing", "paused"}:
            self.draw_world()
        else:
            self.draw_title()
        self.scale_to_window()

    def draw_world(self) -> None:
        c, game = self.canvas, self.game
        for bullet in game.bullets:
            c.create_rectangle(bullet.x - 3, bullet.y - 9, bullet.x + 3, bullet.y + 9,
                               fill=CYAN, outline="")
        for enemy in game.enemies:
            x, y = enemy.x, enemy.y
            c.create_polygon(x, y + 14, x - 15, y - 10, x, y - 5, x + 15, y - 10,
                             fill=VIOLET, outline="#e1d7ff", width=2)
            if enemy.health > 1:
                c.create_oval(x - 3, y - 3, x + 3, y + 3, fill=WHITE, outline="")
        x, y = game.player_x, game.player_y
        c.create_polygon(x, y - 24, x - 20, y + 19, x, y + 10, x + 20, y + 19,
                         fill=CYAN, outline="#c8ffff", width=2)
        c.create_text(24, 22, anchor="nw", fill=WHITE, font=("TkDefaultFont", 15, "bold"),
                      text=f"STAR DEFENDER   •   PUNKTE {game.score:04d}   •   LEBEN {game.lives}   •   SEKTOR {game.level}")
        c.create_text(WIDTH / 2, HEIGHT - 15, fill="#aab7ca", font=("TkDefaultFont", 10),
                      text="BEWEGEN: WASD / PFEILE     FEUERN: LEERTASTE     PAUSE: P     ABSCHLUSS: ESC")
        if game.phase == "paused":
            self.panel("PAUSE", "P drücken zum Weiterspielen")
        if game.phase == "game_over":
            self.panel("RUNDE BEENDET", f"Punkte: {game.score}     R: Neustart     ENTER: Abspann")

    def draw_title(self) -> None:
        c = self.canvas
        cx = WIDTH / 2
        self.draw_brand_mark(cx, 165, 132)
        c.create_text(cx, 58, fill=MINT, font=("TkDefaultFont", 13, "bold"),
                      text="A STREAMIOV ORIGINAL")
        c.create_text(cx, 280, fill=WHITE, font=("TkDefaultFont", 32, "bold"),
                      text="STAR DEFENDER")
        if self.game.phase == "intro":
            c.create_text(cx, 345, fill="#c4d0e4", font=("TkDefaultFont", 15),
                          text="Halte die Sternenroute frei. Sammle Punkte und überstehe jeden Sektor.")
            c.create_text(cx, 402, fill=CYAN, font=("TkDefaultFont", 16, "bold"),
                          text="ENTER oder LEERTASTE  ·  SPIEL STARTEN")
            c.create_text(cx, 465, fill="#9aa9c2", font=("TkDefaultFont", 12),
                          text="WASD / Pfeile bewegen  ·  Leertaste feuern  ·  P pausieren  ·  ESC beenden")
        else:
            c.create_text(cx, 355, fill=MINT, font=("TkDefaultFont", 20, "bold"), text="DANKE FÜRS SPIELEN")
            c.create_text(cx, 405, fill=WHITE, font=("TkDefaultFont", 14), text="Spielidee, Code und Herkunft: siehe README und Manifest.")
            c.create_text(cx, 460, fill=CYAN, font=("TkDefaultFont", 14, "bold"), text="ENTER  ·  ZURÜCK ZUM TITEL")
            c.create_text(cx, 520, fill="#7e8ba2", font=("TkDefaultFont", 10), text="STREAMIOV ORIGINAL  ·  STAR DEFENDER")

    def draw_brand_mark(self, cx: float, cy: float, size: float) -> None:
        """Draw the shared StreamioV signal/play mark with native Canvas shapes."""
        c = self.canvas
        radius = size * 0.43
        c.create_rectangle(cx - size * 0.53, cy - size * 0.53,
                           cx + size * 0.53, cy + size * 0.53,
                           fill="#0b1020", outline="#293651", width=2)
        bounds = (cx - radius, cy - radius, cx + radius, cy + radius)
        c.create_arc(*bounds, start=28, extent=150, style=tk.ARC, outline=VIOLET, width=7)
        c.create_arc(*bounds, start=208, extent=150, style=tk.ARC, outline=MINT, width=7)
        c.create_polygon(cx - size * 0.11, cy - size * 0.20,
                         cx + size * 0.22, cy,
                         cx - size * 0.11, cy + size * 0.20,
                         fill=CYAN, outline=WHITE, width=2)
        c.create_oval(cx + size * 0.22, cy - size * 0.45,
                      cx + size * 0.29, cy - size * 0.38, fill=VIOLET, outline="")
        c.create_oval(cx - size * 0.29, cy + size * 0.38,
                      cx - size * 0.22, cy + size * 0.45, fill=MINT, outline="")

    def panel(self, title: str, subtitle: str) -> None:
        c = self.canvas
        c.create_rectangle(145, 220, 655, 380, fill="#10182a", outline=CYAN, width=2)
        c.create_text(WIDTH / 2, 275, fill=CYAN, font=("TkDefaultFont", 28, "bold"), text=title)
        c.create_text(WIDTH / 2, 325, fill=WHITE, font=("TkDefaultFont", 14), text=subtitle)

    def scale_to_window(self) -> None:
        width, height = max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())
        scale = min(width / WIDTH, height / HEIGHT)
        x_offset, y_offset = (width - WIDTH * scale) / 2, (height - HEIGHT * scale) / 2
        self.canvas.configure(scrollregion=(0, 0, width, height))
        self.canvas.scale("all", 0, 0, scale, scale)
        if x_offset or y_offset:
            self.canvas.move("all", x_offset, y_offset)


if __name__ == "__main__":
    StarDefender().root.mainloop()
