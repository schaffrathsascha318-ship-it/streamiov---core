import re
import sqlite3
import tempfile
from contextlib import closing, contextmanager
import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from pathlib import Path
from unittest.mock import patch

from host.server import (
    DEFAULT_SITE_ROOT, Handler, StreamioVHTTPServer,
    resolve_public_file, run_local_ai_task, validate_tls_settings,
)
from host.data_store import DEFAULT_RAW_DATA_ROOT


class HostStaticPathTests(unittest.TestCase):
    def test_default_host_site_root_contains_the_project_homepage(self):
        homepage = resolve_public_file(DEFAULT_SITE_ROOT, "/")
        self.assertEqual(homepage, DEFAULT_SITE_ROOT / "index.html")
        self.assertTrue(homepage.is_file())

    def test_default_site_root_serves_every_local_navigation_link(self):
        """Every local href/src on the homepage must resolve under the served root."""
        index = DEFAULT_SITE_ROOT / "index.html"
        markup = index.read_text(encoding="utf-8")
        targets = re.findall(r'(?:href|src)="([^"]+)"', markup)
        self.assertTrue(targets, "homepage must contain navigation links")
        checked = 0
        for target in targets:
            if target.startswith(("#", "http://", "https://", "mailto:", "tel:", "data:")):
                continue
            with self.subTest(target=target):
                self.assertIsNotNone(
                    resolve_public_file(DEFAULT_SITE_ROOT, target),
                    f"homepage link does not resolve: {target}",
                )
                checked += 1
        self.assertGreater(checked, 5)

    def test_download_page_local_links_and_checksum_file_resolve(self):
        checksums = DEFAULT_SITE_ROOT / "downloads" / "SHA256SUMS.txt"
        if not checksums.is_file():
            self.skipTest("download artifacts are release files and are not part of the source snapshot")
        page = DEFAULT_SITE_ROOT / "download" / "index.html"
        markup = page.read_text(encoding="utf-8")
        targets = [
            target
            for target in re.findall(r'(?:href|src)="([^"]+)"', markup)
            if not target.startswith(("#", "http://", "https://", "mailto:", "tel:", "data:"))
        ]
        self.assertTrue(targets)
        for target in targets:
            with self.subTest(target=target):
                self.assertIsNotNone(resolve_public_file(DEFAULT_SITE_ROOT, target))
        self.assertTrue(checksums.is_file())

    def test_promo_page_local_links_and_real_media_resolve(self):
        page = DEFAULT_SITE_ROOT / "promo" / "index.html"
        markup = page.read_text(encoding="utf-8")
        targets = [
            target
            for target in re.findall(r'(?:href|src|poster)="([^"]+)"', markup)
            if not target.startswith(("#", "http://", "https://", "mailto:", "tel:", "data:"))
        ]
        self.assertTrue(targets)
        for target in targets:
            with self.subTest(target=target):
                self.assertIsNotNone(
                    resolve_public_file(DEFAULT_SITE_ROOT, target),
                    f"promo link does not resolve: {target}",
                )
        self.assertIn("Ctrl+Shift+P", markup)
        self.assertIn("Stopp des lokalen Encoders", markup)

    def test_public_site_serves_no_backup_or_secret_files(self):
        patterns = (".bak", ".save", ".before-", ".orig", ".old", ".tmp", ".log")
        offenders = []
        for path in DEFAULT_SITE_ROOT.rglob("*"):
            if not path.is_file():
                continue
            name = path.name
            if name.startswith(".env") or name in {".git", ".DS_Store"}:
                offenders.append(str(path))
            elif any(pattern in name for pattern in patterns):
                offenders.append(str(path))
        self.assertEqual(offenders, [], "public site must not serve backup or secret files")

    def test_public_downloads_contain_only_published_source_parts_and_game_prototypes(self):
        downloads = DEFAULT_SITE_ROOT / "downloads"
        if not (downloads / "streamiov-studio-part-00.bin").is_file():
            self.skipTest("download artifacts are release files and are not part of the source snapshot")
        game_prototypes = {
            "streamiov-echo-grid-0.1.0-prototype.zip",
            "streamiov-neon-relay-0.1.0-prototype.zip",
            "streamiov-pulse-defender-0.1.0-prototype.zip",
            "streamiov-signal-weave-0.1.0-prototype.zip",
            "streamiov-star-defender-0.2.0-prototype.zip",
        }
        published = {
            "SHA256SUMS.txt",
            "SHA256SUMS-games.txt",
            "SHA256SUMS.txt.sig",
            "SHA256SUMS-games.txt.sig",
            "STREAMIOV-RELEASE-KEY.pub",
            *(f"streamiov-studio-part-{index:02d}.bin" for index in range(7)),
            *game_prototypes,
        }
        actual = {path.name for path in downloads.iterdir() if path.is_file()}
        self.assertEqual(actual, published)

    def test_game_prototype_downloads_match_their_checksums(self):
        downloads = DEFAULT_SITE_ROOT / "downloads"
        checksum_file = downloads / "SHA256SUMS-games.txt"
        if not checksum_file.is_file():
            self.skipTest("game prototype downloads are release artifacts")
        import hashlib

        for line in checksum_file.read_text(encoding="utf-8").splitlines():
            if not line or line.startswith("#"):
                continue
            digest, filename = line.split(maxsplit=1)
            payload = (downloads / filename).read_bytes()
            with self.subTest(filename=filename):
                self.assertEqual(hashlib.sha256(payload).hexdigest(), digest)
                source = DEFAULT_SITE_ROOT.parents[2] / "games" / "releases" / filename
                if source.is_file():
                    self.assertEqual(payload, source.read_bytes(), f"published copy drifted from {source}")

    def test_catalog_gift_svgs_are_published_for_the_host(self):
        catalog = json.loads(
            (DEFAULT_RAW_DATA_ROOT / "game_actions" / "gift_catalog.json").read_text(encoding="utf-8")
        )
        self.assertTrue(catalog["gifts"])
        for gift in catalog["gifts"]:
            with self.subTest(gift=gift["id"]):
                self.assertTrue(gift["svg"].startswith("/assets/gifts/"))
                target = DEFAULT_SITE_ROOT / gift["svg"].lstrip("/")
                self.assertTrue(target.is_file(), f"missing published gift asset: {target}")
                self.assertTrue(target.read_text(encoding="utf-8").lstrip().startswith("<svg"))

    def test_remote_bind_requires_certificate_and_key(self):
        self.assertFalse(validate_tls_settings("127.0.0.1", None, None))
        self.assertFalse(validate_tls_settings("localhost", None, None))
        self.assertTrue(validate_tls_settings("0.0.0.0", "/cert.pem", "/key.pem"))
        self.assertTrue(validate_tls_settings("::", "/cert.pem", "/key.pem"))
        with self.assertRaises(ValueError):
            validate_tls_settings("0.0.0.0", None, None)
        with self.assertRaises(ValueError):
            validate_tls_settings("127.0.0.1", "/cert.pem", None)

    def test_local_ai_status_never_selects_cloud_provider(self):
        from host.server import local_ai_status

        with patch.dict("os.environ", {"STREAMIOV_MODEL_PROVIDER": "cloudflare-workers-ai"}):
            status = local_ai_status()
        self.assertFalse(status["ready"])
        self.assertIn("local providers only", status["detail"])

    def test_resolves_site_files_and_root_index(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "index.html").write_text("home", encoding="utf-8")
            (root / "assets").mkdir()
            (root / "assets" / "mark.svg").write_text("<svg/>", encoding="utf-8")
            self.assertEqual(resolve_public_file(root, "/"), root / "index.html")
            self.assertEqual(resolve_public_file(root, "/assets/mark.svg?v=1"), root / "assets" / "mark.svg")

    def test_rejects_traversal_hidden_files_and_missing_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "index.html").write_text("home", encoding="utf-8")
            for path in ("/../outside", "/%2e%2e/outside", "/.env", "/missing.html", "/bad%00path"):
                with self.subTest(path=path):
                    self.assertIsNone(resolve_public_file(root, path))

    def test_rejects_symlinks(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = Path(directory)
            secret = Path(outside) / "private.txt"
            secret.write_text("private", encoding="utf-8")
            try:
                (root / "link.txt").symlink_to(secret)
            except (OSError, NotImplementedError):
                self.skipTest("Symlinks are unavailable on this platform.")
            self.assertIsNone(resolve_public_file(root, "/link.txt"))

    def test_local_host_serves_home_health_and_honest_status_without_write_routes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "index.html").write_text("StreamioV local homepage", encoding="utf-8")
            (root / "section").mkdir()
            (root / "section" / "index.html").write_text("section page", encoding="utf-8")
            server = StreamioVHTTPServer(
                ("127.0.0.1", 0), Handler, root, root / "state", trust_loopback_proxy=True
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                with urlopen(base + "/", timeout=2) as response:
                    self.assertEqual(response.read(), b"StreamioV local homepage")
                    self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
                with urlopen(base + "/section/", timeout=2) as response:
                    self.assertEqual(response.read(), b"section page")
                with urlopen(base + "/healthz", timeout=2) as response:
                    health = json.loads(response.read())
                self.assertEqual(health["status"], "ok")
                with urlopen(base + "/api/v1/status", timeout=2) as response:
                    status = json.loads(response.read())
                self.assertFalse(status["api_ready"])
                self.assertTrue(status["auth_ready"])
                self.assertTrue(status["account_api_ready"])
                self.assertFalse(status["registration_open"])
                with patch.dict("os.environ", {"STREAMIOV_MODEL_PROVIDER": "cloudflare-workers-ai"}):
                    with urlopen(base + "/api/v1/ai/status", timeout=2) as response:
                        model_status = json.loads(response.read())
                self.assertFalse(model_status["ready"])
                self.assertIn("local providers only", model_status["detail"])
                origin = f"https://127.0.0.1:{server.server_port}"
                account = json.dumps({"username": "Local_Creator", "password": "a-long-local-password"}).encode()
                closed_registration = Request(base + "/api/v1/auth/register", data=account, method="POST", headers={
                    "Content-Type": "application/json", "Origin": origin, "X-Forwarded-Proto": "https",
                })
                with self.assertRaises(HTTPError) as error:
                    urlopen(closed_registration, timeout=2)
                self.assertEqual(error.exception.code, 403)
                server.registration_open = True  # Simulate the explicit --enable-registration operator flag.

                bad_origin = Request(base + "/api/v1/auth/register", data=account, method="POST", headers={
                    "Content-Type": "application/json", "Origin": "https://attacker.example",
                    "X-Forwarded-Proto": "https",
                })
                with self.assertRaises(HTTPError) as error:
                    urlopen(bad_origin, timeout=2)
                self.assertEqual(error.exception.code, 403)

                duplicate_body = b'{"username":"First","username":"Second","password":"a-long-local-password"}'
                duplicate = Request(base + "/api/v1/auth/register", data=duplicate_body, method="POST", headers={
                    "Content-Type": "application/json", "Origin": origin, "X-Forwarded-Proto": "https",
                })
                with self.assertRaises(HTTPError) as error:
                    urlopen(duplicate, timeout=2)
                self.assertEqual(error.exception.code, 400)

                register = Request(base + "/api/v1/auth/register", data=account, method="POST", headers={
                    "Content-Type": "application/json", "Origin": origin, "X-Forwarded-Proto": "https",
                })
                with urlopen(register, timeout=5) as response:
                    created = json.loads(response.read())
                    cookie = response.headers["Set-Cookie"]
                    self.assertEqual(response.status, 201)
                self.assertEqual(created["user"]["username"], "Local_Creator")
                self.assertIn("HttpOnly", cookie)
                self.assertIn("SameSite=Strict", cookie)
                self.assertIn("Secure", cookie)
                session_cookie = cookie.split(";", 1)[0]
                login = Request(base + "/api/v1/auth/login", data=account, method="POST", headers={
                    "Content-Type": "application/json", "Origin": origin, "X-Forwarded-Proto": "https",
                })
                with urlopen(login, timeout=5) as response:
                    self.assertEqual(response.status, 200)
                    session_cookie = response.headers["Set-Cookie"].split(";", 1)[0]
                current = Request(base + "/api/v1/auth/me", headers={"Cookie": session_cookie})
                with urlopen(current, timeout=2) as response:
                    self.assertEqual(json.loads(response.read())["user"]["username"], "Local_Creator")

                ai_body = b'{"request":"Testauftrag"}'
                unauthenticated_ai = Request(base + "/api/v1/ai/tasks", data=ai_body, method="POST", headers={
                    "Content-Type": "application/json", "X-Streamiov-Client": "studio",
                })
                with self.assertRaises(HTTPError) as error:
                    urlopen(unauthenticated_ai, timeout=2)
                self.assertEqual(error.exception.code, 401)

                missing_client_header = Request(base + "/api/v1/ai/tasks", data=ai_body, method="POST", headers={
                    "Content-Type": "application/json", "Cookie": session_cookie,
                })
                with self.assertRaises(HTTPError) as error:
                    urlopen(missing_client_header, timeout=2)
                self.assertEqual(error.exception.code, 403)

                ai_task = Request(base + "/api/v1/ai/tasks", data=ai_body, method="POST", headers={
                    "Content-Type": "application/json", "Cookie": session_cookie,
                    "X-Streamiov-Client": "studio",
                })
                with self.assertRaises(HTTPError) as error:
                    urlopen(ai_task, timeout=2)
                self.assertEqual(error.exception.code, 503)
                failed_task = json.loads(error.exception.read())
                self.assertEqual(failed_task["error"], "ai_execution_not_ready")
                self.assertEqual(failed_task["task"]["status"], "failed")
                self.assertTrue(failed_task["task"]["error"])

                with patch("host.server.run_local_ai_task", return_value={
                    "ok": True, "answer": "Antwort", "provider": "ollama",
                    "model": "qwen2.5-coder:7b", "execution": "read_only_local_inference",
                }):
                    with urlopen(ai_task, timeout=2) as response:
                        ai_result = json.loads(response.read())
                self.assertEqual(response.status, 200)
                self.assertEqual(ai_result["answer"], "Antwort")
                self.assertEqual(ai_result["execution"], "read_only_local_inference")
                task_id = ai_result["task_id"]
                self.assertEqual(ai_result["task"]["status"], "completed")
                self.assertEqual(ai_result["task"]["answer"], "Antwort")
                task_request = Request(base + "/api/v1/ai/tasks/" + task_id, headers={
                    "Cookie": session_cookie, "X-Streamiov-Client": "studio",
                })
                with urlopen(task_request, timeout=2) as response:
                    stored_task = json.loads(response.read())
                self.assertEqual(stored_task["task"]["id"], task_id)
                self.assertEqual(stored_task["task"]["request"], "Testauftrag")
                listing_request = Request(base + "/api/v1/ai/tasks", headers={
                    "Cookie": session_cookie, "X-Streamiov-Client": "studio",
                })
                with urlopen(listing_request, timeout=2) as response:
                    listing = json.loads(response.read())
                self.assertIn(task_id, [task["id"] for task in listing["tasks"]])
                with self.assertRaises(HTTPError) as error:
                    urlopen(Request(base + "/api/v1/ai/tasks", method="GET"), timeout=2)
                self.assertEqual(error.exception.code, 401)

                logout = Request(base + "/api/v1/auth/logout", data=b"", method="POST", headers={
                    "Origin": origin, "X-Forwarded-Proto": "https", "Cookie": session_cookie,
                })
                with urlopen(logout, timeout=2) as response:
                    self.assertEqual(response.status, 200)
                    self.assertIn("Max-Age=0", response.headers["Set-Cookie"])
                with self.assertRaises(HTTPError) as error:
                    urlopen(current, timeout=2)
                self.assertEqual(error.exception.code, 401)

                with self.assertRaises(HTTPError) as error:
                    urlopen(Request(base + "/healthz", method="POST"), timeout=2)
                self.assertEqual(error.exception.code, 405)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)


class HostCatalogApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._directory = tempfile.TemporaryDirectory()
        root = Path(cls._directory.name)
        (root / "index.html").write_text("StreamioV catalog host", encoding="utf-8")
        cls.server = StreamioVHTTPServer(
            ("127.0.0.1", 0), Handler, root, root / "state",
            raw_data_root=DEFAULT_RAW_DATA_ROOT,
        )
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)
        cls._directory.cleanup()

    def _get_json(self, path):
        with urlopen(self.base + path, timeout=3) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            return json.loads(response.read())

    def test_status_reports_the_read_only_catalog_without_claiming_a_full_api(self):
        status = self._get_json("/api/v1/status")
        self.assertFalse(status["api_ready"])
        self.assertTrue(status["catalog_ready"])
        self.assertTrue(status["catalog_read_only"])
        self.assertEqual(status["catalog_counts"]["gifts"], 18)
        self.assertEqual(status["data_store"]["counts"]["games"], 2)
        self.assertFalse(status["data_store"]["legacy_databases_read"])
        self.assertFalse(status["ai_execution_ready"])
        self.assertTrue(status["ai_task_endpoint_ready"])
        self.assertTrue(status["event_ledger_ready"])
        self.assertEqual(status["event_schema_version"], 1)
        self.assertFalse(status["platform_integrations_ready"])

    def test_gift_catalog_is_seeded_from_repository_json(self):
        catalog = self._get_json("/api/v1/catalog/gifts")
        self.assertTrue(catalog["ok"])
        self.assertTrue(catalog["read_only"])
        self.assertEqual(catalog["counts"], {"gifts": 18, "rules": 2, "like_milestones": 3})
        self.assertFalse(catalog["tiktok_gift_ids_present"])
        self.assertEqual(catalog["like_milestones"], [10000, 15000, 20000])
        self.assertTrue(all(gift["tiktok_gift_id"] is None for gift in catalog["gifts"]))
        self.assertTrue(all(rule["status"] == "planned" for rule in catalog["rules"]))
        self.assertIn("keine TikTok-Coins", catalog["points_note"])

    def test_games_music_and_templates_are_read_from_the_catalog(self):
        games = self._get_json("/api/v1/catalog/games")
        self.assertEqual(games["counts"], {"games": 2, "actions": 3})
        self.assertTrue(all(game["interface_status"] == "test" for game in games["games"]))

        music = self._get_json("/api/v1/music/library")
        self.assertEqual(music["counts"], {"playlists": 1, "tracks": 1, "rights_tracks": 0})
        self.assertEqual(music["playlists"][0]["tracks"][0]["rights_status"], "test-only")

        templates = self._get_json("/api/v1/studio/templates")
        self.assertEqual(templates["counts"], {"templates": 5})
        self.assertTrue(all(template["local_only"] for template in templates["templates"]))

        summary = self._get_json("/api/v1/catalog")
        self.assertTrue(summary["ok"])
        self.assertEqual(summary["counts"]["gift_rules"], 2)
        self.assertFalse(summary["legacy_databases_read"])

    def test_catalog_is_read_only_and_unknown_paths_are_not_found(self):
        post = Request(self.base + "/api/v1/catalog/gifts", data=b"", method="POST")
        with self.assertRaises(HTTPError) as error:
            urlopen(post, timeout=2)
        self.assertEqual(error.exception.code, 405)
        with self.assertRaises(HTTPError) as error:
            urlopen(self.base + "/api/v1/catalog/unknown", timeout=2)
        self.assertEqual(error.exception.code, 404)


