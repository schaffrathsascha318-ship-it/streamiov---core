"""Strict read-only catalogue validation for STREAMIOV-native gifts.

No checkout, payment, payout, TikTok event or gift-send action is performed here.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


GIFT_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")
ALLOWED_STATUSES = {"draft", "local_preview_only", "validated", "approved", "released"}


class GiftCatalogError(ValueError):
    pass


@dataclass(frozen=True)
class NativeGift:
    gift_id: str
    name: str
    streamiov_points: int
    asset: str
    status: str
    asset_available: bool
    tiktok_gift_id: str | None

    @property
    def previewable(self) -> bool:
        return self.asset_available and self.status in {"local_preview_only", "validated", "approved", "released"}

    @property
    def released(self) -> bool:
        return self.status == "released" and self.asset_available


class GiftCatalog:
    def __init__(self, gifts: list[NativeGift], *, points_note: str) -> None:
        self.gifts = tuple(gifts)
        self.points_note = points_note

    @classmethod
    def load(cls, catalog_path: str | Path, *, asset_root: str | Path | None = None) -> "GiftCatalog":
        path = Path(catalog_path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise GiftCatalogError(f"Cannot read gift catalogue: {exc}") from exc
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            raise GiftCatalogError("Unsupported gift catalogue schema.")
        raw_gifts = payload.get("gifts")
        if not isinstance(raw_gifts, list) or len(raw_gifts) > 1000:
            raise GiftCatalogError("Catalogue must contain an array of at most 1000 gifts.")
        root = Path(asset_root).resolve() if asset_root is not None else None
        gifts: list[NativeGift] = []
        seen: set[str] = set()
        for item in raw_gifts:
            if not isinstance(item, dict):
                raise GiftCatalogError("Every gift entry must be an object.")
            gift_id = item.get("id")
            name = item.get("name")
            points = item.get("streamiov_points")
            asset = item.get("svg")
            status = item.get("status", "draft")
            tiktok_id = item.get("tiktok_gift_id")
            if not isinstance(gift_id, str) or not GIFT_ID.fullmatch(gift_id) or gift_id in seen:
                raise GiftCatalogError("Gift IDs must be unique lowercase identifiers.")
            seen.add(gift_id)
            if not isinstance(name, str) or not name.strip() or len(name) > 80:
                raise GiftCatalogError(f"Gift {gift_id} has an invalid name.")
            if isinstance(points, bool) or not isinstance(points, int) or not 1 <= points <= 49_999:
                raise GiftCatalogError(f"Gift {gift_id} has invalid STREAMIOV point value.")
            if not isinstance(asset, str) or not asset.startswith("/assets/gifts/") or ".." in Path(asset).parts:
                raise GiftCatalogError(f"Gift {gift_id} has an unsafe asset path.")
            if not isinstance(status, str) or status not in ALLOWED_STATUSES:
                raise GiftCatalogError(f"Gift {gift_id} has an unknown release status.")
            if tiktok_id is not None:
                raise GiftCatalogError(
                    f"Gift {gift_id} mixes a STREAMIOV-native gift with a TikTok-native gift ID."
                )
            asset_available = False
            if root is not None:
                relative = asset.removeprefix("/assets/gifts/")
                candidate = root / relative
                if candidate.is_symlink():
                    raise GiftCatalogError(f"Gift {gift_id} asset must not be a symlink.")
                resolved = candidate.resolve()
                if not resolved.is_relative_to(root):
                    raise GiftCatalogError(f"Gift {gift_id} asset escapes the configured asset root.")
                asset_available = resolved.is_file()
            gifts.append(NativeGift(
                gift_id=gift_id,
                name=name.strip(),
                streamiov_points=points,
                asset=asset,
                status=status,
                asset_available=asset_available,
                tiktok_gift_id=None,
            ))
        note = payload.get("points_note", "")
        if not isinstance(note, str):
            raise GiftCatalogError("points_note must be text.")
        return cls(gifts, points_note=note)

    def previewable_gifts(self) -> tuple[NativeGift, ...]:
        return tuple(gift for gift in self.gifts if gift.previewable)

    def released_gifts(self) -> tuple[NativeGift, ...]:
        return tuple(gift for gift in self.gifts if gift.released)

    def snapshot(self) -> dict:
        return {
            "schema_version": 1,
            "gift_count": len(self.gifts),
            "previewable_count": len(self.previewable_gifts()),
            "released_count": len(self.released_gifts()),
            "points_note": self.points_note,
            "gifts": [
                {
                    "id": gift.gift_id,
                    "name": gift.name,
                    "streamiov_points": gift.streamiov_points,
                    "asset": gift.asset,
                    "status": gift.status,
                    "asset_available": gift.asset_available,
                    "previewable": gift.previewable,
                    "released": gift.released,
                    "source": "STREAMIOV_NATIVE",
                }
                for gift in self.gifts
            ],
            "real_money_enabled": False,
            "checkout_enabled": False,
            "payout_enabled": False,
        }
