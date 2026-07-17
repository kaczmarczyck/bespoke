# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Unit tests for the simplified static and DB decks server."""

from http.server import HTTPServer
from pathlib import Path
import tempfile
import threading
import unittest

import httpx

import server


class TestServerStatic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 1. Bind to port 0 to get a random available local port
        cls.httpd = HTTPServer(("127.0.0.1", 0), server.BespokeAPIHandler)
        cls.port = cls.httpd.server_address[1]
        cls.server_thread = threading.Thread(
            target=cls.httpd.serve_forever, daemon=True
        )
        cls.server_thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.port}"

        # 2. Setup a temporary directory for cards, bypassing cards folder
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.temp_path = Path(cls.temp_dir.name)
        cls.cards_dir = cls.temp_path / "cards"
        cls.cards_dir.mkdir()

        # Patch server cards path
        cls.original_cards_dir = Path("cards")

        # Create a mock database file
        cls.db_filename = "simp_chinese_german.db"
        cls.db_file = cls.cards_dir / cls.db_filename
        cls.db_file.write_bytes(b"SQLite mock database bytes")

        # Temporarily mock get_available_db_decks to look into cls.cards_dir
        cls.original_get_decks = server.get_available_db_decks

        def mock_get_decks():
            # Temporarily redirect cards path
            original_path = server.Path

            class MockPath:
                def __init__(self, name):
                    self.name = name

                def exists(self):
                    return cls.cards_dir.exists()

                def glob(self, pattern):
                    return cls.cards_dir.glob(pattern)

            server.Path = MockPath
            try:
                return cls.original_get_decks()
            finally:
                server.Path = original_path

        server.get_available_db_decks = mock_get_decks

    @classmethod
    def tearDownClass(cls):
        # Restore mock patches
        server.get_available_db_decks = cls.original_get_decks

        # Shutdown HTTPServer
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.server_thread.join()

        # Clean up temp directory
        cls.temp_dir.cleanup()

    def test_get_decks_list(self):
        response = httpx.get(f"{self.base_url}/api/decks")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("decks", data)
        self.assertIn("languages", data)

        # Verify the mock db file is found in the list of decks
        deck_names = [d["filename"] for d in data["decks"]]
        self.assertIn(self.db_filename, deck_names)

        # Verify languages are listed
        lang_names = [lang["code_name"] for lang in data["languages"]]
        self.assertIn("german", lang_names)
        self.assertIn("simp_chinese", lang_names)

    def test_serve_static_index(self):
        response = httpx.get(f"{self.base_url}/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers.get("Content-Type", ""))
        self.assertIn("Bespoke", response.text)

    def test_serve_static_css(self):
        response = httpx.get(f"{self.base_url}/style.css")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/css", response.headers.get("Content-Type", ""))


if __name__ == "__main__":
    unittest.main()
