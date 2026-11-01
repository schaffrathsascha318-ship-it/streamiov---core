"""Bounded, auditable official-source research helpers for the Game AI.

This module discovers and records evidence. It deliberately does not decide that a
work is public domain or that an activity is legally permitted.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
import re
from urllib.parse import urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler

from .sources import sources_for

MAX_RESPONSE_BYTES = 1_000_000
DEFAULT_TIMEOUT_SECONDS = 8
USER_AGENT = "Streamiov-RightsResearch/1.0 (+https://streamiov.pages.dev/)"
ALLOWED_HOSTS = frozenset({
    "www.gesetze-im-internet.de", "www.dpma.de", "eur-lex.europa.eu",
    "www.euipo.europa.eu", "www.epo.org", "www.copyright.gov",
    "publicrecords.copyright.gov", "www.uspto.gov",
    "www.legislation.gov.uk", "www.gov.uk",
})

class ResearchError(ValueError):
    pass

class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip = 0
    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "svg"}:
            self.skip += 1
    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "svg"} and self.skip:
            self.skip -= 1
    def handle_data(self, data):
        if not self.skip and data.strip():
            self.parts.append(data.strip())

def validate_official_url(url: str) -> str:
    parsed = urlparse(url if isinstance(url, str) else "")
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise ResearchError("Research fetch is restricted to curated official HTTPS domains.")
    if parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ResearchError("Credentials and non-standard ports are not allowed.")
    return url

def extract_text(payload: bytes, content_type: str = "text/html") -> str:
    if len(payload) > MAX_RESPONSE_BYTES:
        raise ResearchError("Source response exceeds the configured size limit.")
    decoded = payload.decode("utf-8", errors="replace")
    if "html" in (content_type or "").lower() or re.search(r"<[a-z][^>]*>", decoded[:500], re.I):
        parser = _TextExtractor()
        parser.feed(decoded)
        decoded = " ".join(parser.parts)
    return re.sub(r"\s+", " ", decoded).strip()

@dataclass(frozen=True)
class SourceSnapshot:
    url: str
    authority: str
    accessed_at: str
    content_type: str
    text: str
    sha256: str

class OfficialSourceFetcher:
    """Fetch only curated official sources; redirects are checked before following."""
    def __init__(self, timeout: int = DEFAULT_TIMEOUT_SECONDS, opener=None):
        self.timeout = timeout
        self.opener = opener or urlopen

    def fetch(self, source: dict) -> SourceSnapshot:
        import hashlib
        url = validate_official_url(source.get("url"))
        request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,text/plain"})
        try:
            response = self.opener(request, timeout=self.timeout)
            final_url = validate_official_url(response.geturl())
            content_type = response.headers.get("Content-Type", "text/html")
            payload = response.read(MAX_RESPONSE_BYTES + 1)
            response.close()
        except ResearchError:
            raise
        except Exception as exc:
            raise ResearchError("Official source could not be fetched.") from exc
        if len(payload) > MAX_RESPONSE_BYTES:
            raise ResearchError("Source response exceeds the configured size limit.")
        text = extract_text(payload, content_type)
        return SourceSnapshot(final_url, source.get("authority", "Unknown authority"),
                              date.today().isoformat(), content_type, text,
                              hashlib.sha256(payload).hexdigest())

class RightsResearcher:
    """Research coordinator. A caller supplies a fetcher; findings remain evidence only."""
    def __init__(self, register, fetcher=None):
        self.register = register
        self.fetcher = fetcher or OfficialSourceFetcher()

    def catalogue(self, territory: str) -> list[dict]:
        return sources_for(territory)

    def collect_component_sources(self, component_id: str, territory: str,
                                   right_types: tuple[str, ...] = ("copyright", "trademark")) -> list[dict]:
        """Fetch curated starting points and save snapshots as evidence, without legal conclusions."""
        collected = []
        for source in self.catalogue(territory):
            if source["right_type"] not in right_types:
                continue
            snapshot = self.fetcher.fetch(source)
            excerpt = snapshot.text[:1200] or "Official source fetched; no readable text extracted."
            evidence_id = self.register.add_evidence(
                component_id, snapshot.url, snapshot.authority, snapshot.accessed_at,
                excerpt, f"right_type={source['right_type']}; sha256={snapshot.sha256}; content_type={snapshot.content_type}"
            )
            collected.append({
                "evidence_id": evidence_id, "url": snapshot.url,
                "authority": snapshot.authority, "right_type": source["right_type"],
                "accessed_at": snapshot.accessed_at, "sha256": snapshot.sha256,
                "text_excerpt": excerpt, "legal_conclusion": None,
                "status": "EVIDENCE_COLLECTED_REVIEW_REQUIRED"
            })
        return collected
