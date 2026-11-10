"""Deterministic, review-gated asset bundling for original STREAMIOV gifts.

This pipeline validates and packages authored SVG assets. It does not generate
art, perform trademark/copyright clearance, render a 3D scene, play audio,
publish gifts, process payments or trigger events.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable


PACK_ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")
GIFT_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")
MAX_SVG_BYTES = 1_000_000
MAX_ASSETS = 100
ALLOWED_TAGS = {
    "svg", "g", "defs", "path", "circle", "ellipse", "rect", "line",
    "polyline", "polygon", "linearGradient", "radialGradient", "stop",
    "filter", "feGaussianBlur", "feColorMatrix", "feMerge",
    "feMergeNode", "clipPath", "mask", "animate", "animateTransform",
}
FORBIDDEN_TAGS = {"script", "foreignObject", "iframe", "audio", "video"}
EXTERNAL_REFERENCE = re.compile(
    r"(?:https?:|//|javascript:|data:|file:)", re.IGNORECASE
)


class GiftAssetError(ValueError):
    """Raised when a gift asset or bundle is unsafe or invalid."""


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def validate_svg(content: bytes) -> dict:
    if not content or len(content) > MAX_SVG_BYTES:
        raise GiftAssetError("SVG must be between 1 byte and 1 MB.")
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GiftAssetError("SVG must be valid UTF-8 XML.") from exc
    if re.search(r"<!DOCTYPE|<!ENTITY", text, re.IGNORECASE):
        raise GiftAssetError("SVG document types and entities are not allowed.")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise GiftAssetError("SVG must be valid UTF-8 XML.") from exc
    if _local_name(root.tag) != "svg":
        raise GiftAssetError("Asset root element must be svg.")

    element_count = 0
    for element in root.iter():
        element_count += 1
        tag = _local_name(element.tag)
        if tag in FORBIDDEN_TAGS or tag not in ALLOWED_TAGS:
            raise GiftAssetError(f"Unsupported or active SVG element: {tag}.")
        for raw_name, value in element.attrib.items():
            name = _local_name(raw_name).lower()
            if name.startswith("on"):
                raise GiftAssetError("SVG event-handler attributes are not allowed.")
            if name in {"href", "src"} and value and not value.startswith("#"):
                raise GiftAssetError("External SVG references are not allowed.")
            if EXTERNAL_REFERENCE.search(value):
                raise GiftAssetError("External URLs and data URIs are not allowed.")
            if "url(" in value.lower() and not re.fullmatch(
                r".*url\(\s*#[A-Za-z0-9_-]+\s*\).*", value, re.IGNORECASE
            ):
                raise GiftAssetError("Only local fragment references are allowed.")
        if element.text and len(element.text) > 1000:
            raise GiftAssetError("SVG text nodes exceed the safe size limit.")
    if element_count > 5000:
        raise GiftAssetError("SVG contains too many elements.")

    values = re.split(r"[ ,]+", root.attrib.get("viewBox", "").strip())
    if len(values) != 4:
        raise GiftAssetError("SVG must declare a four-number viewBox.")
    try:
        _x, _y, width, height = (float(value) for value in values)
    except ValueError as exc:
        raise GiftAssetError("SVG viewBox must contain numbers.") from exc
    if not all(math.isfinite(value) for value in (_x, _y, width, height)):
        raise GiftAssetError("SVG viewBox values must be finite.")
    if width <= 0 or height <= 0 or width > 8192 or height > 8192:
        raise GiftAssetError("SVG viewBox dimensions are outside supported limits.")
    return {
        "format": "image/svg+xml",
        "width": int(width),
        "height": int(height),
        "element_count": element_count,
        "bytes": len(content),
        "sha256": _sha256(content),
    }


def build_gift_pack(
    *,
    pack_id: str,
    assets: Iterable[dict],
    output_root: str | Path,
) -> dict:
    """Copy validated SVGs and write a deterministic, non-publishable manifest."""
    if not isinstance(pack_id, str) or not PACK_ID.fullmatch(pack_id):
        raise GiftAssetError("pack_id must be a lowercase kebab-case identifier.")
    entries = list(assets)
    if not entries or len(entries) > MAX_ASSETS:
        raise GiftAssetError(f"A pack must contain 1 to {MAX_ASSETS} gifts.")

    seen: set[str] = set()
    prepared = []
    for item in entries:
        if not isinstance(item, dict):
            raise GiftAssetError("Each gift asset entry must be an object.")
        gift_id = item.get("id")
        name = item.get("name")
        source_value = item.get("source")
        if not isinstance(source_value, (str, Path)) or not str(source_value).strip():
            raise GiftAssetError("Each gift requires a source file path.")
        source = Path(source_value).resolve()
        if not isinstance(gift_id, str) or not GIFT_ID.fullmatch(gift_id) or gift_id in seen:
            raise GiftAssetError("Gift IDs must be unique lowercase identifiers.")
        seen.add(gift_id)
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 80:
            raise GiftAssetError(f"Gift {gift_id} has an invalid display name.")
        if source.suffix.lower() != ".svg" or not source.is_file():
            raise GiftAssetError(f"Gift {gift_id} requires an existing SVG source.")
        content = source.read_bytes()
        metadata = validate_svg(content)
        points = item.get("streamiov_points", 1)
        if isinstance(points, bool) or not isinstance(points, int) or not 1 <= points <= 49_999:
            raise GiftAssetError(f"Gift {gift_id} has invalid STREAMIOV point value.")
        accessibility = item.get("accessibility_text", name.strip())
        if not isinstance(accessibility, str) or not accessibility.strip() or len(accessibility) > 240:
            raise GiftAssetError(f"Gift {gift_id} requires accessibility text.")
        prepared.append((item, gift_id, name.strip(), content, metadata, points, accessibility.strip()))

    gifts = []
    base = Path(output_root).resolve()
    base.mkdir(parents=True, exist_ok=True)
    output = base / pack_id
    if output.exists():
        raise GiftAssetError(f"Refusing to overwrite existing gift pack: {pack_id}.")

    # Stage the complete bundle beside its final directory and publish it with
    # one rename. Validation or write failures never leave a half-built pack.
    with tempfile.TemporaryDirectory(prefix=f".{pack_id}-", dir=base) as temp_dir:
        stage = Path(temp_dir) / pack_id
        stage.mkdir()
        for item, gift_id, name, content, metadata, points, accessibility in prepared:
            filename = gift_id + ".svg"
            (stage / filename).write_bytes(content)
            gifts.append({
                "id": gift_id,
                "name": name,
                "category": str(item.get("category", "REACTION")).upper(),
                "rarity": str(item.get("rarity", "COMMON")).upper(),
                "streamiov_points": points,
                "price_unit": "STREAMIOV_POINTS",
                "tiktok_coin_price": None,
                "asset": filename,
                "fallback_still": filename,
                "asset_metadata": metadata,
                "animation": {"status": "NOT_PROVIDED", "duration_ms": 0, "loop": False},
                "audio": {"status": "NOT_PROVIDED"},
                "accessibility_text": accessibility,
                "validation_status": "VALIDATED",
                "review_status": "REVIEW_REQUIRED",
                "release_status": "NOT_RELEASED",
            })

        gifts.sort(key=lambda gift: gift["id"])
        manifest = {
            "schema_version": 1,
            "pack_id": pack_id,
            "pack_status": "REVIEW_REQUIRED",
            "release_status": "NOT_RELEASED",
            "published": False,
            "real_money_enabled": False,
            "checkout_enabled": False,
            "payout_enabled": False,
            "points_note": "STREAMIOV points only; not TikTok coins and not a cash value.",
            "copyright_review": "NOT_PERFORMED",
            "human_approval": "REQUIRED",
            "gifts": gifts,
        }
        (stage / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(stage, output)
    return manifest
