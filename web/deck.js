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
 * Port of bespoke/deck.py to JavaScript.
 */

// Import dependency (Node environment lookup)
const urgencyModule = typeof require !== 'undefined' ? require('./urgency') : window.BespokeUrgency;
const Rating = urgencyModule.Rating;
const RatingState = urgencyModule.RatingState;

// Map difficulty hierarchies for comparison
const DIFFICULTY_LEVELS = {
    "A1": 1, "A2": 2, "B1": 3, "B2": 4, "C1": 5, "C2": 6
};

function compareDifficulty(d1, d2) {
    const v1 = DIFFICULTY_LEVELS[d1] || 0;
    const v2 = DIFFICULTY_LEVELS[d2] || 0;
    return v1 - v2;
}

// Card scoring constants
const REPORT_PENALTY = 1000000.0;
const CARD_USAGE_FACTOR = 1000.0;
const CARD_USAGE_DECAY = 0.1;
const UNTOUCHED_PENALTY = 200.0;
const UNINTRODUCED_PENALTY = 100.0;
const URGENCY_BONUS = 10.0;
const DIFFICULTY_MATCH_BONUS = 0.1;
const DIFFICULTY_PENALTY = 0.1;

class Deck {
    constructor({
        targetLanguage,
        nativeLanguage,
        vocabulary, // Array of { id, difficulty }
        cardIndex,   // Map of { unit_id: [card_id1, card_id2] }
        cards        // Map of { card_id: CardObj }
    }) {
        this.targetLanguage = targetLanguage;
        this.nativeLanguage = nativeLanguage;
        this.vocabulary = vocabulary || [];
        this.cardIndex = cardIndex || {};
        this.cards = cards || {};
        
        // Deck progress state using RatingState instances
        this._ratingStates = {};
        this.cardIdUses = {};   // Map of { card_id: [CardUsage] }
        
        // Defaults matching deck.py
        this.difficulty = "A1";
        this.modes = ["listen", "speak", "read", "write"];
        this.assumeKnown = null;
        
        this._knownUnitModes = 0;
        this._matureUnitModes = 0;

        // Populate units with cards
        this._unitsWithCards = [];
        for (const unit of this.vocabulary) {
            const cardIds = this.cardIndex[unit.id] || [];
            if (cardIds.length > 0) {
                this._unitsWithCards.push(unit);
            }
        }
    }

    // Getter/setter for backward compatibility with app.js / equivalence tests
    get ratings() {
        const raw = {};
        for (const [unitId, state] of Object.entries(this._ratingStates)) {
            raw[unitId] = state.ratings();
        }
        return raw;
    }

    set ratings(val) {
        this._ratingStates = {};
        this._knownUnitModes = 0;
        this._matureUnitModes = 0;
        for (const [unitId, history] of Object.entries(val)) {
            const state = new RatingState(history);
            this._ratingStates[unitId] = state;
            for (const mode of this.modes) {
                if (state.is_known(mode)) {
                    this._knownUnitModes += 1;
                }
                if (state.is_mature(mode)) {
                    this._matureUnitModes += 1;
                }
            }
        }
    }

    setDifficulty(difficulty) {
        this.difficulty = difficulty;
    }

    setModes(modes) {
        this.modes = modes;
        this._knownUnitModes = 0;
        this._matureUnitModes = 0;
        for (const state of Object.values(this._ratingStates)) {
            for (const mode of this.modes) {
                if (state.is_known(mode)) {
                    this._knownUnitModes += 1;
                }
                if (state.is_mature(mode)) {
                    this._matureUnitModes += 1;
                }
            }
        }
    }

    setAssumeKnown(assumeKnown) {
        this.assumeKnown = assumeKnown;
    }

    stats(currentTime) {
        if (currentTime === undefined) {
            currentTime = Date.now() / 1000;
        }
        let waiting = 0;
        for (const unit of this._unitsWithCards) {
            const state = this._ratingStates[unit.id];
            const isSkipped = this.assumeKnown !== null && 
                compareDifficulty(unit.difficulty, this.assumeKnown) <= 0;
            
            if (state === undefined) {
                if (!isSkipped) {
                    break;
                }
                continue;
            }
            if (state.is_waiting(this.modes, currentTime)) {
                waiting += 1;
            }
            if (!isSkipped && this.modes.some(mode => !state.is_introduced(mode))) {
                break;
            }
        }
        return {
            waiting,
            known: Math.floor(this._knownUnitModes / this.modes.length),
            mature: Math.floor(this._matureUnitModes / this.modes.length)
        };
    }

