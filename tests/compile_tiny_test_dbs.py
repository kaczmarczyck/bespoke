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

import csv
import json
from pathlib import Path
import tempfile
import package_db


def compile_db(db_path: Path, target: str, native: str, data: dict):
    print(f"Creating tiny test DB at {db_path} via package_db...")

    # Load real audio bytes if available
    ogg_path = Path(
        "cards/german_english/000038335182748ab8fb04473d2de1c5975cfdb435f0cd07dc5f11ccfa0bb498.ogg"
    )
    audio_bytes = b""
    if ogg_path.exists():
        with open(ogg_path, "rb") as f:
            audio_bytes = f.read()

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        cards_dir = tmp_path / "cards"
        languages_dir = tmp_path / "languages"

        cards_dir.mkdir()
        languages_dir.mkdir()

        target_lang_dir = languages_dir / target
        target_lang_dir.mkdir()

        # 1. Write index JSON file
        index_file = cards_dir / f"index_{target}_{native}.json"
        index_data = {}
        for unit_id, card_id in data["unit_cards"].items():
            if unit_id not in index_data:
                index_data[unit_id] = []
            index_data[unit_id].append(card_id)

        with open(index_file, "w", encoding="utf-8") as f:
            json.dump(index_data, f)

        # 2. Write translations CSV file
        translations_file = cards_dir / f"translations_{target}_{native}.csv"
        with open(translations_file, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["unit_id", "translation"])
            writer.writeheader()
            for unit_id, trans in data["translations"].items():
                writer.writerow({"unit_id": unit_id, "translation": trans})

        # 3. Write vocabulary CSV file
        vocab_file = target_lang_dir / "vocabulary.csv"
        with open(vocab_file, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(
                f, fieldnames=["id", "name", "definition", "difficulty"]
            )
            writer.writeheader()
            for item in data["vocabulary"]:
                writer.writerow(
                    {
                        "id": item["id"],
                        "name": item["name"],
                        "definition": item["definition"],
                        "difficulty": item["difficulty"],
                    }
                )

        # 4. Write card JSON files in folder
        pair_dir = cards_dir / f"{target}_{native}"
        pair_dir.mkdir()

        for card in data["cards"]:
            card_id = card["id"]
            unit_tags = card["unit_tags"]
            if isinstance(unit_tags, str):
                unit_tags = json.loads(unit_tags)
            notes = card["notes"]
            if isinstance(notes, str):
                notes = json.loads(notes)

            audio_filename = f"{card_id}.ogg"
            slow_audio_filename = f"{card_id}_slow.ogg"

            with open(pair_dir / audio_filename, "wb") as f:
                f.write(audio_bytes)
            with open(pair_dir / slow_audio_filename, "wb") as f:
                f.write(audio_bytes)

            card_json = {
                "id": card_id,
                "sentence": card["sentence"],
                "native_sentence": card["native_sentence"],
                "phonetic": card.get("phonetic"),
                "unit_tags": unit_tags,
                "notes": notes,
                "audio_filename": str(pair_dir / audio_filename),
                "slow_audio_filename": str(pair_dir / slow_audio_filename),
                "native_audio_filename": str(pair_dir / audio_filename),
            }

            with open(pair_dir / f"{card_id}.json", "w", encoding="utf-8") as f:
                json.dump(card_json, f)

        # 5. package the deck using package_db.py logic
        if db_path.exists():
            try:
                db_path.unlink()
            except Exception:
                pass

        package_db.package_language_pair(
            target,
            native,
            db_path,
            cards_dir=cards_dir,
            languages_dir=languages_dir,
        )


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
