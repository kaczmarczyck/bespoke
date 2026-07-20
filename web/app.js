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
 * Bespoke Frontend Application Controller
 * Powered by SQLite WASM + OPFS for Offline-First mobile support.
 */

import sqlite3InitModule from './index.mjs';
import './urgency.js';
import './deck.js';

const { Deck, splitIntoParts } = window.BespokeDeck;
const { Rating } = window.BespokeUrgency;

// State variables
let currentDeck = null; // Contains loaded deck metadata
let currentCardState = null; // Contains active drawn card data
let currentRatings = {}; // Key: unit_id, Value: score (0, 1, 2, 3)

// Offline Mode State
let isOfflineMode = true;
let sqliteDb = null;
let jsDeck = null;
let currentDbFilename = "";
let poolUtil = null;
window.downloadedDecks = window.downloadedDecks || {};

// Score cycles (0 -> 3 -> 1 -> 0)
const SCORE_CYCLE = {
    0: 3, // Blue (Untouched) -> Green (Known)
    3: 1, // Green (Known) -> Red (Failed)
    1: 0, // Red (Failed) -> Blue (Untouched)
    2: 1  // Yellow (Treated as Red) -> Red
};

// SQLite WASM reference
let sqlite3 = null;

// UI Elements
const screenDecks = document.getElementById('screen-decks');
const screenStudy = document.getElementById('screen-study');
const deckList = document.getElementById('deck-list');
const btnBackToDecks = document.getElementById('btn-back-to-decks');

const selectTarget = document.getElementById('select-target');
const selectNative = document.getElementById('select-native');
const selectAssumeKnown = document.getElementById('select-assume-known');
const formCreateDeck = document.getElementById('form-create-deck');

const badgeMode = document.getElementById('badge-mode');
const statKnown = document.getElementById('stat-known');
const statMature = document.getElementById('stat-mature');
const statTodo = document.getElementById('stat-todo');

const flashcard = document.getElementById('flashcard');
const cardFrontText = document.getElementById('card-front-text');
const cardBackSentence = document.getElementById('card-back-sentence');
const cardBackPhonetic = document.getElementById('card-back-phonetic');
const cardBackTranslation = document.getElementById('card-back-translation');

const audioPlayer = document.getElementById('audio-player');
const btnFrontPlay = document.getElementById('btn-front-play');
const btnFrontSlow = document.getElementById('btn-front-slow');
const btnBackPlay = document.getElementById('btn-back-play');
const btnBackSlow = document.getElementById('btn-back-slow');
const btnBackNative = document.getElementById('btn-back-native');

const definitionDisplay = document.getElementById('definition-display');
const wordBadgeGrid = document.getElementById('word-badge-grid');

const btnFlip = document.getElementById('btn-flip');
const backControls = document.getElementById('back-controls');
const btnAllGreen = document.getElementById('btn-all-green');
const checkReportError = document.getElementById('check-report-error');
const btnNext = document.getElementById('btn-next');

// Initial Setup
document.addEventListener('DOMContentLoaded', () => {
    initApp();

    if ('serviceWorker' in navigator && !window.location.search.includes('no-sw')) {
        navigator.serviceWorker.register('/service-worker.js')
            .then(reg => console.log('Service Worker registered successfully:', reg.scope))
            .catch(err => console.error('Service Worker registration failed:', err));
    }
});

async function initApp() {
    setupEventListeners();
    try {
        await getSqlite3();
    } catch (e) {
        console.warn("Failed to initialize SQLite:", e);
    }
    loadDecksAndLanguages();
}

function setupEventListeners() {
    btnBackToDecks.addEventListener('click', showDeckSelection);
    btnFlip.addEventListener('click', flipCard);
    btnNext.addEventListener('click', finalizeCardAndNext);
    btnAllGreen.addEventListener('click', setAllWordsToGreen);
    formCreateDeck.addEventListener('submit', handleCreateDeck);

    // Audio Trigger Buttons
    btnFrontPlay.addEventListener('click', () => { if (currentCardState) triggerAudioPlay('audio'); });
    btnFrontSlow.addEventListener('click', () => { if (currentCardState) triggerAudioPlay('slow_audio'); });
    btnBackPlay.addEventListener('click', () => { if (currentCardState) triggerAudioPlay('audio'); });
    btnBackSlow.addEventListener('click', () => { if (currentCardState) triggerAudioPlay('slow_audio'); });
    btnBackNative.addEventListener('click', () => { if (currentCardState) triggerAudioPlay('native_audio'); });

    // Keyboard Shortcuts
    window.addEventListener('keydown', handleGlobalKeydown);
}

// -------------------------------------------------------------
// Screen Navigation
// -------------------------------------------------------------

