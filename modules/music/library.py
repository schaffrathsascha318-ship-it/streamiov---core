"""Local music catalogue with fail-closed rights and content gates.

This module never downloads audio or contacts a music provider. Rights evidence
may be gathered elsewhere, but a human-reviewed, zero-cost grant for the exact
territory and use is required before a local track can be selected.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Iterable
from urllib.parse import urlparse


TRACK_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")
TERRITORY = re.compile(r"^[A-Z]{2}$")
USES = frozenset({"local_playback", "live_stream", "saved_vod", "download"})
AUDIO_EXTENSIONS = frozenset({".aac", ".flac", ".m4a", ".mp3", ".ogg", ".opus", ".wav"})
CONTENT_LABELS = frozenset({
    "sexual_explicit",
    "violence_graphic",
    "hate_or_threats",
    "political",
    "drug_reference",
})
RIGHTS_COMPONENTS = frozenset({"composition", "lyrics", "performance", "sound_recording"})
GRANT_BASES = frozenset({"direct_permission", "license", "public_domain_determination"})
EVIDENCE_KINDS = frozenset({
    "license_text", "rightsholder_permission", "official_register", "legal_source", "other"
})
POLITICAL_DIRECTIONS = frozenset({"left", "right", "mixed", "unknown", "not_political"})
RIGHTS_STATES = frozenset({"unknown", "candidate", "restricted", "approved"})
CONTENT_REVIEW_STATES = frozenset({"pending", "approved", "rejected"})


class MusicLibraryError(ValueError):
    """Raised when a catalogue entry is malformed or unsafe."""


@dataclass(frozen=True)
class ContentPolicy:
    """Creator-selected filters; left/right political direction is never a gate."""

    # Explicit sexual content is blocked until an age policy exists.
    blocked_labels: frozenset[str] = frozenset({"hate_or_threats", "sexual_explicit"})
    review_labels: frozenset[str] = frozenset({
        "violence_graphic", "political", "drug_reference"
    })

    def __post_init__(self) -> None:
        unknown = (self.blocked_labels | self.review_labels) - CONTENT_LABELS
        if unknown:
            raise MusicLibraryError("Unknown content policy labels: " + ", ".join(sorted(unknown)))


@dataclass(frozen=True)
class GateResult:
    track_id: str
    allowed: bool
    state: str
    reasons: tuple[str, ...]
    local_path: Path | None = None


@dataclass(frozen=True)
class Evidence:
    url: str
    accessed_at: str
    source_title: str
    publisher: str
    section: str
    kind: str
    summary: str


@dataclass(frozen=True)
class RightsGrant:
    territory: str
    usage: str
    components: frozenset[str]
    state: str
    cost_eur: float | None
    evidence: tuple[Evidence, ...] = ()
    rightsholder: str | None = None
    grant_basis: str | None = None
    license_id: str | None = None
    attribution: str | None = None
    reviewed_by: str | None = None
    reviewed_at: str | None = None


@dataclass(frozen=True)
class MusicTrack:
    track_id: str
    title: str
    artist: str
    local_file: str
    rights_components: frozenset[str]
    rights: tuple[RightsGrant, ...]
    content_labels: frozenset[str] = field(default_factory=frozenset)
    content_review: str = "pending"
    political_direction: str = "not_political"


def _iso_date(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise MusicLibraryError(field_name + " must be an ISO date.")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise MusicLibraryError(field_name + " must be an ISO date.") from exc
    return value


def _text(value: object, field_name: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise MusicLibraryError(field_name + " must be non-empty text within its size limit.")
    return value.strip()


def _evidence(raw: object) -> Evidence:
    if not isinstance(raw, dict):
        raise MusicLibraryError("Every rights evidence item must be an object.")
    url = _text(raw.get("url"), "evidence.url", 2048)
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise MusicLibraryError("Rights evidence URLs must use HTTPS and contain no credentials.")
    kind = raw.get("kind")
    if kind not in EVIDENCE_KINDS:
        raise MusicLibraryError("Evidence kind is unsupported.")
    return Evidence(
        url=url,
        accessed_at=_iso_date(raw.get("accessed_at"), "evidence.accessed_at"),
        source_title=_text(raw.get("source_title"), "evidence.source_title", 300),
        publisher=_text(raw.get("publisher"), "evidence.publisher", 200),
        section=_text(raw.get("section"), "evidence.section", 300),
        kind=kind,
        summary=_text(raw.get("summary"), "evidence.summary", 2000),
    )


def _rights(raw: object) -> RightsGrant:
    if not isinstance(raw, dict):
        raise MusicLibraryError("Every rights grant must be an object.")
    territory = raw.get("territory")
    usage = raw.get("usage")
    state = raw.get("state")
    if not isinstance(territory, str) or not TERRITORY.fullmatch(territory):
        raise MusicLibraryError("Rights territory must be an explicit ISO 3166-1 alpha-2 code.")
    if usage not in USES:
        raise MusicLibraryError("Rights usage is unsupported.")
    if state not in RIGHTS_STATES:
        raise MusicLibraryError("Rights state is unsupported.")
    raw_components = raw.get("components")
    if (not isinstance(raw_components, list) or not raw_components
            or any(not isinstance(component, str) for component in raw_components)):
        raise MusicLibraryError("Every rights grant must name one or more rights components.")
    components = frozenset(raw_components)
    if components - RIGHTS_COMPONENTS or len(components) != len(raw_components):
        raise MusicLibraryError("Rights grant contains unsupported or duplicate components.")

    cost = raw.get("cost_eur")
    if cost is not None and (isinstance(cost, bool) or not isinstance(cost, (int, float)) or cost < 0):
        raise MusicLibraryError("cost_eur must be zero, a positive amount, or unknown.")
    raw_evidence = raw.get("evidence", [])
    if not isinstance(raw_evidence, list) or len(raw_evidence) > 30:
        raise MusicLibraryError("evidence must contain at most 30 entries.")
    evidence = tuple(_evidence(item) for item in raw_evidence)
    reviewer = raw.get("reviewed_by")
    reviewed_at = raw.get("reviewed_at")
    rightsholder = raw.get("rightsholder")
    grant_basis = raw.get("grant_basis")
    license_id = raw.get("license_id")
    attribution = raw.get("attribution")
    if reviewer is not None:
        reviewer = _text(reviewer, "reviewed_by", 120)
    if reviewed_at is not None:
        reviewed_at = _iso_date(reviewed_at, "reviewed_at")
    if rightsholder is not None:
        rightsholder = _text(rightsholder, "rightsholder", 300)
    if grant_basis is not None:
        grant_basis = _text(grant_basis, "grant_basis", 200)
        if grant_basis not in GRANT_BASES:
            raise MusicLibraryError("grant_basis is unsupported.")
    if license_id is not None:
        license_id = _text(license_id, "license_id", 200)
    if attribution is not None:
        attribution = _text(attribution, "attribution", 1000)
    evidence_kinds = frozenset(item.kind for item in evidence)
    evidence_matches_basis = (
        grant_basis == "direct_permission" and "rightsholder_permission" in evidence_kinds
        or grant_basis == "license" and "license_text" in evidence_kinds
        or grant_basis == "public_domain_determination"
        and bool(evidence_kinds & {"legal_source", "official_register"})
    )
    if state == "approved" and (
        cost != 0 or not evidence or not reviewer or not reviewed_at
        or not grant_basis or not attribution
        or not evidence_matches_basis
        or (grant_basis != "public_domain_determination" and not rightsholder)
        or (grant_basis == "license" and not license_id)
    ):
        raise MusicLibraryError(
            "Approved rights require zero cost, component-specific evidence, a human reviewer, a grant basis, attribution terms, and a review date; licenses also require a license ID and public-domain determinations require official evidence."
        )
    return RightsGrant(
        territory, usage, components, state, float(cost) if cost is not None else None,
        evidence, rightsholder, grant_basis, license_id, attribution, reviewer, reviewed_at,
    )


def _track(raw: object) -> MusicTrack:
    if not isinstance(raw, dict):
        raise MusicLibraryError("Every track must be an object.")
    track_id = raw.get("id")
    if not isinstance(track_id, str) or not TRACK_ID.fullmatch(track_id):
        raise MusicLibraryError("Track IDs must be lowercase identifiers.")
    local_file = raw.get("local_file")
    if not isinstance(local_file, str) or "\\" in local_file:
        raise MusicLibraryError("local_file must be a relative POSIX path.")
    relative = PurePosixPath(local_file)
    if relative.is_absolute() or not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise MusicLibraryError("local_file must remain inside the configured local music directory.")
    if Path(relative.name).suffix.lower() not in AUDIO_EXTENSIONS:
        raise MusicLibraryError("local_file must use a supported audio extension.")

    raw_components = raw.get("rights_components")
    if (not isinstance(raw_components, list) or not raw_components
            or any(not isinstance(component, str) for component in raw_components)):
        raise MusicLibraryError("rights_components must explicitly list every protected track component.")
    rights_components = frozenset(raw_components)
    if rights_components - RIGHTS_COMPONENTS or len(rights_components) != len(raw_components):
        raise MusicLibraryError("rights_components contains unsupported or duplicate components.")

    labels = raw.get("content_labels", [])
    if not isinstance(labels, list) or any(not isinstance(label, str) for label in labels):
        raise MusicLibraryError("content_labels must be an array of strings.")
    label_set = frozenset(labels)
    if label_set - CONTENT_LABELS:
        raise MusicLibraryError("Track contains unsupported content labels.")
    content_review = raw.get("content_review", "pending")
    if content_review not in CONTENT_REVIEW_STATES:
        raise MusicLibraryError("content_review state is unsupported.")
    political_direction = raw.get("political_direction", "not_political")
    if political_direction not in POLITICAL_DIRECTIONS:
        raise MusicLibraryError("political_direction is unsupported.")
    if political_direction != "not_political" and "political" not in label_set:
        raise MusicLibraryError("Political direction may only be recorded for politically labelled tracks.")

    raw_rights = raw.get("rights", [])
    if not isinstance(raw_rights, list) or len(raw_rights) > 100:
        raise MusicLibraryError("rights must contain at most 100 grants.")
    grants = tuple(_rights(item) for item in raw_rights)
    pairs = [
        (grant.territory, grant.usage, component)
        for grant in grants
        for component in grant.components
    ]
    if len(set(pairs)) != len(pairs):
        raise MusicLibraryError("A track cannot have duplicate rights grants for one territory, use, and component.")
    return MusicTrack(
        track_id=track_id,
        title=_text(raw.get("title"), "title", 200),
        artist=_text(raw.get("artist"), "artist", 200),
        local_file=local_file,
        rights_components=rights_components,
        rights=grants,
        content_labels=label_set,
        content_review=content_review,
        political_direction=political_direction,
    )


class MusicLibrary:
    """Read-only local library. It does not fetch tracks or authorize rights."""

    def __init__(self, tracks: Iterable[MusicTrack], music_root: str | Path) -> None:
        # Preserve the caller's absolute path spelling for returned paths;
        # containment checks below use the canonical root separately.
        self.music_root = Path(music_root).absolute()
        self.tracks = {track.track_id: track for track in tracks}

    @classmethod
    def load(cls, catalog_path: str | Path, *, music_root: str | Path) -> "MusicLibrary":
        try:
            payload = json.loads(Path(catalog_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MusicLibraryError("Cannot read local music catalogue.") from exc
        if not isinstance(payload, dict) or payload.get("schema_version") != 2:
            raise MusicLibraryError("Unsupported music catalogue schema.")
        raw_tracks = payload.get("tracks")
        if not isinstance(raw_tracks, list) or len(raw_tracks) > 5000:
            raise MusicLibraryError("tracks must be an array of at most 5000 entries.")
        tracks = tuple(_track(item) for item in raw_tracks)
        ids = [track.track_id for track in tracks]
        if len(set(ids)) != len(ids):
            raise MusicLibraryError("Track IDs must be unique.")
        return cls(tracks, music_root)

    def _local_path(self, track: MusicTrack) -> Path | None:
        candidate = self.music_root.joinpath(*PurePosixPath(track.local_file).parts)
        current = self.music_root
        for part in PurePosixPath(track.local_file).parts:
            current = current / part
            if current.is_symlink():
                return None
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(self.music_root.resolve())
        except (OSError, ValueError):
            return None
        return candidate if resolved.is_file() else None

    def assess(
        self,
        track_id: str,
        *,
        territory: str,
        usage: str,
        policy: ContentPolicy | None = None,
    ) -> GateResult:
        track = self.tracks.get(track_id)
        if track is None:
            return GateResult(track_id, False, "unknown_track", ("track_not_in_local_catalogue",))
        if not isinstance(territory, str) or not TERRITORY.fullmatch(territory):
            return GateResult(track_id, False, "invalid_request", ("territory_required",))
        if usage not in USES:
            return GateResult(track_id, False, "invalid_request", ("usage_not_supported",))

        local_path = self._local_path(track)
        if local_path is None:
            return GateResult(track_id, False, "missing_local_audio", ("audio_file_not_found_or_unsafe",))

        relevant = [
            r for r in track.rights
            if r.territory == territory and r.usage == usage
            and r.components & track.rights_components
        ]
        covered = frozenset(component for grant in relevant for component in grant.components)
        if not relevant or track.rights_components - covered:
            return GateResult(track_id, False, "rights_unknown", ("no_exact_territory_and_usage_grant",))
        if any(grant.state == "restricted" for grant in relevant):
            return GateResult(track_id, False, "rights_restricted", ("rights_holder_restricted_this_use",))
        if any(
            grant.state != "approved" or grant.cost_eur != 0 or not grant.evidence
            or not grant.reviewed_by or not grant.grant_basis or not grant.attribution
            or (grant.grant_basis != "public_domain_determination" and not grant.rightsholder)
            or (grant.grant_basis == "license" and not grant.license_id)
            for grant in relevant
        ):
            return GateResult(track_id, False, "rights_unverified", ("zero_cost_human_reviewed_evidence_required",))

        selected_policy = policy or ContentPolicy()
        blocked = track.content_labels & selected_policy.blocked_labels
        if blocked:
            return GateResult(track_id, False, "content_blocked", ("blocked_labels:" + ",".join(sorted(blocked)),))
        needs_review = track.content_labels & selected_policy.review_labels
        if needs_review and track.content_review != "approved":
            return GateResult(track_id, False, "content_review_required", ("review_labels:" + ",".join(sorted(needs_review)),))
        if track.content_review == "rejected":
            return GateResult(track_id, False, "content_rejected", ("content_review_rejected",))
        return GateResult(track_id, True, "playable", (), local_path)

    def list_playable(
        self,
        *,
        territory: str,
        usage: str,
        policy: ContentPolicy | None = None,
    ) -> tuple[GateResult, ...]:
        return tuple(self.assess(track_id, territory=territory, usage=usage, policy=policy)
                     for track_id in sorted(self.tracks))
