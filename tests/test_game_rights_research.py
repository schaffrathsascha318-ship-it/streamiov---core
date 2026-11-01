import unittest
from unittest.mock import Mock
from ai.rights.research import (
    ResearchError, OfficialSourceFetcher, RightsResearcher,
    _OfficialRedirectHandler, extract_text, validate_official_url,
)
from ai.rights.sources import sources_for


class ResearchTests(unittest.TestCase):
    def test_catalogue_only_official_sources(self):
        sources = sources_for("DE")
        self.assertTrue(sources)
        self.assertTrue(all(s["url"].startswith("https://") for s in sources))
        self.assertTrue(any("urhg/__64" in s["url"] for s in sources))
        with self.assertRaises(ValueError):
            sources_for("XX")

    def test_fetch_rejects_unapproved_hosts_and_credentials(self):
        for url in ("https://example.com/law", "http://www.dpma.de/", "https://user:pass@www.dpma.de/"):
            with self.subTest(url=url), self.assertRaises(ResearchError):
                validate_official_url(url)

    def test_html_text_extraction_ignores_scripts(self):
        text = extract_text(b"<html><script>secret()</script><p>Copyright law</p></html>")
        self.assertIn("Copyright law", text)
        self.assertNotIn("secret", text)

    def test_fetch_records_hash_and_source_metadata(self):
        response = Mock()
        response.geturl.return_value = "https://www.dpma.de/english/trade_marks/"
        response.headers = {"Content-Type": "text/html; charset=utf-8"}
        response.read.return_value = b"<html><p>Trade mark information</p></html>"
        response.close.return_value = None
        fetcher = OfficialSourceFetcher(opener=lambda request, timeout: response)
        snapshot = fetcher.fetch({"url": "https://www.dpma.de/english/trade_marks/", "authority": "DPMA"})
        self.assertEqual(snapshot.authority, "DPMA")
        self.assertIn("Trade mark information", snapshot.text)
        self.assertEqual(len(snapshot.sha256), 64)

    def test_default_fetcher_has_a_working_opener(self):
        fetcher = OfficialSourceFetcher()
        self.assertTrue(callable(fetcher.opener))

    def test_unapproved_redirect_is_rejected_before_following(self):
        handler = _OfficialRedirectHandler()
        with self.assertRaises(ResearchError):
            handler.redirect_request(None, None, 302, "Found", {}, "https://attacker.example/redirect")

    def test_fetch_rejects_unapproved_redirect_target(self):
        response = Mock()
        response.geturl.return_value = "https://attacker.example/redirect"
        fetcher = OfficialSourceFetcher(opener=lambda request, timeout: response)
        with self.assertRaises(ResearchError):
            fetcher.fetch({"url": "https://www.dpma.de/english/trade_marks/", "authority": "DPMA"})


if __name__ == "__main__":
    unittest.main()