function showDeckSelection() {
    screenStudy.classList.remove('active');
    screenDecks.classList.add('active');
    btnBackToDecks.classList.add('hidden');
    currentDeck = null;
    
    // Close sqlite DB if active to free resource
    if (sqliteDb) {
        try {
            sqliteDb.close();
        } catch (e) {
            console.error("Error closing SQLite DB on exit:", e);
        }
        sqliteDb = null;
    }
    
    jsDeck = null;
    loadDecksAndLanguages();
}

function showStudyScreen() {
    screenDecks.classList.remove('active');
    screenStudy.classList.add('active');
    btnBackToDecks.classList.remove('hidden');
}

// -------------------------------------------------------------
// SQLite WASM Init & Local Storage (OPFS) Downloads
// -------------------------------------------------------------

async function getSqlite3() {
    if (sqlite3) return sqlite3;
    sqlite3 = await sqlite3InitModule({
        print: console.log,
        printErr: console.error,
    });
    window.sqlite3 = sqlite3;
    if (sqlite3.installOpfsSAHPoolVfs) {
        try {
            poolUtil = await sqlite3.installOpfsSAHPoolVfs();
        } catch (e) {
            console.warn("OPFS SAHPool VFS initialization failed:", e);
        }
    }
    return sqlite3;
}

async function isLocalDbStored(target, native) {
    const dbFilename = `deck_${target}_${native}.sqlite3`;
    if (window.downloadedDecks[dbFilename]) {
        return true;
    }
    if (poolUtil) {
        return poolUtil.getFileNames().includes(dbFilename);
    }
    try {
        if (typeof navigator.storage === 'undefined' || !navigator.storage.getDirectory) {
            return false;
        }
        const root = await navigator.storage.getDirectory();
        await root.getFileHandle(dbFilename, { create: false });
        return true;
    } catch (e) {
        return false;
    }
}

async function getAudioFilenamesFromDb(dbFilename, target, native) {
    const sqlite = await getSqlite3();
    let db;
    if (poolUtil && poolUtil.OpfsSAHPoolDb) {
        db = new poolUtil.OpfsSAHPoolDb(dbFilename);
    } else {
        try {
            if (!('opfs' in sqlite)) {
                throw new Error("OPFS not in sqliteInitModule");
            }
            db = new sqlite.oo1.OpfsDb(dbFilename);
        } catch (e) {
            console.warn("OPFS not available for metadata lookup, using in-memory:", e);
            let bytes = window.downloadedDecks[dbFilename];
            if (!bytes) {
                const root = await navigator.storage.getDirectory();
                const fileHandle = await root.getFileHandle(dbFilename);
                const file = await fileHandle.getFile();
                const buffer = await file.arrayBuffer();
                bytes = new Uint8Array(buffer);
            }
            const pData = sqlite.wasm.alloc(bytes.byteLength);
            sqlite.wasm.heap8u().set(bytes, pData);
            db = new sqlite.oo1.DB();
            const rc = sqlite.capi.sqlite3_deserialize(
                db.pointer,
                "main",
                pData,
                bytes.byteLength,
                bytes.byteLength,
                1 | 2
            );
            if (rc !== 0) throw new Error("deserialize failed");
        }
    }

    const audioFiles = new Set();
    try {
        db.exec({
            sql: "SELECT DISTINCT audio_filename, slow_audio_filename, native_audio_filename FROM cards;",
            rowMode: 'array',
            callback: (row) => {
                if (row[0]) audioFiles.add(row[0]);
                if (row[1]) audioFiles.add(row[1]);
                if (row[2]) audioFiles.add(row[2]);
            }
        });
    } catch (err) {
        console.error("Error querying audio filenames from DB:", err);
    } finally {
        try {
            db.close();
        } catch (e) {}
    }
    return audioFiles;
}

async function downloadAudioFilesForDb(audioFiles, onProgress) {
    const cache = await caches.open('bespoke-audio-cache');
    const filesArray = Array.from(audioFiles);
    const total = filesArray.length;
    let loaded = 0;
    
    const limit = 10;
    const chunks = [];
    for (let i = 0; i < total; i += limit) {
        chunks.push(filesArray.slice(i, i + limit));
    }
    
    for (const chunk of chunks) {
        await Promise.all(chunk.map(async (filename) => {
            const url = filename.startsWith('/') ? filename : `/${filename}`;
            const exists = await cache.match(url);
            if (exists) {
                loaded++;
                if (onProgress) {
                    onProgress({ stage: 'audio', loaded, total });
                }
                return;
            }
            try {
                const res = await fetch(url);
                if (res.ok) {
                    await cache.put(url, res);
                }
            } catch (err) {
                console.warn(`Failed to cache audio file ${url}:`, err);
            }
            loaded++;
            if (onProgress) {
                onProgress({ stage: 'audio', loaded, total });
            }
        }));
    }
}

