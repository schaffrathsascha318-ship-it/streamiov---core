# STREAMIOV gift asset pipeline

The new `ai.runtime.gift_asset_pipeline` module is the deterministic packaging and validation stage for original, authored SVG gift assets.

## What it does

- Validates UTF-8 SVG/XML, root/viewBox, element count and file-size limits.
- Rejects scripts, foreign objects, event handlers, external references, data URIs and unsafe document entities.
- Copies assets into a pack directory and calculates SHA-256 checksums.
- Writes a stable manifest with explicit STREAMIOV point semantics, accessibility text, fallback still, asset metadata and review state.
- Keeps every generated pack at `REVIEW_REQUIRED` / `NOT_RELEASED`; checkout and payout stay disabled.

## What it does not claim

This stage does not generate artwork with a model, prove originality, perform trademark/copyright clearance, render 3D effects, decode/normalize audio, integrate the gallery/event bus, or approve/publish gifts. Those remain separate acceptance gates. TikTok coin prices are never assigned to STREAMIOV-native points. TikTok-native gifts remain a separate integration.

## Usage

Call `build_gift_pack(pack_id=..., assets=[...], output_root=...)` with a list of authored SVG files and metadata. The function refuses to overwrite existing packs. Run:

```bash
python -m unittest tests.test_gift_asset_pipeline -v
```

A validated asset is not automatically an approved or released gift.
