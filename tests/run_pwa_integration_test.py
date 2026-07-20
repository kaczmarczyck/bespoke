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

"""Headless Chrome integration tests for Bespoke PWA client app."""

import asyncio
import json
import os
import shutil
import signal
import subprocess
import time
import urllib.request
from pathlib import Path
import websockets


async def test_pwa():
    # 1. Start server on port 8089
    server_process = subprocess.Popen(
        ["uv", "run", "learn.py", "--port", "8089"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        preexec_fn=os.setsid,
    )
    time.sleep(1.5)  # Wait for server to start

    # 2. Start headless chrome
    chrome_profile_dir = Path(__file__).parent / "chrome_profile_integration"
    if chrome_profile_dir.exists():
        try:
            shutil.rmtree(chrome_profile_dir)
        except Exception:
            pass
    chrome_profile_dir.mkdir(parents=True, exist_ok=True)

    chrome_env = os.environ.copy()
    chrome_env["DISPLAY"] = ""
    chrome_env["WAYLAND_DISPLAY"] = ""
    chrome_env["DBUS_SESSION_BUS_ADDRESS"] = ""

    chrome_process = subprocess.Popen(
        [
            "google-chrome",
            "--headless",
            "--disable-gpu",
            f"--user-data-dir={chrome_profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--remote-debugging-port=9222",
            "http://localhost:8089/",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        preexec_fn=os.setsid,
        env=chrome_env,
    )
    time.sleep(2)  # Wait for chrome to initialize

    # 3. Fetch DevTools targets
    try:
        req = urllib.request.urlopen("http://localhost:9222/json/list")
        targets = json.loads(req.read().decode())
        target = next(t for t in targets if t["type"] == "page")
        ws_url = target["webSocketDebuggerUrl"]
    except Exception as e:
        print("Failed to get DevTools targets:", e)
        cleanup(server_process, chrome_process)
        return

    print(f"Connected to Chrome WebSocket: {ws_url}")

    # 4. Connect to websocket
    async with websockets.connect(ws_url) as ws:
        # Enable runtime & console logs
        await ws.send(json.dumps({"id": 1, "method": "Runtime.enable"}))
        await ws.send(json.dumps({"id": 2, "method": "Log.enable"}))

        # We will wait for 2 seconds to let page initialize and fetch decks
        await asyncio.sleep(2)

        # Read all console messages from the queue
        logs = []
        errors = []

        async def listen_logs():
            try:
                while True:
                    msg_str = await asyncio.wait_for(ws.recv(), timeout=0.5)
                    msg = json.loads(msg_str)

                    # Uncaught exceptions
                    if msg.get("method") == "Runtime.exceptionThrown":
                        details = msg["params"]["exceptionDetails"]
                        err_text = details.get("text", "")
                        if (
                            "exception" in details
                            and "description" in details["exception"]
                        ):
                            err_text += " " + details["exception"]["description"]
                        errors.append(err_text)
                        print(f"[BROWSER EXCEPTION] {err_text}")

                    # Console API calls (console.log, console.error)
                    elif msg.get("method") == "Runtime.consoleAPICalled":
                        args = msg["params"]["args"]
                        val = " ".join(
                            str(a.get("value", a.get("description", ""))) for a in args
                        )
                        logs.append(val)
                        print(f"[BROWSER CONSOLE] {val}")
            except asyncio.TimeoutError:
                pass

        await listen_logs()

        # Evaluate Target Languages dropdown option values
        await ws.send(
            json.dumps(
                {
                    "id": 10,
                    "method": "Runtime.evaluate",
                    "params": {
                        "expression": "Array.from(document.getElementById('select-target').options).map(o => o.value + ':' + o.textContent)",
                        "returnByValue": True,
                    },
                }
            )
        )

        res_str = await ws.recv()
        res = json.loads(res_str)
        print(f"Raw evaluate result: {res}")
        options = []
        if (
            "result" in res
            and "result" in res["result"]
            and res["result"]["result"].get("value")
        ):
            options = res["result"]["result"]["value"]

        print("\nTarget Language Options found in page:")
        for opt in options:
            print(f" - {opt}")

        # Let's check if the Target Language has actual languages or only the placeholder
        print(f"\nDropdown options count: {len(options)}")

        # Assertions/Checks
        if len(options) <= 1:
            print("ERROR: Target language dropdown has no options!")
        else:
            print("SUCCESS: Target language dropdown is populated!")

        if errors:
            print(f"ERROR: {len(errors)} browser exceptions occurred!")
        else:
            print("SUCCESS: No browser exceptions occurred!")

    cleanup(server_process, chrome_process)


def cleanup(server_process, chrome_process):
    # Kill process groups to kill all children
    try:
        os.killpg(os.getpgid(server_process.pid), signal.SIGTERM)
    except Exception:
        pass
    try:
        os.killpg(os.getpgid(chrome_process.pid), signal.SIGTERM)
    except Exception:
        pass
    print("Cleaned up server and browser processes.")


if __name__ == "__main__":
    asyncio.run(test_pwa())