async function downloadAndStoreDb(target, native, onProgress) {
    const dbFilename = `deck_${target}_${native}.sqlite3`;
    const url = `/cards/${target}_${native}.db`;
    console.log(`Downloading deck database from ${url}...`);
    
    if (onProgress) {
        onProgress({ stage: 'db', percent: null });
    }
    
    const response = await fetch(url);
    if (!response.ok) {
        throw new Error(`Failed to download deck database. Server responded with ${response.status}`);
    }
    
    // Check if we are running in headless test mode where OPFS is restricted
    const isUnderTest = window.__isUnderTest || !sqliteDb || !('opfs' in (window.sqlite3 || {}));
    
    if (isUnderTest) {
        const buffer = await response.arrayBuffer();
        const bytes = new Uint8Array(buffer);
        window.downloadedDecks[dbFilename] = bytes;
        console.log(`Saved database ${dbFilename} to browser memory for testing.`);
    } else if (poolUtil) {
        const reader = response.body.getReader();
        const callback = async () => {
            const { done, value } = await reader.read();
            if (done) return undefined;
            return value;
        };
        await poolUtil.importDb(dbFilename, callback);
        console.log(`Saved database ${dbFilename} to browser OPFS storage.`);
    } else {
        if (typeof navigator.storage === 'undefined' || !navigator.storage.getDirectory) {
            throw new Error("OPFS navigator.storage is not available (non-secure context?).");
        }
        const root = await navigator.storage.getDirectory();
        const fileHandle = await root.getFileHandle(dbFilename, { create: true });
        const writable = await fileHandle.createWritable();
        const reader = response.body.getReader();
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            await writable.write(value);
        }
        await writable.close();
        console.log(`Saved database ${dbFilename} to browser OPFS storage.`);
    }

    if (onProgress) {
        onProgress({ stage: 'db_complete' });
    }
    
    const audioFiles = await getAudioFilenamesFromDb(dbFilename, target, native);
    console.log(`Found ${audioFiles.size} audio files to cache.`);
    
    if (audioFiles.size > 0) {
        await downloadAudioFilesForDb(audioFiles, onProgress);
    }
}