    chooseTask(currentTime) {
        const defaultState = new RatingState([]);
        
        let maxUrgency = -1e5;
        let maxMode = null;
        let maxUnitId = null;
        let introductionIndex = 0;
        let introductionMode = null;
        let introductionUnitId = null;
        let introductionIsTouched = false;
        
        for (let i = 0; i < this._unitsWithCards.length; i++) {
            const unit = this._unitsWithCards[i];
            const state = this._ratingStates[unit.id] || defaultState;
            const isSkipped = this.assumeKnown !== null &&
                compareDifficulty(unit.difficulty, this.assumeKnown) <= 0;
                
            for (const mode of this.modes) {
                const urgency = state.urgency(mode, currentTime);
                if (urgency > maxUrgency) {
                    maxUrgency = urgency;
                    maxMode = mode;
                    maxUnitId = unit.id;
                }
                if (!isSkipped && urgency >= 0.0 && !state.is_introduced(mode)) {
                    introductionIndex = i;
                    introductionMode = mode;
                    introductionUnitId = unit.id;
                    introductionIsTouched = state.is_touched();
                    break;
                }
            }
            if (introductionMode !== null) {
                break;
            }
        }
        
        if (maxMode === null || maxUnitId === null) {
            throw new Error("No units found");
        }
        
        if (maxUrgency > 0.0) {
            // Case 1: Urgent unit earlier than all new units
            return { mode: maxMode, unitId: maxUnitId };
        }
        if (introductionMode === null || introductionUnitId === null) {
            // Case 2: No new units need to be introduced right now
            console.error("Nothing needs to be learned right now");
            return { mode: maxMode, unitId: maxUnitId };
        }
        
        // Second loop over units after first unintroduced
        const TOUCH_TOLERANCE_FACTOR = 1.0;
        const TOUCH_TOLERANCE_BUFFER = 10.0;
        const INTRODUCTION_THRESHOLD = 10.0;
        const INTRODUCE_OUT_OF_ORDER = false;
        
        let tolerance = introductionIndex * TOUCH_TOLERANCE_FACTOR + TOUCH_TOLERANCE_BUFFER;
        tolerance = Math.max(Math.floor(tolerance), 1);
        const toleranceIndex = introductionIndex + tolerance;
        
        let totalPressure = 0.0;
        let maxPressure = 0.0;
        let maxPressureMode = null;
        let maxPressureUnitId = null;
        
        for (let i = introductionIndex; i < Math.min(toleranceIndex, this._unitsWithCards.length); i++) {
            const unit = this._unitsWithCards[i];
            const state = this._ratingStates[unit.id] || defaultState;
            const indexFactor = 1.0 - (i - introductionIndex) / tolerance;
            
            for (const mode of this.modes) {
                const urgency = state.urgency(mode, currentTime);
                if (urgency > 0.0) {
                    const pressure = urgency * indexFactor;
                    totalPressure += pressure;
                    if (pressure > maxPressure) {
                        maxPressure = pressure;
                        maxPressureMode = mode;
                        maxPressureUnitId = unit.id;
                    }
                } else if (
                    INTRODUCE_OUT_OF_ORDER &&
                    !introductionIsTouched &&
                    state.is_touched() &&
                    !state.is_introduced(mode)
                ) {
                    introductionMode = mode;
                    introductionUnitId = unit.id;
                    introductionIsTouched = true;
                }
            }
        }
        
        if (totalPressure > INTRODUCTION_THRESHOLD) {
            // Case 3: Prioritize learning over introduction
            return { mode: maxPressureMode, unitId: maxPressureUnitId };
        } else {
            // Case 4: Prioritize introduction over learning
            return { mode: introductionMode, unitId: introductionUnitId };
        }
    }

    scoreCard(card, mode, currentTime) {
        const defaultState = new RatingState([]);
        let score = 0.0;
        
        // Calculate usage decays
        const uses = this.cardIdUses[card.id] || [];
        for (const usage of uses) {
            if (usage.isReported) {
                score -= REPORT_PENALTY;
            }
            const days = (currentTime - usage.time) / 60.0 / 60.0 / 24.0;
            if (days >= 0.0) {
                score -= CARD_USAGE_FACTOR * Math.exp(-CARD_USAGE_DECAY * days);
            }
        }

        // Find associated unit tags from card
        const cardUnitIds = Array.from(new Set(card.unit_tags.map(t => t.unit_id).filter(id => id)));
        
        for (const unitId of cardUnitIds) {
            const state = this._ratingStates[unitId] || defaultState;
            if (!state.is_touched()) {
                score -= UNTOUCHED_PENALTY;
            } else if (!state.is_introduced(mode)) {
                score -= UNINTRODUCED_PENALTY;
            }
            let urgency = state.urgency(mode, currentTime);
            if (urgency > 0.0) {
                score += URGENCY_BONUS * Math.max(urgency, 0.1);
            }
            
            // Look up difficulty of unit
            const vocabUnit = this.vocabulary.find(u => u.id === unitId);
            const unitDifficulty = vocabUnit ? vocabUnit.difficulty : "A1";
            
            if (unitDifficulty === this.difficulty) {
                score += DIFFICULTY_MATCH_BONUS;
            } else if (compareDifficulty(unitDifficulty, this.difficulty) > 0) {
                score += DIFFICULTY_PENALTY;
            }
        }
        return score;
    }

