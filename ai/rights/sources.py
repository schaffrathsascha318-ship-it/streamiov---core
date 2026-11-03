"""Curated official starting points for territory-specific rights research.

URLs are discovery entry points, not proof that a particular game is cleared.
Always verify current text, amendments, territorial scope, and the exact activity.
"""
OFFICIAL_SOURCES = {
    "DE": {
        "copyright": [
            {"authority": "Gesetze im Internet", "url": "https://www.gesetze-im-internet.de/urhg/__64.html", "topic": "UrhG §64 general copyright term"},
            {"authority": "Gesetze im Internet", "url": "https://www.gesetze-im-internet.de/urhg/__65.html", "topic": "UrhG §65 joint authors and special cases"},
            {"authority": "Gesetze im Internet", "url": "https://www.gesetze-im-internet.de/urhg/", "topic": "UrhG current consolidated text"},
        ],
        "trademark": [
            {"authority": "Gesetze im Internet", "url": "https://www.gesetze-im-internet.de/markeng/__47.html", "topic": "MarkenG §47 term and renewal"},
            {"authority": "DPMA", "url": "https://www.dpma.de/english/trade_marks/", "topic": "German trademark information and register access"},
        ],
        "patent_design": [
            {"authority": "DPMA", "url": "https://www.dpma.de/english/patents/", "topic": "German patent information"},
            {"authority": "DPMA", "url": "https://www.dpma.de/english/designs/", "topic": "German registered designs"},
        ],
    },
    "EU": {
        "copyright": [
            {"authority": "EUR-Lex", "url": "https://eur-lex.europa.eu/eli/dir/2006/116/oj", "topic": "Directive 2006/116/EC copyright term"},
        ],
        "trademark": [
            {"authority": "EUIPO", "url": "https://www.euipo.europa.eu/en/trade-marks", "topic": "EU trade marks and eSearch"},
        ],
        "patent_design": [
            {"authority": "European Patent Office", "url": "https://www.epo.org/en", "topic": "European patent information"},
        ],
    },
    "US": {
        "copyright": [
            {"authority": "US Copyright Office", "url": "https://www.copyright.gov/title17/", "topic": "US Copyright Act"},
            {"authority": "US Copyright Office", "url": "https://publicrecords.copyright.gov/", "topic": "Copyright public records"},
        ],
        "trademark": [
            {"authority": "USPTO", "url": "https://www.uspto.gov/trademarks/search", "topic": "US trademark search"},
        ],
        "patent_design": [
            {"authority": "USPTO", "url": "https://www.uspto.gov/patents/search", "topic": "US patent search"},
        ],
    },
    "UK": {
        "copyright": [
            {"authority": "legislation.gov.uk", "url": "https://www.legislation.gov.uk/ukpga/1988/48/contents", "topic": "Copyright, Designs and Patents Act 1988"},
        ],
        "trademark": [
            {"authority": "UK IPO", "url": "https://www.gov.uk/search-for-trademark", "topic": "UK trademark search"},
        ],
        "patent_design": [
            {"authority": "UK IPO", "url": "https://www.gov.uk/search-for-patent", "topic": "UK patent search"},
        ],
    },
}

def sources_for(territory: str) -> list[dict]:
    """Return a copy of the official starting-point catalogue for a territory."""
    key = (territory or "").upper()
    if key not in OFFICIAL_SOURCES:
        raise ValueError("No curated official-source catalogue for this territory.")
    return [dict(item, right_type=right_type, territory=key)
            for right_type, entries in OFFICIAL_SOURCES[key].items()
            for item in entries]