async function loadOfflineDeck(target, native, difficulty, modes, assumeKnown) {
    const dbFilename = `deck_${target}_${native}.sqlite3`;
    
    // Persist and load settings from localStorage
    const settingsKey = `bespoke_settings_${target}_${native}`;
    let savedSettings = null;
    try {
        const raw = localStorage.getItem(settingsKey);
        if (raw) savedSettings = JSON.parse(raw);
    } catch (e) {
        console.warn("Failed to read settings from localStorage:", e);
    }

    const finalDifficulty = difficulty !== undefined ? difficulty : (savedSettings ? savedSettings.difficulty : "A1");
    const finalModes = modes !== undefined ? modes : (savedSettings ? savedSettings.modes : ["listen", "speak", "read", "write"]);
    const finalAssumeKnown = assumeKnown !== undefined ? assumeKnown : (savedSettings ? savedSettings.assumeKnown : null);

    try {
        localStorage.setItem(settingsKey, JSON.stringify({
            difficulty: finalDifficulty,
            modes: finalModes,
            assumeKnown: finalAssumeKnown
        }));
    } catch (e) {
        console.warn("Failed to save settings to localStorage:", e);
    }

    const sqlite = await getSqlite3();
    let db;
    if (poolUtil && poolUtil.OpfsSAHPoolDb) {
        db = new poolUtil.OpfsSAHPoolDb(dbFilename);
        console.log("Using OPFS SAHPool database:", dbFilename);
    } else {
        try {
            if (!('opfs' in sqlite)) {
                throw new Error("OPFS not in sqliteInitModule");
            }
            db = new sqlite.oo1.OpfsDb(dbFilename);
            console.log("Using OPFS OpfsDb database:", dbFilename);
        } catch (e) {
            console.warn("OPFS database VFS not available on main thread, falling back to in-memory deserialization:", e);
            
            let bytes = window.downloadedDecks[dbFilename];
            if (!bytes) {
                try {
                    if (typeof navigator.storage === 'undefined' || !navigator.storage.getDirectory) {
                        throw new Error("OPFS is not available.");
                    }
                    const root = await navigator.storage.getDirectory();
                    const fileHandle = await root.getFileHandle(dbFilename);
                    const file = await fileHandle.getFile();
                    const buffer = await file.arrayBuffer();
                    bytes = new Uint8Array(buffer);
                } catch (err) {
                    console.log("Failed to read from OPFS storage, downloading directly:", err);
                    const url = `/cards/${target}_${native}.db`;
                    const response = await fetch(url);
                    if (!response.ok) {
                        throw new Error(`Failed to fetch database bytes: ${response.status}`);
                    }
                    const buffer = await response.arrayBuffer();
                    bytes = new Uint8Array(buffer);
                }
            }
            
            // Allocate and copy bytes to WASM heap
            const pData = sqlite.wasm.alloc(bytes.byteLength);
            sqlite.wasm.heap8u().set(bytes, pData);
            
            // Create transient in-memory DB
            db = new sqlite.oo1.DB();
            
            // Deserialize bytes into DB
            const SQLITE_DESERIALIZE_FREEONCLOSE = 1;
            const SQLITE_DESERIALIZE_RESIZEABLE = 2;
            const rc = sqlite.capi.sqlite3_deserialize(
                db.pointer,
                "main",
                pData,
                bytes.byteLength,
                bytes.byteLength,
                SQLITE_DESERIALIZE_FREEONCLOSE | SQLITE_DESERIALIZE_RESIZEABLE
            );
            if (rc !== 0) {
                throw new Error(`sqlite3_deserialize failed with code ${rc}`);
            }
            console.log("Successfully deserialized database into in-memory SQLite instance!");
            try {
                db.exec("PRAGMA journal_mode=MEMORY;");
            } catch (err) {
                console.warn("Failed to set journal_mode=MEMORY:", err);
            }
        }
    }
    sqliteDb = db;
    currentDbFilename = dbFilename;

    // Create user ratings table inside DB if missing
    db.exec(`
        CREATE TABLE IF NOT EXISTS ratings (
            unit_id TEXT NOT NULL,
            mode TEXT NOT NULL,
            time REAL NOT NULL,
            score INTEGER NOT NULL
        );
    `);
    
    // Create usage log table inside DB if missing
    db.exec(`
        CREATE TABLE IF NOT EXISTS card_usage (
            card_id TEXT NOT NULL,
            time REAL NOT NULL,
            is_reported INTEGER NOT NULL
        );
    `);

    // 1. Load vocabulary units
    const vocabulary = [];
    db.exec({
        sql: "SELECT id, name, definition, difficulty FROM vocabulary;",
        rowMode: 'object',
        callback: (row) => {
            vocabulary.push({
                id: row.id,
                name: row.name,
                definition: row.definition,
                difficulty: row.difficulty
            });
        }
    });

    // 2. Load card index map
    const cardIndex = {};
    db.exec({
        sql: "SELECT unit_id, card_id FROM unit_cards;",
        rowMode: 'array',
        callback: (row) => {
            const unitId = row[0];
            const cardId = row[1];
            if (!cardIndex[unitId]) {
                cardIndex[unitId] = [];
            }
            cardIndex[unitId].push(cardId);
        }
    });

    // 3. Load card JSON metadata (kept in memory!)
    const cards = {};
    db.exec({
        sql: "SELECT id, sentence, native_sentence, phonetic, unit_tags, notes, audio_filename, slow_audio_filename, native_audio_filename FROM cards;",
        rowMode: 'object',
        callback: (row) => {
            const unitTags = JSON.parse(row.unit_tags) || [];
            unitTags.sort((a, b) => row.sentence.indexOf(a.occurance) - row.sentence.indexOf(b.occurance));

            cards[row.id] = {
                id: row.id,
                sentence: row.sentence,
                native_sentence: row.native_sentence,
                phonetic: row.phonetic,
                unit_tags: unitTags,
                notes: JSON.parse(row.notes),
                audio_filename: row.audio_filename,
                slow_audio_filename: row.slow_audio_filename,
                native_audio_filename: row.native_audio_filename
            };
        }
    });

    // 4. Instantiate JS Deck
    jsDeck = new Deck({
        targetLanguage: target,
        nativeLanguage: native,
        vocabulary,
        cardIndex,
        cards
    });
    jsDeck.setDifficulty(finalDifficulty);
    jsDeck.setModes(finalModes);
    jsDeck.setAssumeKnown(finalAssumeKnown);

    // 5. Populate rating logs from DB
    db.exec({
        sql: "SELECT unit_id, mode, time, score FROM ratings;",
        rowMode: 'object',
        callback: (row) => {
            jsDeck.rate(row.unit_id, row.mode, row.score, row.time);
        }
    });

    // 6. Populate card usage logs from DB
    db.exec({
        sql: "SELECT card_id, time, is_reported FROM card_usage;",
        rowMode: 'object',
        callback: (row) => {
            if (!jsDeck.cardIdUses[row.card_id]) {
                jsDeck.cardIdUses[row.card_id] = [];
            }
            jsDeck.cardIdUses[row.card_id].push({
                time: row.time,
                isReported: !!row.is_reported
            });
        }
    });

    isOfflineMode = true;
    console.log(`Successfully initialized JS Deck offline in browser.`);
}

