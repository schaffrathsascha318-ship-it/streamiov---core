# StreamioV AI Game Studio

This package is the first executable foundation of the StreamioV AI Game Builder.
It validates a substantial clean-room game brief and creates a durable, audited
design workspace under `games/ai_created/<game-id>/`.

## Run

```sh
python3 -m ai.game_studio path/to/game-brief.json --repository-root .
```

A brief must define original concept ownership, a gameplay vision and loop,
at least two signature mechanics, at least three level/challenge beats, controls,
progression, art/audio direction, accessibility, test plan, target platforms,
and the provenance/licence of every declared third-party component.

## Honest status boundary

The builder returns `DESIGN_BRIEF_VALIDATED`. It does not generate a playable game
by itself, run an engine, verify hardware, or publish a release. The existing
StreamioV Game specialist performs implementation through the shared AI provider
and project workspace. Automated tests, real gameplay verification, rights review,
and independent release approval remain mandatory gates. Existing projects are
never overwritten by this scaffold command.
