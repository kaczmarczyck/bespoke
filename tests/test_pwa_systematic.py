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

"""Systematic end-to-end PWA integration tests running via Chrome DevTools Protocol."""

import asyncio
import json
import os
import signal
import subprocess
import threading
import time
import urllib.request
import unittest
from pathlib import Path
import websockets

from tests import compile_tiny_test_dbs


class TestPWASystematic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 1. Compile tiny mock SQLite databases using package_db pathway
        print("Compiling mock databases for integration testing...")
        compile_tiny_test_dbs.main()

    def test_pwa_systematic_flow(self):
        # Run the async flow using asyncio
        asyncio.run(self.run_pwa_flow())

    async def run_pwa_flow(self):
        print("=== STARTING PWA SYSTEMATIC INTEGRATION TEST ===")

        # 1. Start learn.py server
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        server_process = subprocess.Popen(
            ["uv", "run", "learn.py", "--port", "8089"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            preexec_fn=os.setsid,
            text=True,
            env=env,
        )

        # Read server logs in background
        def read_stream(stream, prefix):
            for line in iter(stream.readline, ""):
                print(f"{prefix} {line.strip()}")

        threading.Thread(
            target=read_stream,
            args=(server_process.stdout, "[SERVER OUT]"),
            daemon=True,
        ).start()
        threading.Thread(
            target=read_stream,
            args=(server_process.stderr, "[SERVER ERR]"),
            daemon=True,
        ).start()

        time.sleep(1.5)

        # 2. Start headless chrome with remote debugging
        chrome_profile_dir = Path(__file__).parent / "chrome_profile"
        import shutil

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
                "--remote-debugging-port=9228",
                "http://localhost:8089/?no-sw",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            preexec_fn=os.setsid,
            env=chrome_env,
        )
        time.sleep(2)

        # 3. Get WebSocket debugging URL
        try:
            req = urllib.request.urlopen("http://localhost:9228/json/list")
            targets = json.loads(req.read().decode())
            target = next(t for t in targets if t["type"] == "page")
            ws_url = target["webSocketDebuggerUrl"]
        except Exception as e:
            self.cleanup(server_process, chrome_process)
            self.fail(f"Failed to locate Chrome target page: {e}")

        print(f"CDP connected to Chrome at: {ws_url}")

        errors = []

        try:
            async with websockets.connect(ws_url) as ws:
                # Enable protocol domains
                await ws.send(json.dumps({"id": 1, "method": "Runtime.enable"}))
                await ws.send(json.dumps({"id": 2, "method": "Log.enable"}))
                await ws.send(json.dumps({"id": 3, "method": "Page.enable"}))

                # Store future responses by their message ID
                pending_responses = {}

                # Listen for events and populate responses in a single loop
                async def main_receiver_loop():
                    try:
                        while True:
                            msg_str = await ws.recv()
                            msg = json.loads(msg_str)

                            if "id" in msg:
                                pending_responses[msg["id"]] = msg
                            elif msg.get("method") == "Runtime.consoleAPICalled":
                                args = msg["params"]["args"]
                                val = " ".join(
                                    str(a.get("value", a.get("description", "")))
                                    for a in args
                                )
                                print(f" [CONSOLE] {val}")
                            elif msg.get("method") == "Runtime.exceptionThrown":
                                desc = (
                                    msg["params"]["exceptionDetails"]
                                    .get("exception", {})
                                    .get("description", "")
                                )
                                print(f" [EXCEPTION] {desc}")
                                errors.append(desc)
                            elif msg.get("method") == "Page.javascriptDialogOpening":
                                message = msg["params"].get("message", "")
                                print(f" [ALERT] Auto-accepting alert: {message}")
                                asyncio.create_task(
                                    ws.send(
                                        json.dumps(
                                            {
                                                "id": 9999,
                                                "method": "Page.handleJavaScriptDialog",
                                                "params": {"accept": True},
                                            }
                                        )
                                    )
                                )
                    except asyncio.CancelledError:
                        pass
                    except Exception as e:
                        print("Receiver loop stopped:", e)

                receiver_task = asyncio.create_task(main_receiver_loop())

                # Helper to send a command and wait for response
                msg_counter = 100

                async def send_cmd(method, params=None):
                    nonlocal msg_counter
                    msg_counter += 1
                    payload = {
                        "id": msg_counter,
                        "method": method,
                        "params": params or {},
                    }
                    await ws.send(json.dumps(payload))
                    return msg_counter

                async def eval_js(expression):
                    cid = await send_cmd(
                        "Runtime.evaluate",
                        {"expression": expression, "returnByValue": True},
                    )
                    # Poll pending_responses for our ID
                    for _ in range(100):  # Timeout after 10 seconds
                        if cid in pending_responses:
                            msg = pending_responses.pop(cid)
                            if "result" in msg and "result" in msg["result"]:
                                res = msg["result"]["result"]
                                if msg["result"].get("exceptionDetails"):
                                    raise Exception(
                                        f"JS Exception: {res.get('description')}"
                                    )
                                return res.get("value")
                            raise Exception(f"Invalid response: {msg}")
                        await asyncio.sleep(0.1)
                    raise Exception(
                        f"CDP command {cid} timed out waiting for response!"
                    )

                try:
                    # Let the page initialize and fetch the deck list
                    await asyncio.sleep(2)

                    # --- Test Step 1: Verify Language Dropdowns ---
                    print("\n--- Test Step 1: Checking dropdown languages ---")
                    sqlite_keys = await eval_js(
                        "window.sqlite3 ? Object.keys(window.sqlite3) : []"
                    )
                    print(f"sqlite3 keys: {sqlite_keys}")
                    targets = await eval_js(
                        "Array.from(document.getElementById('select-target').options).map(o => o.value)"
                    )
                    print(f"Target languages options: {targets}")
                    self.assertIn(
                        "german",
                        targets,
                        "German not available in target language select options",
                    )
                    print("Step 1 Success!")

                    # --- Test Step 2: Trigger Download ---
                    print("\n--- Test Step 2: Downloading German-English deck ---")
                    has_download = await eval_js(
                        '!!document.querySelector(\'button[data-target="german"][data-native="english"].download-db-btn\')'
                    )
                    self.assertTrue(
                        has_download,
                        "German-English download button not found in deck list!",
                    )

                    await eval_js(
                        'document.querySelector(\'button[data-target="german"][data-native="english"].download-db-btn\').click()'
                    )
                    print(
                        "Download clicked. Waiting 5 seconds for download and OPFS store completion..."
                    )
                    await asyncio.sleep(5)
                    print("Step 2 Success!")

                    # --- Test Step 3: Start Study / Play ---
                    print("\n--- Test Step 3: Clicking Play to start studying ---")
                    has_play = await eval_js(
                        "!!document.querySelector('button[data-filename=\"german_english.db\"].play-deck-btn')"
                    )
                    self.assertTrue(has_play, "German-English play button not found!")

                    await eval_js(
                        "document.querySelector('button[data-filename=\"german_english.db\"].play-deck-btn').click()"
                    )
                    await asyncio.sleep(1.5)  # Let screen transition

                    is_study_active = await eval_js(
                        "document.getElementById('screen-study').classList.contains('active')"
                    )
                    self.assertTrue(
                        is_study_active,
                        "Study screen is not active after clicking Play!",
                    )
                    print("Step 3 Success! transitioned to study screen.")

                    # --- Test Step 4: Verify Card Loaded ---
                    print("\n--- Test Step 4: Verifying card front is rendered ---")
                    front_text = await eval_js(
                        "document.getElementById('card-front-text').textContent.trim()"
                    )
                    print(f"Card front text: '{front_text}'")
                    self.assertTrue(
                        front_text and front_text != "---",
                        "Flashcard front text did not load properly!",
                    )
                    print("Step 4 Success!")

                    # --- Test Step 5: Flip Card ---
                    print("\n--- Test Step 5: Flipping the card ---")
                    await eval_js("document.getElementById('btn-flip').click()")
                    await asyncio.sleep(0.5)

                    is_flipped = await eval_js(
                        "document.getElementById('flashcard').classList.contains('flipped')"
                    )
                    self.assertTrue(
                        is_flipped,
                        "Card does not have 'flipped' class after clicking flip!",
                    )
                    print("Step 5 Success!")

                    # --- Test Step 6: All Success & Next Card ---
                    print("\n--- Test Step 6: Rating words and drawing next card ---")
                    await eval_js("document.getElementById('btn-all-green').click()")
                    await asyncio.sleep(0.5)

                    # Click "Next Card"
                    await eval_js("document.getElementById('btn-next').click()")
                    await asyncio.sleep(1.5)

                    # Verify new front text is loaded (meaning drawNextCard succeeded and card unflipped)
                    is_unflipped = await eval_js(
                        "!document.getElementById('flashcard').classList.contains('flipped')"
                    )
                    self.assertTrue(
                        is_unflipped, "Card did not unflip after clicking Next Card!"
                    )

                    next_front_text = await eval_js(
                        "document.getElementById('card-front-text').textContent.trim()"
                    )
                    print(f"Next card front text: '{next_front_text}'")
                    self.assertTrue(
                        next_front_text and next_front_text != "---",
                        "New flashcard did not draw or load properly!",
                    )
                    print("Step 6 Success!")

                    # --- Test Step 7: Go back to deck list ---
                    print("\n--- Test Step 7: Returning to home screen ---")
                    await eval_js(
                        "document.getElementById('btn-back-to-decks').click()"
                    )
                    await asyncio.sleep(1.0)
                    is_home_active = await eval_js(
                        "document.getElementById('screen-decks').classList.contains('active')"
                    )
                    self.assertTrue(
                        is_home_active, "Home screen not active after clicking Back!"
                    )
                    print("Step 7 Success!")

                    # --- Test Step 8: Download & Play Traditional Chinese deck ---
                    print("\n--- Test Step 8: Downloading Traditional Chinese deck ---")
                    has_chinese_download = await eval_js(
                        '!!document.querySelector(\'button[data-target="trad_chinese"][data-native="german"].download-db-btn\')'
                    )
                    self.assertTrue(
                        has_chinese_download,
                        "Traditional Chinese-German download button not found!",
                    )

                    await eval_js(
                        'document.querySelector(\'button[data-target="trad_chinese"][data-native="german"].download-db-btn\').click()'
                    )
                    print("Download clicked. Waiting 5 seconds...")
                    await asyncio.sleep(5)
                    print("Step 8 Success!")

                    # --- Test Step 9: Start studying Traditional Chinese ---
                    print(
                        "\n--- Test Step 9: Clicking Play for Traditional Chinese deck ---"
                    )
                    has_chinese_play = await eval_js(
                        "!!document.querySelector('button[data-filename=\"trad_chinese_german.db\"].play-deck-btn')"
                    )
                    self.assertTrue(
                        has_chinese_play, "Traditional Chinese play button not found!"
                    )

                    await eval_js(
                        "document.querySelector('button[data-filename=\"trad_chinese_german.db\"].play-deck-btn').click()"
                    )
                    await asyncio.sleep(1.5)

                    is_study_active = await eval_js(
                        "document.getElementById('screen-study').classList.contains('active')"
                    )
                    self.assertTrue(
                        is_study_active,
                        "Study screen is not active for Traditional Chinese deck!",
                    )
                    print("Step 9 Success!")

                    # --- Test Step 10: Verify Chinese card front and flip ---
                    print("\n--- Test Step 10: Verifying card front and flipping ---")
                    ch_front_text = await eval_js(
                        "document.getElementById('card-front-text').textContent.trim()"
                    )
                    print(f"Chinese card front text: '{ch_front_text}'")
                    self.assertTrue(
                        ch_front_text and ch_front_text != "---",
                        "Chinese card front did not load properly!",
                    )

                    await eval_js("document.getElementById('btn-flip').click()")
                    await asyncio.sleep(0.5)

                    is_flipped = await eval_js(
                        "document.getElementById('flashcard').classList.contains('flipped')"
                    )
                    self.assertTrue(
                        is_flipped, "Traditional Chinese card did not flip!"
                    )
                    print("Step 10 Success!")

                    # --- Test Step 11: Verify ratings buttons and click Next ---
                    print(
                        "\n--- Test Step 11: Verifying rating buttons exist and progressing ---"
                    )
                    has_word_btns = await eval_js(
                        "document.querySelectorAll('#word-badge-grid .word-btn').length > 0"
                    )
                    self.assertTrue(
                        has_word_btns,
                        "No word rating buttons rendered on back of card!",
                    )

                    # Click all green
                    await eval_js("document.getElementById('btn-all-green').click()")
                    await asyncio.sleep(0.5)

                    # Dispatch Enter keypress to progress to next card
                    await eval_js(
                        "window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));"
                    )
                    await asyncio.sleep(1.5)

                    ch_next_front = await eval_js(
                        "document.getElementById('card-front-text').textContent.trim()"
                    )
                    print(f"Chinese next card front text: '{ch_next_front}'")
                    self.assertTrue(
                        ch_next_front and ch_next_front != "---",
                        "Chinese next card did not draw properly!",
                    )
                    print("Step 11 Success!")

                finally:
                    receiver_task.cancel()
        finally:
            self.cleanup(server_process, chrome_process)

        self.assertFalse(errors, f"Browser exceptions occurred: {errors}")

    def cleanup(self, server_process, chrome_process):
        try:
            os.killpg(os.getpgid(server_process.pid), signal.SIGTERM)
            server_process.wait(timeout=2)
        except Exception:
            pass
        try:
            os.killpg(os.getpgid(chrome_process.pid), signal.SIGTERM)
            chrome_process.wait(timeout=2)
        except Exception:
            pass

        # Close streams to prevent resource leaks/warnings
        if server_process.stdout:
            try:
                server_process.stdout.close()
            except Exception:
                pass
        if server_process.stderr:
            try:
                server_process.stderr.close()
            except Exception:
                pass

        print("Process cleanups finished.")


if __name__ == "__main__":
    unittest.main()