async function getOPFSDecks() {
    const decks = [];
    // Include memory cached decks first
    Object.keys(window.downloadedDecks).forEach(name => {
        if (name.startsWith('deck_') && name.endsWith('.sqlite3')) {
            const match = name.match(/^deck_(.+?)_(.+?)\.sqlite3$/);
            if (match) {
                decks.push({
                    filename: name,
                    target_language: match[1],
                    native_language: match[2],
                    difficulty: "A1",
                    isOfflineStored: true
                });
            }
        }
    });

    if (poolUtil) {
        try {
            const fileNames = poolUtil.getFileNames();
            fileNames.forEach(name => {
                if (window.downloadedDecks[name]) return;
                if (name.startsWith('deck_') && name.endsWith('.sqlite3')) {
                    const match = name.match(/^deck_(.+?)_(.+?)\.sqlite3$/);
                    if (match) {
                        decks.push({
                            filename: name,
                            target_language: match[1],
                            native_language: match[2],
                            difficulty: "A1",
                            isOfflineStored: true
                        });
                    }
                }
            });
            return decks;
        } catch (e) {
            console.error("Error reading file names from pool:", e);
        }
    }
    try {
        if (typeof navigator.storage === 'undefined' || !navigator.storage.getDirectory) {
            console.warn("OPFS navigator.storage is not available.");
            return decks;
        }
        const root = await navigator.storage.getDirectory();
        for await (const name of root.keys()) {
            if (window.downloadedDecks[name]) continue;
            if (name.startsWith('deck_') && name.endsWith('.sqlite3')) {
                const match = name.match(/^deck_(.+?)_(.+?)\.sqlite3$/);
                if (match) {
                    decks.push({
                        filename: name,
                        target_language: match[1],
                        native_language: match[2],
                        difficulty: "A1", // Defaults for local offline listing
                        isOfflineStored: true
                    });
                }
            }
        }
    } catch (e) {
        console.error("Error reading directory from OPFS:", e);
    }
    return decks;
}

// -------------------------------------------------------------
// Render Decks List & Language Dropdowns
// -------------------------------------------------------------

async function loadDecksAndLanguages() {
    let apiDecks = [];
    let apiLangs = [];
    let serverAvailable = true;

    // 1. Try fetching from server
    try {
        const response = await fetch('/api/decks');
        if (response.ok) {
            const data = await response.json();
            apiDecks = data.decks;
            apiLangs = data.languages;
        } else {
            serverAvailable = false;
        }
    } catch (e) {
        serverAvailable = false;
    }

    // 2. Fetch OPFS decks stored locally
    const storedDecks = await getOPFSDecks();

    // 3. Render combined Decks list
    renderCombinedDecks(apiDecks, storedDecks, serverAvailable);

    // 4. Render Dropdowns
    if (serverAvailable) {
        populateLanguages(apiLangs);
    } else {
        // Mock default offline language selectors if server is dead
        populateLanguages([
            { code_name: "simp_chinese", name: "Chinese", writing_system: "Simplified Chinese", has_data: true },
            { code_name: "trad_chinese", name: "Chinese", writing_system: "Traditional Chinese", has_data: true },
            { code_name: "german", name: "German", writing_system: "German", has_data: true },
            { code_name: "english", name: "English", writing_system: "English", has_data: true }
        ]);
    }
}

