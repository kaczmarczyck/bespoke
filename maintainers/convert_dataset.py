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

"""Tool to convert an existing SQLite dataset .db to a new native language."""

import argparse
import asyncio
import hashlib
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

from bespoke import database, languages, llm, translation, unit
from bespoke.card import CARDS_DIR, Card, encode_audio_to_ogg


async def convert_dataset(
    input_db_path: Path | str,
    to_native: languages.Language | str,
    output_db_path: Path | str | None = None,
    llm_client: llm.LlmClient | None = None,
    parallelism: int = 16,
) -> Path:
    """Converts a dataset SQLite .db to a new native language directly."""
    input_db_path = Path(input_db_path)
    if not input_db_path.is_file():
        raise FileNotFoundError(f"Input database not found: {input_db_path}")

    meta = database.load_metadata_from_db(input_db_path)
    target_code = meta.get("target_language")
    if not target_code:
        raise ValueError(f"Missing target_language in metadata for {input_db_path}")
    target_lang = database.resolve_language(target_code)
    new_native_lang = database.resolve_language(to_native)

    if output_db_path is None:
        output_db_path = database.get_dataset_db_path(
            input_db_path.parent, target_lang, new_native_lang
        )
    output_db_path = Path(output_db_path)
    output_db_path.parent.mkdir(parents=True, exist_ok=True)

    if llm_client is None:
        llm_client = llm.get_llm_client()

    cards = database.load_all_cards_from_db(input_db_path)
    vocabulary = database.load_vocabulary_from_db(input_db_path)

    conn = sqlite3.connect(output_db_path)
    try:
        with conn:
            conn.executescript(database.CREATE_TABLES_SQL)

            # Ensure vocabulary is present in output database
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM vocabulary")
            if cursor.fetchone()[0] == 0:
                vocab_rows = []
                for vocabulary_unit in vocabulary:
                    definition = (
                        vocabulary_unit.definition()
                        if isinstance(vocabulary_unit, unit.DictionaryUnit)
                        else ""
                    )
                    vocab_rows.append(
                        (
                            vocabulary_unit.id(),
                            vocabulary_unit.name(),
                            definition,
                            str(vocabulary_unit.difficulty()),
                        )
                    )
                cursor.executemany(
                    "INSERT OR REPLACE INTO vocabulary (id, name, definition, difficulty) VALUES (?, ?, ?, ?)",
                    vocab_rows,
                )

            # Copy target and slow audio blobs from input database if missing in output database
            for target_card in cards:
                for audio_ref in [
                    target_card.audio_filename,
                    target_card.slow_audio_filename,
                ]:
                    if not audio_ref:
                        continue
                    base_name = Path(audio_ref).name
                    cursor.execute(
                        "SELECT 1 FROM audio WHERE filename = ? OR filename = ?",
                        (audio_ref, base_name),
                    )
                    if cursor.fetchone() is None:
                        blob = database.get_audio_blob(input_db_path, audio_ref)
                        if blob is not None:
                            cursor.execute(
                                "INSERT OR REPLACE INTO audio (filename, data) VALUES (?, ?)",
                                (base_name, blob),
                            )

        # 1. Translate vocabulary units (resumable)
        existing_translations = database.load_translations_from_db(output_db_path)
        print(f"Translating {len(vocabulary)} vocabulary units...")
        new_translations = await translation.translate_units(
            units=vocabulary,
            target_language=target_lang,
            native_language=new_native_lang,
            llm_client=llm_client,
            existing_translations=existing_translations,
            parallelism=parallelism,
        )

        with conn:
            cursor = conn.cursor()
            cursor.executemany(
                "INSERT OR REPLACE INTO translations (unit_id, translation) VALUES (?, ?)",
                list(new_translations.items()),
            )

        # 2. Check already converted cards in output_db_path
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM cards")
        existing_card_ids = {row[0] for row in cursor.fetchall()}

        cards_to_process = [c for c in cards if c.id not in existing_card_ids]
        if existing_card_ids:
            print(
                f"Resuming card conversion: {len(existing_card_ids)}/{len(cards)} cards already converted, "
                f"{len(cards_to_process)} remaining."
            )
        else:
            print(f"Translating {len(cards)} cards and generating audio...")

        if cards_to_process:
            semaphore = asyncio.Semaphore(parallelism)

            @llm.standard_retry
            async def _convert_single_card(
                target_card: Card,
            ) -> tuple[Card, str, bytes]:
                raw_translated = await llm_client.translate(
                    target_card.sentence, new_native_lang
                )
                new_native_sentence = raw_translated.strip().strip("\"'“”«»‘`")
                if not new_native_sentence:
                    raise ValueError("Missing content")
                audio_array = await llm_client.speak(new_native_sentence, slowly=False)
                ogg_bytes = await encode_audio_to_ogg(audio_array)

                native_hash = hashlib.sha256(
                    new_native_sentence.encode("utf-8")
                ).hexdigest()
                native_filename = f"cards/{target_lang.code_name}_{new_native_lang.code_name}/{native_hash}.ogg"
                base_native_filename = f"{native_hash}.ogg"

                new_card = Card(
                    id=target_card.id,
                    sentence=target_card.sentence,
                    native_sentence=new_native_sentence,
                    phonetic=target_card.phonetic,
                    audio_filename=target_card.audio_filename,
                    slow_audio_filename=target_card.slow_audio_filename,
                    native_audio_filename=native_filename,
                    unit_tags=target_card.unit_tags,
                    notes=target_card.notes,
                )
                return new_card, base_native_filename, ogg_bytes

            async def process_card(
                target_card: Card,
            ) -> tuple[Card, str, bytes] | None:
                async with semaphore:
                    try:
                        return await _convert_single_card(target_card)
                    except Exception as exception:  # noqa: BLE001
                        print(
                            f"Failed to convert card {target_card.id} ('{target_card.sentence}'): {exception}"
                        )
                        return None

            tasks = [process_card(c) for c in cards_to_process]
            pending_cards_batch: list[tuple[Card, str, bytes]] = []
            converted_so_far = len(existing_card_ids)

            def flush_batch(batch: list[tuple[Card, str, bytes]]) -> None:
                if not batch:
                    return
                with conn:
                    cur = conn.cursor()
                    cards_rows = [
                        (
                            c.id,
                            c.sentence,
                            c.native_sentence,
                            c.phonetic,
                            c.audio_filename,
                            c.slow_audio_filename,
                            c.native_audio_filename,
                            json.dumps(
                                [t.model_dump() for t in c.unit_tags],
                                ensure_ascii=False,
                            ),
                            json.dumps(c.notes, ensure_ascii=False),
                            c.model_dump_json(),
                        )
                        for c, _, _ in batch
                    ]
                    cur.executemany(
                        """
                        INSERT OR REPLACE INTO cards (
                            id, sentence, native_sentence, phonetic,
                            audio_filename, slow_audio_filename, native_audio_filename,
                            unit_tags_json, notes_json, json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        cards_rows,
                    )
                    audio_rows = [(base_name, blob) for _, base_name, blob in batch]
                    cur.executemany(
                        "INSERT OR REPLACE INTO audio (filename, data) VALUES (?, ?)",
                        audio_rows,
                    )

            for future in asyncio.as_completed(tasks):
                result = await future
                if result is not None:
                    pending_cards_batch.append(result)
                    converted_so_far += 1
                    if len(pending_cards_batch) >= 100:
                        flush_batch(pending_cards_batch)
                        pending_cards_batch.clear()

                if converted_so_far % 1000 == 0 or converted_so_far == len(cards):
                    print(f"Converted {converted_so_far}/{len(cards)} cards...")

            if pending_cards_batch:
                flush_batch(pending_cards_batch)
                pending_cards_batch.clear()

        # 3. Rebuild index for all cards actually present in database
        all_saved_cards = database.load_all_cards_from_db(output_db_path)
        with conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM card_index")
            index_rows = []
            for c in all_saved_cards:
                for unit_id in c.unit_ids():
                    index_rows.append((unit_id, c.id))
            cur.executemany(
                "INSERT OR REPLACE INTO card_index (unit_id, card_id) VALUES (?, ?)",
                index_rows,
            )

            # 4. Finalize metadata
            cur.execute("SELECT COUNT(*) FROM audio")
            audio_count = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM vocabulary")
            vocab_count = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM translations")
            trans_count = cur.fetchone()[0]

            now_iso = datetime.now(UTC).isoformat()
            metadata = {
                "target_language": target_lang.code_name,
                "native_language": new_native_lang.code_name,
                "target_language_name": target_lang.name,
                "native_language_name": new_native_lang.name,
                "created_at": now_iso,
                "version": "1.0",
                "card_count": str(len(all_saved_cards)),
                "audio_count": str(audio_count),
                "vocabulary_count": str(vocab_count),
                "translation_count": str(trans_count),
            }
            cur.executemany(
                "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
                list(metadata.items()),
            )

        # 5. Vacuum database
        conn.execute("VACUUM")
    finally:
        conn.close()

    if not database.verify_dataset_db(output_db_path):
        raise RuntimeError(
            f"Verification failed for converted database: {output_db_path}"
        )

    return output_db_path


async def main_async() -> None:
    target_choices = {}
    for language in languages.LANGUAGES.values():
        if language.has_data():
            target_choices[language.writing_system] = language
            target_choices[language.code_name] = language

    native_choices = {}
    for language in languages.LANGUAGES.values():
        native_choices[language.writing_system] = language
        native_choices[language.code_name] = language

    parser = argparse.ArgumentParser(
        description="Convert a dataset .db into a new native language."
    )
    parser.add_argument(
        "--target",
        type=str,
        required=True,
        choices=list(target_choices),
        help="The language of the dataset you are learning.",
    )
    parser.add_argument(
        "--from-native",
        type=str,
        required=True,
        choices=list(native_choices),
        help="The current native language of the source dataset.",
    )
    parser.add_argument(
        "--to-native",
        type=str,
        required=True,
        choices=list(native_choices),
        help="The new native language to translate into.",
    )
    parser.add_argument(
        "--parallelism",
        type=int,
        default=16,
        help="Parallelism limit for LLM calls (default: 16).",
    )
    args = parser.parse_args()

    target_lang = database.resolve_language(args.target)
    from_native_lang = database.resolve_language(args.from_native)
    to_native_lang = database.resolve_language(args.to_native)

    input_db_path = database.get_dataset_db_path(
        CARDS_DIR, target_lang, from_native_lang
    )

    if not input_db_path.exists():
        print(
            f"Error: Source dataset DB not found at '{input_db_path}'.",
            file=sys.stderr,
        )
        sys.exit(1)

    output_db_path = database.get_dataset_db_path(
        CARDS_DIR, target_lang, to_native_lang
    )

    llm_client = llm.get_llm_client()
    print(
        f"Converting dataset {input_db_path} ({target_lang.writing_system}) to native language: "
        f"{to_native_lang.writing_system} ({output_db_path})..."
    )
    result_path = await convert_dataset(
        input_db_path=input_db_path,
        to_native=to_native_lang,
        output_db_path=output_db_path,
        llm_client=llm_client,
        parallelism=args.parallelism,
    )
    size_mb = result_path.stat().st_size / (1024 * 1024)
    print(f"Successfully converted dataset: {result_path} ({size_mb:.2f} MB)")


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
