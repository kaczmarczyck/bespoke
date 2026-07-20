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

"""Local static and database asset server for the Bespoke PWA app."""

import json
import os
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from socketserver import ThreadingMixIn
from urllib.parse import urlparse

# Ensure the workspace root is in sys.path to find bespoke package
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from bespoke import languages

MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".mjs": "application/javascript; charset=utf-8",
    ".wasm": "application/wasm",
    ".svg": "image/svg+xml",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".ico": "image/x-icon",
    ".ogg": "audio/ogg",
    ".csv": "text/csv; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
}


def get_available_db_decks():
    decks = []
    cards_dir = Path("cards")
    if not cards_dir.exists():
        return decks

    for db_file in cards_dir.glob("*.db"):
        stem = db_file.stem
        target_code = None
        native_code = None
        # Match target & native from the filename based on registered languages
        for code_name in languages.LANGUAGES.keys():
            if stem.startswith(code_name + "_"):
                t_code = code_name
                n_code = stem[len(code_name) + 1 :]
                if n_code in languages.LANGUAGES:
                    target_code = t_code
                    native_code = n_code
                    break

        if target_code and native_code:
            t_lang = languages.LANGUAGES[target_code]
            n_lang = languages.LANGUAGES[native_code]
            decks.append(
                {
                    "filename": db_file.name,
                    "target_language": t_lang.code_name,
                    "native_language": n_lang.code_name,
                    "target_writing_system": t_lang.writing_system,
                    "native_writing_system": n_lang.writing_system,
                    "difficulty": "A1",
                    "modes": ["listen", "speak", "read", "write"],
                }
            )
    return decks


def get_available_languages():
    available = []
    for lang in languages.LANGUAGES.values():
        available.append(
            {
                "code_name": lang.code_name,
                "name": lang.name,
                "writing_system": lang.writing_system,
                "has_data": lang.has_data(),
            }
        )
    return available


def is_safe_path(base_dir: Path, path: Path) -> bool:
    base_abs = base_dir.resolve()
    try:
        path_abs = path.resolve()
    except FileNotFoundError:
        path_abs = Path(os.path.abspath(path))
    try:
        common = os.path.commonpath([str(base_abs), str(path_abs)])
        return common == str(base_abs)
    except ValueError:
        return False


class BespokeAPIHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Silence standard HTTP logs to keep console clean
        pass

    def send_error_response(self, status_code, message):
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        self.end_headers()
        self.wfile.write(json.dumps({"error": message}).encode("utf-8"))

    def send_json_response(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def serve_static_file(self, file_path):
        if not file_path.exists() or not file_path.is_file():
            # Fallback to index.html for SPA routing
            if file_path.parts and file_path.parts[0] == "web":
                file_path = Path("web/index.html")
            else:
                self.send_error(404, "File not found")
                return

        ext = file_path.suffix
        content_type = MIME_TYPES.get(ext, "application/octet-stream")

        try:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cross-Origin-Opener-Policy", "same-origin")
            self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
            self.send_header("Content-Length", str(file_path.stat().st_size))
            self.end_headers()

            with open(file_path, "rb") as f:
                while True:
                    chunk = f.read(64 * 1024)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        except Exception as e:
            print(f"Error serving file {file_path}: {e}")

    def do_GET(self):
        parsed_url = urlparse(self.path)
        path = parsed_url.path

        # 1. API Endpoints
        if path == "/api/decks":
            decks = get_available_db_decks()
            langs = get_available_languages()
            self.send_json_response({"decks": decks, "languages": langs})
            return

        # 2. Static Assets Routing
        parts = Path(path.lstrip("/")).parts
        if not parts:
            file_to_serve = Path("web/index.html")
            base_dir = Path("web")
        elif parts[0] == "cards":
            file_to_serve = Path(path.lstrip("/"))
            base_dir = Path("cards")
        elif parts[0] == "languages":
            file_to_serve = Path(path.lstrip("/"))
            base_dir = Path("languages")
        else:
            file_to_serve = Path("web") / Path(path.lstrip("/"))
            base_dir = Path("web")

        if not is_safe_path(base_dir, file_to_serve):
            self.send_error(403, "Access denied")
            return

        if base_dir == Path("web") and (
            not file_to_serve.exists() or file_to_serve.is_dir()
        ):
            file_to_serve = Path("web/index.html")

        self.serve_static_file(file_to_serve)


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


def run_server(port=8080):
    server_address = ("127.0.0.1", port)
    httpd = ThreadedHTTPServer(server_address, BespokeAPIHandler)
    print(f"Bespoke backend static server running on http://localhost:{port}/")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
        httpd.server_close()


if __name__ == "__main__":
    run_server()