function renderCombinedDecks(apiDecks, storedDecks, serverAvailable) {
    deckList.innerHTML = '';
    
    // Map offline databases in index
    const offlineMap = {};
    storedDecks.forEach(d => {
        offlineMap[`${d.target_language}_${d.native_language}`] = true;
    });

    // Render list
    const renderedKeys = new Set();

    // Loop through server decks
    apiDecks.forEach(deck => {
        const key = `${deck.target_language}_${deck.native_language}`;
        renderedKeys.add(key);

        const isDownloaded = !!offlineMap[key];

        const item = document.createElement('div');
        item.className = 'deck-item';
        item.innerHTML = `
            <div class="deck-details">
                <h3>${deck.target_writing_system} Decks</h3>
                <div class="deck-meta">
                    <span>Native: ${deck.native_writing_system}</span>
                    <span>Level: ${deck.difficulty}</span>
                    ${isDownloaded ? '<span style="color: var(--color-success)">Offline Mode Available</span>' : ''}
                </div>
            </div>
            <div class="deck-action-buttons">
                ${!isDownloaded ? `<button class="outline-button download-db-btn" data-target="${deck.target_language}" data-native="${deck.native_language}"><span class="material-icons">download</span> Download</button>` : ''}
                <button class="primary-button play-deck-btn" data-filename="${deck.filename}" data-target="${deck.target_language}" data-native="${deck.native_language}"><span class="material-icons">play_arrow</span> Play</button>
            </div>
        `;
        
        // Add download listener
        const downloadBtn = item.querySelector('.download-db-btn');
        if (downloadBtn) {
            downloadBtn.addEventListener('click', async (e) => {
                e.stopPropagation();
                downloadBtn.disabled = true;
                downloadBtn.textContent = "Downloading DB...";
                try {
                    await downloadAndStoreDb(deck.target_language, deck.native_language, (progress) => {
                        if (progress.stage === 'db') {
                            downloadBtn.textContent = "Downloading DB...";
                        } else if (progress.stage === 'db_complete') {
                            downloadBtn.textContent = "Extracting audio...";
                        } else if (progress.stage === 'audio') {
                            const percent = Math.round((progress.loaded / progress.total) * 100);
                            downloadBtn.textContent = `Audio: ${progress.loaded}/${progress.total} (${percent}%)`;
                        }
                    });
                    alert("Download complete! This deck is now offline-ready.");
                    loadDecksAndLanguages();
                } catch (err) {
                    alert(`Download failed: ${err.message}`);
                    downloadBtn.disabled = false;
                    downloadBtn.innerHTML = `<span class="material-icons">download</span> Download`;
                }
            });
        }

        // Add play click listener
        item.querySelector('.play-deck-btn').addEventListener('click', async () => {
            if (isDownloaded) {
                // If downloaded locally, load offline DB
                await loadOfflineDeck(deck.target_language, deck.native_language, deck.difficulty, deck.modes, deck.assume_known);
                showStudyScreen();
                drawNextCard();
            } else {
                alert("Please download this deck first to learn offline.");
            }
        });

        deckList.appendChild(item);
    });

    // Add any OPFS stored decks that are not on the server list (running purely offline)
    storedDecks.forEach(deck => {
        const key = `${deck.target_language}_${deck.native_language}`;
        if (renderedKeys.has(key)) return;

        const item = document.createElement('div');
        item.className = 'deck-item';
        item.innerHTML = `
            <div class="deck-details">
                <h3>${formatLanguageName(deck.target_language)} Decks (Offline Only)</h3>
                <div class="deck-meta">
                    <span>Native: ${formatLanguageName(deck.native_language)}</span>
                    <span style="color: var(--color-success)">Stored locally in OPFS</span>
                </div>
            </div>
            <button class="primary-button play-deck-btn"><span class="material-icons">play_arrow</span> Play</button>
        `;

        item.querySelector('.play-deck-btn').addEventListener('click', async () => {
            await loadOfflineDeck(deck.target_language, deck.native_language);
            showStudyScreen();
            drawNextCard();
        });

        deckList.appendChild(item);
    });

    if (deckList.children.length === 0) {
        deckList.innerHTML = `<div class="loading-placeholder">No learning decks found. Create one below!</div>`;
    }
}

function populateLanguages(languages) {
    const prevTarget = selectTarget.value;
    const prevNative = selectNative.value;

    selectTarget.innerHTML = '<option value="" disabled selected>Select target...</option>';
    selectNative.innerHTML = '<option value="" disabled selected>Select native...</option>';

    languages.forEach(lang => {
        if (lang.has_data) {
            const optTarget = document.createElement('option');
            optTarget.value = lang.code_name;
            optTarget.textContent = lang.writing_system;
            selectTarget.appendChild(optTarget);
        }

        const optNative = document.createElement('option');
        optNative.value = lang.code_name;
        optNative.textContent = lang.writing_system;
        selectNative.appendChild(optNative);
    });

    if (prevTarget) selectTarget.value = prevTarget;
    if (prevNative) selectNative.value = prevNative;
}

function formatLanguageName(codeName) {
    if (!codeName) return '';
    return codeName.charAt(0).toUpperCase() + codeName.slice(1).replace('_', ' ');
}

// -------------------------------------------------------------
// Offline Deck Creation & Operations
// -------------------------------------------------------------

async function handleCreateDeck(event) {
    event.preventDefault();
    const target = selectTarget.value;
    const native = selectNative.value;
    const difficulty = document.getElementById('select-difficulty').value;
    const assumeKnown = selectAssumeKnown.value || null;

    const checkedModes = Array.from(document.querySelectorAll('input[name="modes"]:checked'))
                              .map(cb => cb.value);

    if (checkedModes.length === 0) {
        alert("Please select at least one learning mode.");
        return;
    }

    const isOfflineAvailable = await isLocalDbStored(target, native);
    if (isOfflineAvailable) {
        // Setup local offline deck
        await loadOfflineDeck(target, native, difficulty, checkedModes, assumeKnown);
        showStudyScreen();
        drawNextCard();
    } else {
        alert(`The deck database for ${formatLanguageName(target)} (Target) to ${formatLanguageName(native)} (Native) is not downloaded. Please download it from the deck list above first.`);
    }
}

// -------------------------------------------------------------
// Card Drawing Loop (Offline Only)
// -------------------------------------------------------------

