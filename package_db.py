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

"""Script to compile flat JSON cards, OGG audio files, and vocabulary into a SQLite database."""

import argparse
import csv
import json
import sqlite3
from pathlib import Path

from bespoke import languages

CARDS_DIR = Path("cards")
LANGUAGES_DIR = Path("languages")


def package_language_pair(target: str, native: str, output_db_path: Path):
    print(f"Packaging {target}_{native} into {output_db_path}...")

    # Validate that files exist before starting SQLite
    index_file = CARDS_DIR / f"index_{target}_{native}.json"
    card_directory = CARDS_DIR / f"{target}_{native}"

    if not index_file.exists():
        available_dirs = [p.name for p in CARDS_DIR.glob("*_*") if p.is_dir()]
        raise FileNotFoundError(
            f"Card index file not found at: {index_file}.\n"
            f"Please verify that target/native parameters match folders in cards/.\n"
            f"Available card datasets on disk: {available_dirs}"
        )

    if not card_directory.exists():
        raise FileNotFoundError(f"Card files directory not found at: {card_directory}")

    # 1. Initialize SQLite Database
    conn = sqlite3.connect(output_db_path)
    cursor = conn.cursor()

    # Enable Write-Ahead Log & Synchronous OFF for faster packing
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA synchronous=OFF;")

    # Create tables
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cards (
            id TEXT PRIMARY KEY,
            sentence TEXT NOT NULL,
            native_sentence TEXT NOT NULL,
            phonetic TEXT,
            unit_tags TEXT, -- JSON array of tags
            notes TEXT,     -- JSON array of notes
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

    conn.commit()

    # 2. Insert Translations
    translation_file = CARDS_DIR / f"translations_{target}_{native}.csv"
    if translation_file.exists():
        print("Processing translations CSV...")
        with open(translation_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            translations_to_insert = []
            for row in reader:
                translations_to_insert.append((row["unit_id"], row["translation"]))

            cursor.executemany(
                """
                INSERT OR REPLACE INTO translations (unit_id, translation)
                VALUES (?, ?);
            """,
                translations_to_insert,
            )
        conn.commit()
        print(f"Inserted {len(translations_to_insert)} translations.")

    # 3. Insert Card Index (unit_cards)
    print("Processing index JSON...")
    with open(index_file, "r", encoding="utf-8") as f:
        index_data = json.load(f)

    index_to_insert = []
    for unit_id, card_ids in index_data.items():
        for card_id in card_ids:
            index_to_insert.append((unit_id, card_id))

    cursor.executemany(
        """
        INSERT OR REPLACE INTO unit_cards (unit_id, card_id)
        VALUES (?, ?);
    """,
        index_to_insert,
    )
    conn.commit()
    print(f"Inserted {len(index_to_insert)} index mappings.")

    # 4. Insert Vocabulary (reconciling vocabulary.csv with index keys)
    vocab_file = LANGUAGES_DIR / target / "vocabulary.csv"
    if vocab_file.exists():
        print("Processing vocabulary list...")
        # Load CSV into memory for lookup by name
        csv_vocab = {}
        with open(vocab_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                csv_vocab[row["name"]] = {
                    "definition": row.get("definition", ""),
                    "difficulty": row.get("difficulty", "A1"),
                }

        # Populate vocabulary table using unit IDs from the index
        vocab_to_insert = []
        for unit_id in index_data.keys():
            # If the unit ID is f"{word} - {definition}"
            if " - " in unit_id:
                parts = unit_id.split(" - ", 1)
                word = parts[0]
                definition = parts[1]
            else:
                word = unit_id
                definition = ""

            # Look up difficulty from csv_vocab
            difficulty = "A1"
            if word in csv_vocab:
                difficulty = csv_vocab[word]["difficulty"]
                if not definition:
                    definition = csv_vocab[word]["definition"]

            vocab_to_insert.append((unit_id, word, definition, difficulty))

        cursor.executemany(
            """
            INSERT OR REPLACE INTO vocabulary (id, name, definition, difficulty)
            VALUES (?, ?, ?, ?);
        """,
            vocab_to_insert,
        )
        conn.commit()
        print(f"Inserted {len(vocab_to_insert)} vocabulary units.")

    # 5. Insert Cards and Audio BLOBs
    card_directory = CARDS_DIR / f"{target}_{native}"
    if card_directory.exists():
        json_files = list(card_directory.glob("*.json"))
        print(f"Processing {len(json_files)} card files...")

        cards_batch = []
        count = 0

        for json_file in json_files:
            card_id = json_file.stem
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    card_data = json.load(f)

                sentence = card_data.get("sentence", "")
                native_sentence = card_data.get("native_sentence", "")
                phonetic = card_data.get("phonetic")
                unit_tags_str = json.dumps(card_data.get("unit_tags", []))
                notes_str = json.dumps(card_data.get("notes", []))

                def read_audio(filename: str) -> bytes | None:
                    if not filename:
                        return None
                    p = Path(filename)
                    if not p.exists():
                        p = (
                            CARDS_DIR / p.relative_to("cards")
                            if p.parts[0] == "cards"
                            else card_directory / p.name
                        )

                    if p.exists():
                        with open(p, "rb") as af:
                            return af.read()
                    return None

                audio = read_audio(card_data.get("audio_filename", ""))
                slow_audio = read_audio(card_data.get("slow_audio_filename", ""))
                native_audio = read_audio(card_data.get("native_audio_filename", ""))

                cards_batch.append(
                    (
                        card_id,
                        sentence,
                        native_sentence,
                        phonetic,
                        unit_tags_str,
                        notes_str,
                        audio,
                        slow_audio,
                        native_audio,
                    )
                )

                if len(cards_batch) >= 1000:
                    cursor.executemany(
                        """
                        INSERT OR REPLACE INTO cards (
                            id, sentence, native_sentence, phonetic, unit_tags, notes, audio, slow_audio, native_audio
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                        cards_batch,
                    )
                    conn.commit()
                    count += len(cards_batch)
                    print(f"Inserted {count} cards...")
                    cards_batch = []

            except Exception as e:
                print(f"Error processing card {card_id}: {e}")

        if cards_batch:
            cursor.executemany(
                """
                INSERT OR REPLACE INTO cards (
                    id, sentence, native_sentence, phonetic, unit_tags, notes, audio, slow_audio, native_audio
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
                cards_batch,
            )
            conn.commit()
            count += len(cards_batch)
            print(f"Inserted total {count} cards.")

    # Revert WAL mode for browser compatibility
    print("Reverting journal mode to DELETE...")
    cursor.execute("PRAGMA journal_mode=DELETE;")
    conn.commit()

    # Optimize database and vacuum
    print("Optimizing database...")
    cursor.execute("PRAGMA optimize;")
    conn.commit()
    conn.close()
    print("Database packaging complete!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Package language cards into a SQLite database."
    )

    target_choices = {}
    for language in languages.LANGUAGES.values():
        if language.has_data():
            target_choices[language.writing_system] = language
    native_choices = {
        lang.writing_system: lang for lang in languages.LANGUAGES.values()
    }

    parser.add_argument(
        "--target",
        type=str,
        choices=list(target_choices),
        required=True,
        help="Target language (e.g. 'German', 'Traditional Chinese')",
    )
    parser.add_argument(
        "--native",
        type=str,
        choices=list(native_choices),
        required=True,
        help="Native language (e.g. 'English', 'German')",
    )
    parser.add_argument(
        "--output", type=str, required=True, help="Output SQLite database file path"
    )
    args = parser.parse_args()

    target_lang = target_choices[args.target]
    native_lang = native_choices[args.native]

    package_language_pair(
        target_lang.code_name, native_lang.code_name, Path(args.output)
    )
