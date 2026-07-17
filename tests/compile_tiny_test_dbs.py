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

"""Compiles tiny mock German-English and Traditional Chinese-German SQLite databases for testing."""

import sqlite3
from pathlib import Path


def compile_db(db_path: Path, target: str, native: str, data: dict):
    print(f"Creating tiny test DB at {db_path}...")

    # Load real audio bytes if available
    ogg_path = Path(
        "cards/german_english/000038335182748ab8fb04473d2de1c5975cfdb435f0cd07dc5f11ccfa0bb498.ogg"
    )
    audio_bytes = None
    if ogg_path.exists():
        with open(ogg_path, "rb") as f:
            audio_bytes = f.read()
        print(f"Loaded {len(audio_bytes)} bytes of test audio.")
    else:
        print("Warning: test OGG file not found, audio BLOBs will be empty.")

    # Initialize SQLite
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Disable WAL mode and set to DELETE journal mode first
    cursor.execute("PRAGMA journal_mode=DELETE;")

    # Create tables
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cards (
            id TEXT PRIMARY KEY,
            sentence TEXT NOT NULL,
            native_sentence TEXT NOT NULL,
            phonetic TEXT,
            unit_tags TEXT,
            notes TEXT,
            audio BLOB,
            slow_audio BLOB,
            native_audio BLOB
        );
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS unit_cards (
            unit_id TEXT NOT NULL,
            card_id TEXT NOT NULL,
            PRIMARY KEY (unit_id, card_id)
        );
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS translations (
            unit_id TEXT PRIMARY KEY,
            translation TEXT NOT NULL
        );
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS vocabulary (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            definition TEXT,
            difficulty TEXT NOT NULL
        );
    """)

    # Clear existing data
    cursor.execute("DELETE FROM cards;")
    cursor.execute("DELETE FROM unit_cards;")
    cursor.execute("DELETE FROM translations;")
    cursor.execute("DELETE FROM vocabulary;")

    # Insert translations
    for unit_id, trans in data["translations"].items():
        cursor.execute(
            "INSERT OR REPLACE INTO translations VALUES (?, ?);", (unit_id, trans)
        )

    # Insert unit_cards
    for unit_id, card_id in data["unit_cards"].items():
        cursor.execute(
            "INSERT OR REPLACE INTO unit_cards VALUES (?, ?);", (unit_id, card_id)
        )

    # Insert vocabulary
    for item in data["vocabulary"]:
        cursor.execute(
            "INSERT OR REPLACE INTO vocabulary VALUES (?, ?, ?, ?);",
            (item["id"], item["name"], item["definition"], item["difficulty"]),
        )

    # Insert cards
    for card in data["cards"]:
        cursor.execute(
            """
            INSERT OR REPLACE INTO cards (id, sentence, native_sentence, phonetic, unit_tags, notes, audio, slow_audio, native_audio)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
            (
                card["id"],
                card["sentence"],
                card["native_sentence"],
                card["phonetic"],
                card["unit_tags"],
                card["notes"],
                audio_bytes,
                audio_bytes,
                audio_bytes,
            ),
        )

    conn.commit()

    # Shrink database file size to release deleted space
    print("Vacuuming database...")
    cursor.execute("VACUUM;")
    conn.commit()

    conn.close()
    print(f"Tiny DB {db_path.name} compiled successfully!")


def main():
    # 1. Compile German-English DB
    german_data = {
        "translations": {
            "wir": "we",
            "gehen": "to go",
            "ab": "from/off",
            "und": "and",
            "zu": "to/at",
        },
        "unit_cards": {
            "wir": "card1",
            "gehen": "card1",
            "ab": "card2",
            "und": "card2",
            "zu": "card2",
        },
        "vocabulary": [
            {"id": "wir", "name": "wir", "definition": "we", "difficulty": "A1"},
            {"id": "gehen", "name": "gehen", "definition": "to go", "difficulty": "A1"},
            {"id": "ab", "name": "ab", "definition": "from/off", "difficulty": "A1"},
            {"id": "und", "name": "und", "definition": "and", "difficulty": "A1"},
            {"id": "zu", "name": "zu", "definition": "to/at", "difficulty": "A1"},
        ],
        "cards": [
            {
                "id": "card1",
                "sentence": "Wir gehen.",
                "native_sentence": "We go.",
                "phonetic": "veer gay-en",
                "unit_tags": '[{"occurance": "Wir", "unit_id": "wir"}, {"occurance": "gehen", "unit_id": "gehen"}]',
                "notes": "[]",
            },
            {
                "id": "card2",
                "sentence": "Ab und zu.",
                "native_sentence": "Now and then.",
                "phonetic": "ap oont tsoo",
                "unit_tags": '[{"occurance": "Ab", "unit_id": "ab"}, {"occurance": "und", "unit_id": "und"}, {"occurance": "zu", "unit_id": "zu"}]',
                "notes": "[]",
            },
        ],
    }
    compile_db(Path("cards/german_english.db"), "German", "English", german_data)

    # 2. Compile Traditional Chinese-German DB
    chinese_data = {
        "translations": {
            "我們": "wir (we)",
            "走": "gehen (go)",
            "從": "ab (from)",
            "那時": "damals (then)",
            "起": "ab (since)",
        },
        "unit_cards": {
            "我們": "card1",
            "走": "card1",
            "從": "card2",
            "那時": "card2",
            "起": "card2",
        },
        "vocabulary": [
            {
                "id": "我們",
                "name": "我們",
                "definition": "wir (we)",
                "difficulty": "A1",
            },
            {"id": "走", "name": "走", "definition": "gehen (go)", "difficulty": "A1"},
            {"id": "從", "name": "從", "definition": "ab (from)", "difficulty": "A1"},
            {
                "id": "那時",
                "name": "那時",
                "definition": "damals (then)",
                "difficulty": "A1",
            },
            {"id": "起", "name": "起", "definition": "ab (since)", "difficulty": "A1"},
        ],
        "cards": [
            {
                "id": "card1",
                "sentence": "我們走。",
                "native_sentence": "Wir gehen.",
                "phonetic": "wǒmen zǒu",
                "unit_tags": '[{"occurance": "我們", "unit_id": "我們"}, {"occurance": "走", "unit_id": "走"}]',
                "notes": "[]",
            },
            {
                "id": "card2",
                "sentence": "從那時起。",
                "native_sentence": "Seitdem.",
                "phonetic": "cóng nàshí qǐ",
                "unit_tags": '[{"occurance": "從", "unit_id": "從"}, {"occurance": "那時", "unit_id": "那時"}, {"occurance": "起", "unit_id": "起"}]',
                "notes": "[]",
            },
        ],
    }
    compile_db(
        Path("cards/trad_chinese_german.db"),
        "Traditional Chinese",
        "German",
        chinese_data,
    )


if __name__ == "__main__":
    main()