async function drawNextCard() {
    // Reset layout
    unflipCard();
    checkReportError.checked = false;
    currentRatings = {};
    definitionDisplay.innerHTML = '&nbsp;';

    try {
        const { mode, card } = jsDeck.draw();
        
        // Build unit tags list for badges
        const unitParts = [];
        splitIntoParts(card).forEach(tag => {
            let translation = "";
            if (tag.unit_id) {
                // Look up translations offline
                sqliteDb.exec({
                    sql: "SELECT translation FROM translations WHERE unit_id = ?;",
                    bind: [tag.unit_id],
                    rowMode: 'array',
                    callback: (row) => { translation = row[0]; }
                });
                
                // Fallback to dictionary description if translation is missing
                if (!translation) {
                    const vocab = jsDeck.vocabulary.find(u => u.id === tag.unit_id);
                    if (vocab && vocab.definition) {
                        translation = vocab.definition;
                    }
                }
            }
            
            unitParts.push({
                occurance: tag.occurance,
                unit_id: tag.unit_id,
                translation
            });
        });

        const stats = jsDeck.stats();

        currentCardState = {
            mode,
            card: {
                id: card.id,
                sentence: card.sentence,
                native_sentence: card.native_sentence,
                phonetic: card.phonetic,
                notes: card.notes,
                parts: unitParts
            },
            stats
        };

        renderCardFront();
        renderCardBack();
        updateStats();

        // Autoplay in listen mode
        if (mode === 'listen') {
            setTimeout(() => triggerAudioPlay('audio'), 200);
        }
    } catch (e) {
        console.error("Offline draw error:", e);
        cardFrontText.innerHTML = '<div style="color: var(--color-danger)">Offline Draw Error.</div>';
    }
}

function updateStats() {
    if (!currentCardState) return;
    const stats = currentCardState.stats;
    statKnown.textContent = `Known: ${stats.known}`;
    if (statMature) {
        statMature.textContent = `Mature: ${stats.mature}`;
    }
    statTodo.textContent = `To Do: ${stats.waiting}`;
    badgeMode.textContent = currentCardState.mode.toUpperCase();
}

function renderCardFront() {
    const card = currentCardState.card;
    const mode = currentCardState.mode;

    document.getElementById('mode-prompt-listen').classList.add('hidden');
    document.getElementById('mode-prompt-speak').classList.add('hidden');
    document.getElementById('mode-prompt-write').classList.add('hidden');
    document.getElementById('mode-prompt-read').classList.add('hidden');

    const activePrompt = document.getElementById(`mode-prompt-${mode}`);
    if (activePrompt) {
        activePrompt.classList.remove('hidden');
    }

    if (mode === 'listen') {
        cardFrontText.textContent = '???';
        btnFrontPlay.classList.remove('hidden');
        btnFrontSlow.classList.remove('hidden');
    } else if (mode === 'speak' || mode === 'write') {
        cardFrontText.textContent = card.native_sentence;
        btnFrontPlay.classList.add('hidden');
        btnFrontSlow.classList.add('hidden');
    } else if (mode === 'read') {
        cardFrontText.textContent = card.sentence;
        btnFrontPlay.classList.add('hidden');
        btnFrontSlow.classList.add('hidden');
    }
}

function renderCardBack() {
    const card = currentCardState.card;
    cardBackSentence.textContent = card.sentence;
    cardBackPhonetic.textContent = card.phonetic || '';
    cardBackTranslation.textContent = card.native_sentence;

    wordBadgeGrid.innerHTML = '';
    card.parts.forEach(part => {
        const column = document.createElement('div');
        column.className = 'word-column';

        if (!part.unit_id) {
            const textNode = document.createElement('span');
            textNode.className = 'plain-text';
            textNode.textContent = part.occurance;
            column.appendChild(textNode);
        } else {
            const btn = document.createElement('button');
            btn.className = 'word-btn rating-0';
            btn.textContent = part.occurance;
            
            currentRatings[part.unit_id] = 0;

            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                cycleWordRating(part.unit_id, btn);
            });

            btn.addEventListener('mouseenter', () => {
                definitionDisplay.textContent = part.translation || 'No translation available';
            });
            btn.addEventListener('mouseleave', () => {
                definitionDisplay.innerHTML = '&nbsp;';
            });

            column.appendChild(btn);

            const label = document.createElement('span');
            label.className = 'word-subtext';
            label.textContent = part.unit_id;
            column.appendChild(label);
        }
        wordBadgeGrid.appendChild(column);
    });
}

function cycleWordRating(unitId, buttonElement) {
    const current = currentRatings[unitId];
    const next = SCORE_CYCLE[current] !== undefined ? SCORE_CYCLE[current] : 0;
    currentRatings[unitId] = next;
    buttonElement.className = `word-btn rating-${next}`;
}

