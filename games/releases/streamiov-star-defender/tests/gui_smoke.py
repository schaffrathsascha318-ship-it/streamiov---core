"""Display-backed smoke check: python3 games/releases/.../tests/gui_smoke.py"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from game import StarDefender


app = StarDefender()
app.root.update()
assert app.canvas.find_all(), "The window rendered no canvas items."
app.canvas.focus_force()
app.canvas.event_generate("<KeyPress-Return>")
app.root.update()
app.game.step(app.keys)
assert app.game.phase == "playing", "The title-screen start key did not start the game."
app.draw()
app.root.update()
assert app.canvas.find_all(), "The game screen rendered no canvas items."
app.root.destroy()
print("Tkinter display smoke passed: title rendered, Enter input handled, playfield rendered.")
