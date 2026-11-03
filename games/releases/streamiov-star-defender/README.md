# StreamioV Star Defender

An original, offline arcade game. It runs on Python 3 with Tkinter and has no runtime network access or package downloads.

## Run

```sh
python3 game.py
```

On some Linux distributions Tkinter is an optional OS package (`python3-tk`). Installing it may require the system package manager; that is an operating-system dependency, not a paid StreamioV service. Windows Python distributions commonly include Tkinter; verify the target installation.

## Controls

- `WASD` or arrow keys: move
- `Space`: fire
- `P`: pause/resume
- `Esc`: end the round and show the credits screen
- `R`: restart after a game over
- `Enter`: start / return to title

The window can resize while the playfield preserves its aspect ratio. The complete fixed-step game state is isolated in `engine.py` and can be tested without a display.

With a graphical display available, run `python3 games/releases/streamiov-star-defender/tests/gui_smoke.py` from the repository root for a short Tkinter rendering/input smoke check.

## Rights and provenance

This is a new StreamioV prototype written in this repository. The source uses Python's standard library only; the interface is drawn with Tkinter canvas primitives and contains no third-party images, fonts, music, or copied game assets. The code is copyrightable work, but repository authorship alone does not establish transfer of rights from every contributor. See `manifest.json` for the current component record and verification limits. “A StreamioV Original” identifies this project; it is not a legal ownership guarantee.

This is an early playable prototype, not a release: visual rendering, accessibility, balance, gameplay, and installation have not yet been verified on target devices.
