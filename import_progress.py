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

"""Helper script to import user progress from deck JSON into a compiled SQLite database."""

import json
import sqlite3
import sys
from pathlib import Path


def main():
    if len(sys.argv) < 3:
        print("Usage: uv run import_progress.py <deck_json_path> <db_path>")
        sys.exit(1)

    json_path = Path(sys.argv[1])
    db_path = Path(sys.argv[2])

    if not json_path.exists():
        print(f"Error: JSON file not found at {json_path}")
        sys.exit(1)

    if not db_path.exists():
        print(f"Error: SQLite DB file not found at {db_path}")
        sys.exit(1)

    print(f"Importing progress from {json_path} into {db_path}...")

    with open(json_path, "r", encoding="utf-8") as f:
        deck_data = json.load(f)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Create tables if not exist
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ratings (
            unit_id TEXT NOT NULL,
            mode TEXT NOT NULL,
            time REAL NOT NULL,
            score INTEGER NOT NULL
        );
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS card_usage (
            card_id TEXT NOT NULL,
            time REAL NOT NULL,
            is_reported INTEGER NOT NULL
        );
    """)
    conn.commit()

    # Clear existing progress inside database to avoid duplicate ratings
    cursor.execute("DELETE FROM ratings;")
    cursor.execute("DELETE FROM card_usage;")
    conn.commit()

    # 1. Insert Ratings
    ratings_to_insert = []
    ratings_dict = deck_data.get("ratings", {})
    for unit_id, history in ratings_dict.items():
        for r in history:
            ratings_to_insert.append((unit_id, r["mode"], r["time"], r["score"]))

    if ratings_to_insert:
        cursor.executemany(
            """
            INSERT INTO ratings (unit_id, mode, time, score)
            VALUES (?, ?, ?, ?);
        """,
            ratings_to_insert,
        )
        print(f"Imported {len(ratings_to_insert)} rating entries.")

    # 2. Insert Card Uses
    uses_to_insert = []
    uses_dict = deck_data.get("card_id_uses", {})
    for card_id, history in uses_dict.items():
        for u in history:
            uses_to_insert.append((card_id, u["time"], 1 if u["is_reported"] else 0))

    if uses_to_insert:
        cursor.executemany(
            """
            INSERT INTO card_usage (card_id, time, is_reported)
            VALUES (?, ?, ?);
        """,
            uses_to_insert,
        )
        print(f"Imported {len(uses_to_insert)} card usage entries.")

    conn.commit()
    conn.close()
    print("Import complete!")


if __name__ == "__main__":
    main()
