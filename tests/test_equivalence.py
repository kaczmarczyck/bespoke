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

"""Equivalence verification tests comparing Python and JavaScript schedulers."""

import json
import random
import subprocess
import unittest
from datetime import datetime
from pathlib import Path

from bespoke import Deck, Difficulty, Mode
from bespoke.urgency import Rating
from tests.fakes import fake_language, FakeCardIndex


class TestEquivalence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Retrieve target node script path
        cls.node_script = Path(__file__).parent / "run_equivalence.js"
        cls.target_lang = fake_language()
        cls.native_lang = fake_language()

        # Build index mapping
        cls.card_index = FakeCardIndex(cls.target_lang, cls.native_lang)

    def _serialize_deck_state(self, deck, operation, current_time, extra_params=None):
        # 1. Format vocabulary
        vocabulary_data = []
        for unit in self.target_lang.units():
            vocabulary_data.append(
                {"id": unit.id(), "difficulty": str(unit.difficulty())}
            )

        # 2. Format card index
        card_index_data = {}
        for unit in self.target_lang.units():
            cards = self.card_index.cards(unit)
            if cards:
                card_index_data[unit.id()] = [c.id for c in cards]

        # 3. Format cards map
        cards_data = {}
        for unit in self.target_lang.units():
            for card in self.card_index.cards(unit):
                cards_data[card.id] = {
                    "id": card.id,
                    "sentence": card.sentence,
                    "native_sentence": card.native_sentence,
                    "unit_tags": [
                        {"occurance": tag.occurance, "unit_id": tag.unit_id}
                        for tag in card.unit_tags
                    ],
                }

        # 4. Format ratings history
        ratings_data = {}
        for unit_id, state in deck._rating_states.items():
            ratings_data[unit_id] = [
                {"mode": str(r.mode), "time": r.time, "score": r.score}
                for r in state.ratings()
            ]

        # 5. Format card uses
        card_uses_data = {}
        for card_id, uses in deck._card_id_uses.items():
            card_uses_data[card_id] = [
                {"time": u.time, "is_reported": u.is_reported} for u in uses
            ]

        state = {
            "operation": operation,
            "target_language": self.target_lang.code_name,
            "native_language": self.native_lang.code_name,
            "vocabulary": vocabulary_data,
            "card_index": card_index_data,
            "cards": cards_data,
            "ratings": ratings_data,
            "card_id_uses": card_uses_data,
            "difficulty": str(deck._difficulty),
            "modes": [str(m) for m in deck._modes],
            "assume_known": str(deck._assume_known) if deck._assume_known else None,
            "current_time": current_time,
            "extra_params": extra_params or {},
        }
        return state

    def _execute_js_runner(self, payload):
        cmd = ["node", str(self.node_script)]
        result = subprocess.run(
            cmd, input=json.dumps(payload), text=True, capture_output=True
        )
        if result.returncode != 0:
            self.fail(f"Node.js equivalence runner failed: {result.stderr}")
        return json.loads(result.stdout)

    def test_equivalence_rating_state(self):
        # We will test the RatingState class methods directly by generating random rating streams
        current_time = datetime.now().timestamp()

        for _ in range(50):
            history = []
            start_time = current_time - (30 * 24 * 60 * 60)
            for step in range(random.randint(0, 10)):
                rating_time = start_time + (step * 2 * 24 * 60 * 60)
                score = random.choice([0, 1, 2, 3])
                mode = random.choice(list(Mode))
                history.append(Rating(mode=mode, time=rating_time, score=score))

            # Construct Python RatingState
            from bespoke.urgency import RatingState as PyRatingState

            py_state = PyRatingState(history)

            # Choose a target mode
            test_mode = random.choice(list(Mode))

            # Call JS execution
            ratings_payload = [
                {"mode": str(r.mode), "time": r.time, "score": r.score} for r in history
            ]
            extra_params = {
                "ratings": ratings_payload,
                "mode": str(test_mode),
                "modes": [str(m) for m in list(Mode)],
            }

            # We serialize a minimal deck state just to pass to the runner
            deck = Deck(self.target_lang, self.native_lang, self.card_index)
            payload = self._serialize_deck_state(
                deck, "rating_state", current_time, extra_params=extra_params
            )
            js_data = self._execute_js_runner(payload)
            js_state = js_data["result"]

            # Compare all properties
            self.assertAlmostEqual(
                py_state.urgency(test_mode, current_time),
                js_state["urgency"],
                places=5,
                msg=f"urgency mismatch for history: {history} and mode {test_mode}",
            )
            self.assertEqual(
                py_state.is_touched(),
                js_state["is_touched"],
                f"is_touched mismatch for history: {history}",
            )
            self.assertEqual(
                py_state.is_introduced(test_mode),
                js_state["is_introduced"],
                f"is_introduced mismatch for history: {history} and mode {test_mode}",
            )
            self.assertEqual(
                py_state.is_waiting(list(Mode), current_time),
                js_state["is_waiting"],
                f"is_waiting mismatch for history: {history}",
            )
            self.assertEqual(
                py_state.is_known(test_mode),
                js_state["is_known"],
                f"is_known mismatch for history: {history} and mode {test_mode}",
            )
            self.assertEqual(
                py_state.is_mature(test_mode),
                js_state["is_mature"],
                f"is_mature mismatch for history: {history} and mode {test_mode}",
            )

    def test_equivalence_choose_task(self):
        # We will generate a Deck with fuzzed rating states and run chooseTask
        for test_idx in range(20):
            deck = Deck(self.target_lang, self.native_lang, self.card_index)
            current_time = datetime.now().timestamp()

            deck.set_difficulty(random.choice(list(Difficulty)))
            deck.set_modes(random.sample(list(Mode), random.randint(1, 4)))
            if random.choice([True, False]):
                deck.set_assume_known(random.choice(list(Difficulty)))

            # Randomize history
            from bespoke.urgency import RatingState as PyRatingState

            for unit in self.target_lang.units():
                if random.choice([True, False, False]):
                    continue
                history = []
                for step in range(random.randint(1, 5)):
                    rating_time = current_time - random.randint(1, 20) * 24 * 60 * 60
                    history.append(
                        Rating(
                            mode=random.choice(deck._modes),
                            time=rating_time,
                            score=random.choice([0, 1, 2, 3]),
                        )
                    )
                history.sort(key=lambda r: r.time)
                deck._rating_states[unit.id()] = PyRatingState(history)
            deck.set_modes(deck._modes)

            # Python choose_task
            py_mode, py_unit_id = deck._choose_task(current_time)

            # JS choose_task
            payload = self._serialize_deck_state(deck, "choose_task", current_time)
            js_data = self._execute_js_runner(payload)
            js_result = js_data["result"]

            self.assertEqual(
                str(py_mode),
                js_result["mode"],
                f"Choose task mode mismatch on run {test_idx}",
            )
            self.assertEqual(
                py_unit_id,
                js_result["unitId"],
                f"Choose task unit ID mismatch on run {test_idx}",
            )

    def test_equivalence_draw_selections(self):
        # Run 20 fuzzed iterations of card drawing
        for test_idx in range(20):
            deck = Deck(self.target_lang, self.native_lang, self.card_index)
            current_time = datetime.now().timestamp()

            # Randomize deck params
            deck.set_difficulty(random.choice(list(Difficulty)))
            deck.set_modes(random.sample(list(Mode), random.randint(1, 4)))
            if random.choice([True, False]):
                deck.set_assume_known(random.choice(list(Difficulty)))

            # Randomize history
            from bespoke.urgency import RatingState as PyRatingState

            for unit in self.target_lang.units():
                if random.choice([True, False, False]):
                    continue
                history = []
                for step in range(random.randint(1, 5)):
                    rating_time = current_time - random.randint(1, 20) * 24 * 60 * 60
                    history.append(
                        Rating(
                            mode=random.choice(deck._modes),
                            time=rating_time,
                            score=random.choice([0, 1, 2, 3]),
                        )
                    )
                history.sort(key=lambda r: r.time)
                deck._rating_states[unit.id()] = PyRatingState(history)
            deck.set_modes(deck._modes)

            # Python draw
            py_mode, py_card = deck.draw(current_time)

            # JS draw
            payload = self._serialize_deck_state(deck, "draw", current_time)
            js_data = self._execute_js_runner(payload)
            js_result = js_data["result"]

            self.assertEqual(
                str(py_mode), js_result["mode"], f"Draw mode mismatch on run {test_idx}"
            )
            self.assertEqual(
                py_card.id,
                js_result["card_id"],
                f"Draw card ID mismatch on run {test_idx}",
            )

    def test_equivalence_lifecycle_flow(self):
        # Tests full cycle: draw -> rate -> log usage -> stats
        deck = Deck(self.target_lang, self.native_lang, self.card_index)
        current_time = datetime.now().timestamp()

        # Populate baseline touch ratings
        from bespoke.urgency import RatingState as PyRatingState

        for unit in self.target_lang.units():
            if random.choice([True, False]):
                deck._rating_states[unit.id()] = PyRatingState(
                    [Rating(mode=Mode.LISTEN, time=current_time - 100000, score=3)]
                )
        deck.set_modes(deck._modes)

        # Draw next card in Python
        py_mode, py_card = deck.draw(current_time)

        # Create rating updates to submit
        rating_updates = {}
        for unit_id in py_card.unit_ids():
            rating_updates[unit_id] = random.choice([1, 3])

        # Run updates in Python
        for unit_id, score in rating_updates.items():
            unit = deck._target_language.get_by_id(unit_id)
            if unit:
                deck.rate(unit, py_mode, score, current_time)

        deck.log_usage(py_card.id, is_reported=False, current_time=current_time)
        py_stats = deck.stats(current_time)

        # Let's recreate a clean baseline deck
        baseline_deck = Deck(self.target_lang, self.native_lang, self.card_index)
        for unit_id, state in deck._rating_states.items():
            # Exclude the new updates we just added in Python
            clean_history = [r for r in state.ratings() if r.time < current_time]
            baseline_deck._rating_states[unit_id] = PyRatingState(clean_history)
        baseline_deck.set_modes(baseline_deck._modes)

        extra_params = {"rating_updates": rating_updates, "is_reported": False}
        payload = self._serialize_deck_state(
            baseline_deck, "lifecycle", current_time, extra_params=extra_params
        )

        js_data = self._execute_js_runner(payload)
        js_result = js_data["result"]

        # Assert results match exactly
        self.assertEqual(str(py_mode), js_result["draw"]["mode"])
        self.assertEqual(py_card.id, js_result["draw"]["card_id"])

        # Assert stats equality
        self.assertEqual(py_stats["waiting"], js_result["stats"]["waiting"])
        self.assertEqual(py_stats["known"], js_result["stats"]["known"])
        self.assertEqual(py_stats["mature"], js_result["stats"]["mature"])

        # Assert ratings histories match
        for unit_id, py_state in deck._rating_states.items():
            js_history = js_result["ratings"].get(unit_id, [])
            py_history = py_state.ratings()
            self.assertEqual(
                len(py_history),
                len(js_history),
                f"History length mismatch for {unit_id}",
            )
            for py_r, js_r in zip(py_history, js_history):
                self.assertEqual(str(py_r.mode), js_r["mode"])
                self.assertAlmostEqual(py_r.time, js_r["time"], places=3)
                self.assertEqual(py_r.score, js_r["score"])

    def test_equivalence_split_into_parts(self):
        # 1. Gather all cards from our test set
        test_cards = []
        for unit in self.target_lang.units():
            cards = self.card_index.cards(unit)
            if cards:
                test_cards.extend(cards)

        # 2. Add manually crafted edge-case cards to verify boundary correctness
        from bespoke.card import Card
        from bespoke.unit import UnitTag

        edge_cases = [
            # No tags at all
            Card(
                id="edge_1",
                sentence="Hello world this is a test",
                native_sentence="Native translation",
                audio_filename="",
                slow_audio_filename="",
                native_audio_filename="",
                phonetic=None,
                unit_tags=[],
                notes=[],
            ),
            # Single tag covering the entire sentence
            Card(
                id="edge_2",
                sentence="Hello",
                native_sentence="Native",
                audio_filename="",
                slow_audio_filename="",
                native_audio_filename="",
                phonetic=None,
                unit_tags=[UnitTag(occurance="Hello", unit_id="hello_unit")],
                notes=[],
            ),
            # Tags at boundaries and in middle
            Card(
                id="edge_3",
                sentence="Hello beautiful world of coding",
                native_sentence="Native translation",
                audio_filename="",
                slow_audio_filename="",
                native_audio_filename="",
                phonetic=None,
                unit_tags=[
                    UnitTag(occurance="Hello", unit_id="hello"),
                    UnitTag(occurance="world", unit_id="world"),
                    UnitTag(occurance="coding", unit_id="coding"),
                ],
                notes=[],
            ),
        ]
        test_cards.extend(edge_cases)

        deck = Deck(self.target_lang, self.native_lang, self.card_index)
        current_time = datetime.now().timestamp()

        for card in test_cards:
            # Python split
            py_parts = card.split_into_parts()

            # JS split payload
            card_payload = {
                "id": card.id,
                "sentence": card.sentence,
                "native_sentence": card.native_sentence,
                "unit_tags": [
                    {"occurance": tag.occurance, "unit_id": tag.unit_id}
                    for tag in card.unit_tags
                ],
            }

            payload = self._serialize_deck_state(
                deck,
                "split_into_parts",
                current_time,
                extra_params={"card": card_payload},
            )
            js_data = self._execute_js_runner(payload)
            js_parts = js_data["result"]

            self.assertEqual(
                len(py_parts),
                len(js_parts),
                f"Parts count mismatch for sentence: '{card.sentence}'",
            )

            for py_part, js_part in zip(py_parts, js_parts):
                self.assertEqual(
                    py_part.occurance,
                    js_part["occurance"],
                    f"Occurance mismatch in sentence: '{card.sentence}'",
                )
                self.assertEqual(
                    py_part.unit_id,
                    js_part["unit_id"],
                    f"Unit ID mismatch in sentence: '{card.sentence}'",
                )


if __name__ == "__main__":
    unittest.main()