class LocalAiAssistantTests(unittest.TestCase):
    def test_read_only_inference_returns_only_the_model_answer(self):
        from ai.providers.base import ModelReply

        class Provider:
            def check_ready(self):
                return {"ready": True, "detail": "ready"}

            def generate(self, *, system, messages):
                self.system = system
                self.messages = messages
                return ModelReply('{"answer":"Nur eine Antwort."}', "ollama", "local-model")

        provider = Provider()
        with patch("host.server.local_ai_provider", return_value=provider):
            result = run_local_ai_task("Erkläre den Status.")
        self.assertEqual(result["answer"], "Nur eine Antwort.")
        self.assertEqual(result["execution"], "read_only_local_inference")
        self.assertIn("no tools", provider.system)
        self.assertEqual(provider.messages, [{"role": "user", "content": "Erkläre den Status."}])

    def test_unready_local_model_is_rejected(self):
        from ai.providers.local_http import ProviderError

        class Provider:
            def check_ready(self):
                return {"ready": False, "detail": "model missing"}

        with patch("host.server.local_ai_provider", return_value=Provider()):
            with self.assertRaisesRegex(ProviderError, "model missing"):
                run_local_ai_task("Testauftrag")


class HostIntegrityTests(unittest.TestCase):
    @staticmethod
    @contextmanager
    def running_server(root: Path):
        server = StreamioVHTTPServer(
            ("127.0.0.1", 0), Handler, root, root / "state", trust_loopback_proxy=True
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield server, f"http://127.0.0.1:{server.server_port}"
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    @staticmethod
    def prepare_root(root: Path) -> None:
        (root / "index.html").write_text("StreamioV local homepage", encoding="utf-8")

    def test_healthz_and_status_report_real_store_integrity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.prepare_root(root)
            with self.running_server(root) as (_, base):
                with urlopen(base + "/healthz", timeout=5) as response:
                    health = json.loads(response.read())
                self.assertEqual(response.status, 200)
                self.assertEqual(health["status"], "ok")
                self.assertEqual(set(health["stores"]), {"accounts", "forum", "catalog", "ai_tasks", "events", "music_state", "wishbox"})
                for store in health["stores"].values():
                    self.assertTrue(store["ok"])
                with urlopen(base + "/api/v1/status", timeout=5) as response:
                    status = json.loads(response.read())
                self.assertTrue(status["auth_ready"])
                self.assertTrue(status["account_api_ready"])
                self.assertTrue(status["forum_ready"])
                self.assertTrue(status["catalog_ready"])
                self.assertTrue(status["ai_tasks_ready"])
                self.assertTrue(status["event_ledger_ready"])
                self.assertEqual(status["stores"], health["stores"])

    def test_corrupt_account_database_degrades_health_and_status(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.prepare_root(root)
            with self.running_server(root) as (_, base):
                database = root / "state" / "accounts.sqlite3"
                database.write_bytes(b"this is not a sqlite database")
                for suffix in ("-wal", "-shm"):
                    (root / "state" / f"accounts.sqlite3{suffix}").unlink(missing_ok=True)
                with self.assertRaises(HTTPError) as error:
                    urlopen(base + "/healthz", timeout=5)
                self.assertEqual(error.exception.code, 503)
                health = json.loads(error.exception.read())
                self.assertEqual(health["status"], "degraded")
                self.assertEqual(set(health["stores"]), {"accounts", "forum", "catalog", "ai_tasks", "events", "music_state", "wishbox"})
                self.assertFalse(health["stores"]["accounts"]["ok"])
                self.assertIn(
                    health["stores"]["accounts"]["error"],
                    ("database_corrupt", "database_unavailable"),
                )
                with urlopen(base + "/api/v1/status", timeout=5) as response:
                    status = json.loads(response.read())
                self.assertFalse(status["auth_ready"])
                self.assertFalse(status["account_api_ready"])
                self.assertFalse(status["stores"]["accounts"]["ok"])

    def test_legacy_forum_schema_is_migrated_before_indexes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.prepare_root(root)
            state = root / "state"
            state.mkdir()
            database = state / "forum.sqlite3"
            with closing(sqlite3.connect(database)) as db, db:
                db.executescript("""
                    CREATE TABLE threads (
                        thread_id TEXT PRIMARY KEY,
                        title TEXT NOT NULL,
                        body TEXT NOT NULL,
                        author_user_id TEXT NOT NULL,
                        author_name TEXT NOT NULL,
                        created_at INTEGER NOT NULL
                    );
                    CREATE TABLE replies (
                        reply_id TEXT PRIMARY KEY,
                        thread_id TEXT NOT NULL REFERENCES threads(thread_id) ON DELETE CASCADE,
                        body TEXT NOT NULL,
                        author_user_id TEXT NOT NULL,
                        author_name TEXT NOT NULL,
                        created_at INTEGER NOT NULL
                    );
                """)
            with self.running_server(root) as (_, base):
                with urlopen(base + "/healthz", timeout=5) as response:
                    health = json.loads(response.read())
                self.assertEqual(health["status"], "ok")
                self.assertTrue(health["stores"]["forum"]["ok"])
                with closing(sqlite3.connect(database)) as db:
                    thread_columns = {row[1] for row in db.execute("PRAGMA table_info(threads)")}
                    reply_columns = {row[1] for row in db.execute("PRAGMA table_info(replies)")}
                self.assertIn("locked", thread_columns)
                self.assertIn("deleted", thread_columns)
                self.assertIn("deleted", reply_columns)


if __name__ == "__main__":
    unittest.main()
