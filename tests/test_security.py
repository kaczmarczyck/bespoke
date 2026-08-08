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

import unittest
import subprocess
import time
import urllib.request
import urllib.error
import os
import signal


class TestServerSecurity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = 8090
        # Start server
        cls.server_process = subprocess.Popen(
            ["uv", "run", "learn.py", "--port", str(cls.port), "--no-browser"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            preexec_fn=os.setsid,
        )
        time.sleep(1.5)  # Wait for server to start

    @classmethod
    def tearDownClass(cls):
        # Kill server
        try:
            os.killpg(os.getpgid(cls.server_process.pid), signal.SIGTERM)
        except Exception:
            pass

    def test_safe_paths(self):
        # web/index.html (should exist)
        try:
            req = urllib.request.urlopen(f"http://127.0.0.1:{self.port}/index.html")
            self.assertEqual(req.status, 200)
        except Exception as e:
            self.fail(f"Failed to access web/index.html: {e}")

        # cards/german_english.db (should exist based on list_dir)
        try:
            req = urllib.request.urlopen(
                f"http://127.0.0.1:{self.port}/cards/german_english.db"
            )
            self.assertEqual(req.status, 200)
        except Exception as e:
            self.fail(f"Failed to access cards/german_english.db: {e}")

    def test_path_traversal(self):
        # Paths that attempt to escape their document root and should be blocked with 403
        escaping_paths = [
            "/web/../../server.py",
            "/cards/../server.py",
            "/cards/../../../../etc/passwd",
            "/../server.py",
        ]
        for path in escaping_paths:
            with self.subTest(path=path):
                try:
                    urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}")
                    self.fail(f"Managed to access unsafe path: {path}")
                except urllib.error.HTTPError as e:
                    self.assertEqual(
                        e.code, 403, f"Expected 403 for {path}, got {e.code}"
                    )
                except Exception as e:
                    self.fail(f"Unexpected exception for {path}: {e}")

    def test_web_prefix_fallback(self):
        # /web/../server.py resolves to web/server.py due to routing.
        # It doesn't exist, so it should fallback to index.html (200),
        # but it MUST NOT contain server.py content.
        path = "/web/../server.py"
        try:
            req = urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}")
            self.assertEqual(req.status, 200)
            content = req.read().decode("utf-8")
            self.assertNotIn(
                "BespokeAPIHandler", content, "Should not leak server.py content"
            )
            self.assertIn("<!DOCTYPE html>", content, "Should return index.html")
        except Exception as e:
            self.fail(f"Failed to access {path}: {e}")


if __name__ == "__main__":
    unittest.main()