    draw(currentTime) {
        if (currentTime === undefined) {
            currentTime = Date.now() / 1000;
        }
        const { mode, unitId } = this.chooseTask(currentTime);
        
        // Fetch cards associated with this unit
        let cardIds = this.cardIndex[unitId] || [];
        cardIds = cardIds.slice(0, 1000);
        let unitCards = cardIds.map(id => this.cards[id]).filter(c => c);
        
        if (unitCards.length === 0) {
            console.error(`No cards found for unit '${unitId}', showing random card.`);
            this.rate(unitId, mode, 0, currentTime);
            
            // Choose a random unit from units with cards
            if (this._unitsWithCards.length === 0) {
                throw new Error("No units with cards available in deck");
            }
            const randomUnit = this._unitsWithCards[Math.floor(Math.random() * this._unitsWithCards.length)];
            let fallbackCardIds = this.cardIndex[randomUnit.id] || [];
            fallbackCardIds = fallbackCardIds.slice(0, 1000);
            unitCards = fallbackCardIds.map(id => this.cards[id]).filter(c => c);
            
            if (unitCards.length === 0) {
                throw new Error("No cards available in deck");
            }
        }

        let bestCard = unitCards[0];
        let bestScore = -Infinity;

        for (const card of unitCards) {
            const score = this.scoreCard(card, mode, currentTime);
            if (score > bestScore) {
                bestScore = score;
                bestCard = card;
            }
        }

        return { mode, card: bestCard };
    }

    rate(unitId, mode, score, currentTime) {
        if (currentTime === undefined) {
            currentTime = Date.now() / 1000;
        }
        const rating = new Rating(mode, currentTime, score);
        let ratingState = this._ratingStates[unitId];
        if (!ratingState) {
            ratingState = new RatingState([]);
        }
        if (this.modes.includes(mode)) {
            this._knownUnitModes -= ratingState.is_known(mode) ? 1 : 0;
            this._matureUnitModes -= ratingState.is_mature(mode) ? 1 : 0;
        }
        ratingState.add(rating);
        this._ratingStates[unitId] = ratingState;
        if (this.modes.includes(mode)) {
            this._knownUnitModes += ratingState.is_known(mode) ? 1 : 0;
            this._matureUnitModes += ratingState.is_mature(mode) ? 1 : 0;
        }
    }

    logUsage(cardId, isReported = false, currentTime) {
        if (currentTime === undefined) {
            currentTime = Date.now() / 1000;
        }
        if (!this.cardIdUses[cardId]) {
            this.cardIdUses[cardId] = [];
        }
        this.cardIdUses[cardId].push({
            time: currentTime,
            isReported
        });
    }
}

function splitIntoParts(card) {
    const parts = [];
    let sentenceIndex = 0;
    const sentence = card.sentence;
    const unitTags = card.unit_tags || [];

    for (const tag of unitTags) {
        const startIdx = sentence.indexOf(tag.occurance, sentenceIndex);
        if (startIdx >= 0) {
            if (startIdx > sentenceIndex) {
                parts.push({
                    occurance: sentence.substring(sentenceIndex, startIdx),
                    unit_id: ""
                });
            }
            parts.push({
                occurance: tag.occurance,
                unit_id: tag.unit_id
            });
            sentenceIndex = startIdx + tag.occurance.length;
        }
    }
    if (sentenceIndex < sentence.length) {
        parts.push({
            occurance: sentence.substring(sentenceIndex),
            unit_id: ""
        });
    }
    return parts;
}

// Export module definitions for browser and Node.js testing compatibility
if (typeof exports !== 'undefined') {
    module.exports = {
        Deck,
        splitIntoParts
    };
} else {
    window.BespokeDeck = {
        Deck,
        splitIntoParts
    };
}