function setAllWordsToGreen() {
    Object.keys(currentRatings).forEach(unitId => {
        currentRatings[unitId] = 3;
    });

    const buttons = wordBadgeGrid.querySelectorAll('.word-btn');
    buttons.forEach(btn => {
        btn.className = 'word-btn rating-3';
    });
}

// -------------------------------------------------------------
// Interactive Controls (Flip, Audio & Finalize)
// -------------------------------------------------------------

function flipCard() {
    flashcard.classList.add('flipped');
    btnFlip.classList.add('hidden');
    backControls.classList.remove('hidden');

    if (currentCardState && currentCardState.mode !== 'listen') {
        setTimeout(() => triggerAudioPlay('audio'), 200);
    }
}

function unflipCard() {
    flashcard.classList.remove('flipped');
    btnFlip.classList.remove('hidden');
    backControls.classList.add('hidden');
}

function handleGlobalKeydown(e) {
    const tag = e.target && e.target.tagName ? e.target.tagName.toLowerCase() : '';
    if (tag === 'input' || tag === 'select' || tag === 'textarea' || (e.target && e.target.isContentEditable)) {
        return;
    }

    if (!screenStudy.classList.contains('active')) {
        return;
    }

    const isFlipped = flashcard.classList.contains('flipped');
    const activeFace = isFlipped ? '.card-back' : '.card-front';
    const visibleButtons = Array.from(document.querySelectorAll(`${activeFace} .audio-controls-row button`))
        .filter(btn => !btn.classList.contains('hidden') && btn.style.display !== 'none');

    if (e.key === '1') {
        if (visibleButtons.length >= 1) {
            visibleButtons[0].click();
        }
    } else if (e.key === '2') {
        if (visibleButtons.length >= 2) {
            visibleButtons[1].click();
        }
    } else if (e.key === '3') {
        if (visibleButtons.length >= 3) {
            visibleButtons[2].click();
        }
    } else if (e.key === ' ') {
        e.preventDefault();
        if (!isFlipped) {
            flipCard();
        } else {
            unflipCard();
        }
    } else if (e.key === 'Enter') {
        if (isFlipped) {
            btnNext.click();
        }
    }
}

async function triggerAudioPlay(fieldName) {
    if (!currentCardState) return;

    // Query audio bytes BLOB from browser SQLite DB
    let audioBlob = null;
    try {
        sqliteDb.exec({
            sql: `SELECT ${fieldName} FROM cards WHERE id = ?;`,
            bind: [currentCardState.card.id],
            rowMode: 'array',
            callback: (row) => {
                const bytes = row[0]; // Uint8Array
                if (bytes) {
                    audioBlob = new Blob([bytes], { type: 'audio/ogg' });
                }
            }
        });
        
        if (audioBlob) {
            const url = URL.createObjectURL(audioBlob);
            audioPlayer.src = url;
            audioPlayer.play().catch(e => console.log("Audio playback blocked:", e));
            
            // Revoke URL after play ends to free browser memory leaks
            audioPlayer.onended = () => URL.revokeObjectURL(url);
        } else {
            // Fallback: load directly from the server if online
            const filename = currentCardState.card[`${fieldName}_filename`];
            if (filename) {
                // Prepend slash if needed
                const srcUrl = filename.startsWith('/') ? filename : `/${filename}`;
                audioPlayer.src = srcUrl;
                audioPlayer.play().catch(e => console.log("Audio playback blocked:", e));
            } else {
                console.log(`Audio file path for '${fieldName}' not found for card ID: ${currentCardState.card.id}`);
            }
        }
    } catch (e) {
        console.error("Error loading audio BLOB offline:", e);
    }
}

async function finalizeCardAndNext() {
    if (!currentCardState) return;

    const isReported = checkReportError.checked;
    const mode = currentCardState.mode;
    const currentTime = Date.now() / 1000;

    try {
        // Apply ratings locally in JS Deck
        for (const [unitId, score] of Object.entries(currentRatings)) {
            jsDeck.rate(unitId, mode, score, currentTime);
            
            // Write progress to OPFS SQLite ratings table
            sqliteDb.exec({
                sql: "INSERT INTO ratings (unit_id, mode, time, score) VALUES (?, ?, ?, ?);",
                bind: [unitId, mode, currentTime, score]
            });
        }
        
        // Log card usage locally in JS Deck
        jsDeck.logUsage(currentCardState.card.id, isReported, currentTime);
        
        // Write card usage log to OPFS SQLite card_usage table
        sqliteDb.exec({
            sql: "INSERT INTO card_usage (card_id, time, is_reported) VALUES (?, ?, ?);",
            bind: [currentCardState.card.id, currentTime, isReported ? 1 : 0]
        });
        
    } catch (e) {
        console.error("Error finalizing card ratings offline:", e);
    }
    
    // Draw next card offline
    drawNextCard();
}
