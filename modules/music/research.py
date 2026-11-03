"""Human-reviewable rights dossiers from locally recorded music research notes.

This module does not fetch pages, download recordings, or decide legal status.
"""
from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import sys

from .library import MusicLibrary, MusicLibraryError, USES


def rights_dossier(library: MusicLibrary, track_id: str, *, territory: str,
                   usages: tuple[str, ...] = tuple(sorted(USES))) -> dict:
    track = library.tracks.get(track_id)
    if track is None:
        raise MusicLibraryError("Track is not in the local music catalogue.")
    if not isinstance(territory, str) or len(territory) != 2 or not territory.isalpha() or territory != territory.upper():
        raise MusicLibraryError("An uppercase territory code is required.")
    if not usages or any(usage not in USES for usage in usages):
        raise MusicLibraryError("At least one supported use is required.")

    component_results = []
    for component in sorted(track.rights_components):
        by_usage = []
        for usage in usages:
            grant = next((item for item in track.rights
                          if item.territory == territory and item.usage == usage
                          and component in item.components), None)
            if grant is None:
                by_usage.append({"usage": usage, "state": "unknown", "reason": "no_exact_component_territory_and_use_grant"})
                continue
            by_usage.append({
                "usage": usage,
                "state": grant.state,
                "cost_eur": grant.cost_eur,
                "rightsholder": grant.rightsholder,
                "grant_basis": grant.grant_basis,
                "license_id": grant.license_id,
                "attribution": grant.attribution,
                "reviewed_by": grant.reviewed_by,
                "reviewed_at": grant.reviewed_at,
                "evidence": [
                    {
                        "url": item.url,
                        "source_title": item.source_title,
                        "publisher": item.publisher,
                        "section": item.section,
                        "kind": item.kind,
                        "accessed_at": item.accessed_at,
                        "summary": item.summary,
                    }
                    for item in grant.evidence
                ],
            })
        component_results.append({"component": component, "uses": by_usage})

    all_approved = all(
        use.get("state") == "approved" and use.get("cost_eur") == 0
        for component in component_results
        for use in component["uses"]
    )
    any_restricted = any(
        use.get("state") == "restricted"
        for component in component_results
        for use in component["uses"]
    )
    rights_state = "evidence_approved_by_local_reviewer" if all_approved else "restricted" if any_restricted else "incomplete_or_unknown"
    return {
        "schema_version": 1,
        "generated_at": date.today().isoformat(),
        "track": {"id": track.track_id, "title": track.title, "artist": track.artist, "local_file": track.local_file},
        "territory": territory,
        "requested_uses": list(usages),
        "rights_state": rights_state,
        "components": component_results,
        "content_review": {
            "labels": sorted(track.content_labels),
            "state": track.content_review,
            "political_direction": track.political_direction,
        },
        "notice": "Research summary only. Evidence and local approvals are not a legal opinion or a guarantee of permission.",
    }


def render_markdown(dossier: dict) -> str:
    track = dossier["track"]
    lines = [
        f"# Rights research: {track['title']}",
        "",
        f"- Artist: {track['artist']}",
        f"- Track ID: `{track['id']}`",
        f"- Territory: `{dossier['territory']}`",
        f"- State: **{dossier['rights_state']}**",
        f"- Generated: {dossier['generated_at']}",
        "",
        "## Component and use checks",
        "",
    ]
    for component in dossier["components"]:
        lines.extend([f"### {component['component']}", ""])
        for use in component["uses"]:
            lines.append(f"- **{use['usage']}**: `{use['state']}`")
            if use.get("reason"):
                lines.append(f"  - Reason: {use['reason']}")
            if use.get("rightsholder"):
                lines.append(f"  - Rightsholder: {use['rightsholder']}")
            if use.get("grant_basis"):
                lines.append(f"  - Basis: {use['grant_basis']} {use.get('license_id') or ''}".rstrip())
            if use.get("attribution"):
                lines.append(f"  - Attribution: {use['attribution']}")
            for evidence in use.get("evidence", []):
                lines.append(
                    f"  - Evidence: [{evidence['source_title']}]({evidence['url']}) — "
                    f"{evidence['publisher']}, {evidence['section']} (accessed {evidence['accessed_at']}); "
                    f"{evidence['summary']}"
                )
        lines.append("")
    content = dossier["content_review"]
    lines.extend([
        "## Separate content review",
        "",
        f"- Labels: {', '.join(content['labels']) or 'none recorded'}",
        f"- Review: `{content['state']}`",
        f"- Political direction annotation: `{content['political_direction']}` (not a rights or political-viewpoint gate)",
        "",
        f"> {dossier['notice']}",
        "",
    ])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalog", type=Path)
    parser.add_argument("--music-root", type=Path, required=True)
    parser.add_argument("--track", required=True)
    parser.add_argument("--territory", required=True)
    parser.add_argument("--usage", action="append", choices=sorted(USES), required=True)
    parser.add_argument("--format", choices=("json", "markdown"), default="markdown")
    args = parser.parse_args(argv)
    try:
        library = MusicLibrary.load(args.catalog, music_root=args.music_root)
        result = rights_dossier(library, args.track, territory=args.territory, usages=tuple(args.usage))
    except MusicLibraryError as exc:
        parser.error(str(exc))
    output = json.dumps(result, ensure_ascii=False, indent=2) if args.format == "json" else render_markdown(result)
    sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
