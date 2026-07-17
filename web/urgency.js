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
 * Port of bespoke/urgency.py to JavaScript.
 */

const MINUTE = 60.0;
const HOUR = MINUTE * 60.0;
const DAY = HOUR * 24.0;

const BLOCK_INTERVAL = HOUR * 20;
const RED_BLOCK_INTERVAL = MINUTE * 10;
const MINIMUM_BLOCK_INTERVAL = MINUTE * 1;
const BLOCK_SCALE_INTERVAL = DAY * 1;
const INTERVAL_DECAY = 0.5;
const INTERVAL_FACTOR = 1.8;
const MODE_INITIAL_GREEN_INTERVAL = HOUR * 1;
const FULL_INITIAL_GREEN_INTERVAL = DAY * 14;
const WAITING_PROJECTION = RED_BLOCK_INTERVAL;
const KNOWN_AGE = DAY * 1;
const MATURE_AGE = DAY * 21;

const Mode = {
    LISTEN: "listen",
    SPEAK: "speak",
    READ: "read",
    WRITE: "write"
};

class Rating {
    constructor(mode, time, score) {
        this.mode = mode;
        this.time = time;
        this.score = score;
    }
}

class RatingState {
    constructor(ratings) {
        this._ratings = [];
        this._last_red = {};
        this._green_start = {};
        this._green_end = {};
        this._green_streak = {};
        this._block_end = -1e5;
        this._is_touched = false;
        
        if (ratings) {
            for (const r of ratings) {
                this.add(r);
            }
        }
    }

    add(rating) {
        if (this._ratings.length > 0 && this._ratings[this._ratings.length - 1].time > rating.time) {
            console.error("Warning: Rejecting rating out of order");
            return;
        }
        this._ratings.push(rating);
        let base_block_interval = 0.0;
        
        switch (rating.score) {
            case 0:
                base_block_interval = BLOCK_INTERVAL;
                break;
            case 1:
            case 2:
                this._last_red[rating.mode] = rating.time;
                delete this._green_start[rating.mode];
                delete this._green_end[rating.mode];
                let green_streak = this._green_streak[rating.mode];
                if (green_streak !== undefined) {
                    this._green_streak[rating.mode] = green_streak * INTERVAL_DECAY;
                }
                base_block_interval = RED_BLOCK_INTERVAL;
                this._is_touched = true;
                break;
            case 3:
                if (rating.time > this._block_end) {
                    let streak = 0.0;
                    let last_red_time = this._last_red[rating.mode];
                    if (last_red_time !== undefined) {
                        streak = rating.time - last_red_time;
                    } else if (Object.keys(this._last_red).length > 0) {
                        streak = MODE_INITIAL_GREEN_INTERVAL;
                    } else {
                        streak = FULL_INITIAL_GREEN_INTERVAL;
                    }
                    let green_start = this._green_start[rating.mode];
                    if (green_start === undefined) {
                        this._green_start[rating.mode] = rating.time;
                    } else {
                        streak = Math.max(streak, rating.time - green_start);
                    }
                    let last_streak = this._green_streak[rating.mode] || 0.0;
                    this._green_end[rating.mode] = rating.time;
                    this._green_streak[rating.mode] = Math.max(last_streak, streak);
                }
                base_block_interval = BLOCK_INTERVAL;
                this._is_touched = true;
                break;
            default:
                base_block_interval = 0.0;
                console.error("Warning: Found unexpected rating score");
                break;
        }
        
        let green_streaks = Object.values(this._green_streak);
        let max_green_interval = green_streaks.length > 0 ? Math.max(...green_streaks) : 1.0;
        if (max_green_interval <= 0.0) {
            console.error("Warning: Negative green streak");
            max_green_interval = 1.0;
        }
        let block_scale = 1.0 - Math.exp(-max_green_interval / BLOCK_SCALE_INTERVAL);
        let block_interval = base_block_interval * block_scale;
        block_interval = Math.max(block_interval, MINIMUM_BLOCK_INTERVAL);
        this._block_end = Math.max(this._block_end, rating.time + block_interval);
    }

    ratings() {
        return [...this._ratings];
    }

    urgency(mode, current_time) {
        if (current_time < this._block_end) {
            // Blocked
            return -1.0;
        }
        let green_streak = this._green_streak[mode];
        if (green_streak === undefined) {
            // Not introduced, meaning no green ever
            return 0.0;
        }
        let green_end = this._green_end[mode];
        if (green_end === undefined) {
            // Last was red
            return 1.0;
        }
        let target_interval = green_streak * INTERVAL_FACTOR;
        let target = green_end + target_interval;
        let deviation = (current_time - target) / target_interval;
        // Math.tanh centered around target day
        return Math.tanh(deviation);
    }

    is_touched() {
        return this._is_touched;
    }

    is_introduced(mode) {
        return mode in this._green_streak;
    }

    is_waiting(modes, current_time) {
        let projected_time = current_time + WAITING_PROJECTION;
        return modes.some(mode => this.urgency(mode, projected_time) > 0.0);
    }

    is_known(mode) {
        return (this._green_streak[mode] || 0.0) > KNOWN_AGE;
    }

    is_mature(mode) {
        return (this._green_streak[mode] || 0.0) > MATURE_AGE;
    }
}

// Export module definitions for browser and Node.js testing compatibility
if (typeof exports !== 'undefined') {
    module.exports = {
        Mode,
        Rating,
        RatingState
    };
} else {
    window.BespokeUrgency = {
        Mode,
        Rating,
        RatingState
    };
}
