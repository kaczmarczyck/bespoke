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

"""Helper script to download SQLite WASM and JS binaries from jsdelivr for offline usage."""

import urllib.request
from pathlib import Path

WEB_DIR = Path("web")

# We download the latest version files from the 'dist' directory of npm package
FILES_TO_DOWNLOAD = {
    "index.mjs": "https://cdn.jsdelivr.net/npm/@sqlite.org/sqlite-wasm/dist/index.mjs",
    "sqlite3.wasm": "https://cdn.jsdelivr.net/npm/@sqlite.org/sqlite-wasm/dist/sqlite3.wasm",
    "sqlite3-opfs-async-proxy.js": "https://cdn.jsdelivr.net/npm/@sqlite.org/sqlite-wasm/dist/sqlite3-opfs-async-proxy.js",
    "sqlite3-worker1.mjs": "https://cdn.jsdelivr.net/npm/@sqlite.org/sqlite-wasm/dist/sqlite3-worker1.mjs",
}


def download_file(url, dest_path):
    print(f"Downloading {url} to {dest_path}...")
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            },
        )
        with urllib.request.urlopen(req) as response:
            with open(dest_path, "wb") as f:
                f.write(response.read())
        print("Success!")
    except Exception as e:
        print(f"Failed to download: {e}")


def main():
    WEB_DIR.mkdir(parents=True, exist_ok=True)

    for filename, url in FILES_TO_DOWNLOAD.items():
        dest = WEB_DIR / filename
        download_file(url, dest)


if __name__ == "__main__":
    main()
