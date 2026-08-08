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

"""Entry point to launch the Bespoke static server and open the web UI."""

import argparse
import os
import sys
import threading
import webbrowser

# Ensure the workspace root is in sys.path to find bespoke package
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import server


def main():
    parser = argparse.ArgumentParser(description="Start learning with Bespoke.")
    parser.add_argument(
        "--port", type=int, default=8080, help="Local server port to run on."
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not open a browser window automatically.",
    )
    args = parser.parse_args()

    port = int(os.environ.get("PORT", args.port))

    if not args.no_browser and not os.environ.get("BESPOKE_NO_BROWSER"):

        def launch_browser():
            webbrowser.open(f"http://localhost:{port}/")

        threading.Timer(0.5, launch_browser).start()

    server.run_server(port)


if __name__ == "__main__":
    main()
