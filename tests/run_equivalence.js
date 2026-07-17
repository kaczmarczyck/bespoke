// Copyright 2026 Google LLC
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     https://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

/**
 * Node.js script to run equivalence test executions for Deck / Urgency.
 */

const fs = require('fs');
const path = require('path');

// Resolve local module paths
const { Rating, RatingState } = require('../web/urgency');
const { Deck, splitIntoParts } = require('../web/deck');

function readStdin() {
    return new Promise((resolve, reject) => {
        let data = '';
        process.stdin.setEncoding('utf8');
        process.stdin.on('data', chunk => {
            data += chunk;
        });
        process.stdin.on('end', () => {
            resolve(data);
        });
        process.stdin.on('error', err => {
            reject(err);
        });
    });
}

async function main() {
    try {
        const inputStr = await readStdin();
        if (!inputStr) {
            console.error("No input received on stdin.");
            process.exit(1);
        }

        const input = JSON.parse(inputStr);
        
        // 1. Initialize JS Deck
        const deck = new Deck({
            targetLanguage: input.target_language,
            nativeLanguage: input.native_language,
            vocabulary: input.vocabulary,
            cardIndex: input.card_index,
            cards: input.cards
        });

        deck.setDifficulty(input.difficulty);
        deck.setModes(input.modes);
        deck.setAssumeKnown(input.assume_known);

        // Deserialize ratings history maps into RatingState objects
        if (input.ratings) {
            const rawRatings = {};
            for (const [unitId, ratingsArray] of Object.entries(input.ratings)) {
                rawRatings[unitId] = ratingsArray.map(r => new Rating(r.mode, r.time, r.score));
            }
            deck.ratings = rawRatings;
        }
        
        // Deserialize card usage maps
        if (input.card_id_uses) {
            deck.cardIdUses = input.card_id_uses;
        }

        const currentTime = input.current_time;
        const response = {};

        // 2. Perform requested operation
        if (input.operation === "draw") {
            const { mode, card } = deck.draw(currentTime);
            response.result = {
                mode: mode,
                card_id: card ? card.id : null
            };
        } 
        
        else if (input.operation === "rating_state") {
            const ratingsArray = (input.extra_params.ratings || []).map(r => new Rating(r.mode, r.time, r.score));
            const state = new RatingState(ratingsArray);
            const mode = input.extra_params.mode;
            const modes = input.extra_params.modes || [mode];
            
            response.result = {
                urgency: state.urgency(mode, currentTime),
                is_touched: state.is_touched(),
                is_introduced: state.is_introduced(mode),
                is_waiting: state.is_waiting(modes, currentTime),
                is_known: state.is_known(mode),
                is_mature: state.is_mature(mode)
            };
        }
        
        else if (input.operation === "choose_task") {
            const { mode, unitId } = deck.chooseTask(currentTime);
            response.result = { mode, unitId };
        }
        
        else if (input.operation === "stats") {
            const stats = deck.stats(currentTime);
            response.result = stats;
        }
        
        else if (input.operation === "split_into_parts") {
            const card = input.extra_params.card;
            response.result = splitIntoParts(card);
        }
        
        else if (input.operation === "lifecycle") {
            // Lifecycle: draw -> rate -> logUsage -> stats
            const drawResult = deck.draw(currentTime);
            const card = drawResult.card;
            
            // Replicate rating updates
            const ratingUpdates = input.extra_params.rating_updates || {};
            for (const [unitId, score] of Object.entries(ratingUpdates)) {
                deck.rate(unitId, drawResult.mode, score, currentTime);
            }
            
            // Replicate usage logging
            deck.logUsage(card.id, input.extra_params.is_reported || false, currentTime);
            
            const stats = deck.stats(currentTime);

            // Serialize updated states back
            const serializedRatings = {};
            for (const [unitId, ratingsArray] of Object.entries(deck.ratings)) {
                serializedRatings[unitId] = ratingsArray.map(r => ({
                    mode: r.mode,
                    time: r.time,
                    score: r.score
                }));
            }

            response.result = {
                draw: {
                    mode: drawResult.mode,
                    card_id: card.id
                },
                ratings: serializedRatings,
                card_id_uses: deck.cardIdUses,
                stats: stats
            };
        }

        else {
            console.error(`Unknown operation: ${input.operation}`);
            process.exit(1);
        }

        // Output results to stdout
        console.log(JSON.stringify(response));

    } catch (e) {
        console.error("Error in equivalence runner:", e.stack);
        process.exit(1);
    }
}

main();
