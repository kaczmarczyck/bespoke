<img alt="Bespoke logo" src="docs/icon.png" width="200px">

# Bespoke Language Learning

Bespoke is a language learning tool that helps you both memorize and apply
vocabulary in context. Powered by spaced repetition, users are shown sentences
that connect words that need practice.

Generative AI can help you create large amounts of custom flashcards for any
language pair. Or, if a dataset already exists, jump straight into learning!

Compared to existing flashcard software, this tool is specialized for
languages, with the following advantages:

- Depth: Beyond pure memorization, you learn to use vocabulary in sentences.
- Efficiency: A flashcard can have more than one learnable unit.
- Cohesion: Supports receptive (listen/read) and expressive (speak/write)
  skills. It adjusts your review schedule to account for cross-pollination. 🐝

Bespoke is experimental, and we are still learning how to learn better.

## Overview

The project consists of 2 parts:

- The LLM calls to generate the collection of learning cards.
- A simple frontend that selects and shows cards to the user.

## How to create cards

The commands below run Bespoke with
[uv](https://docs.astral.sh/uv/getting-started/installation/).
You can also use a different package manager that can read pyproject.toml.

You may skip the rest of this section if you find your languages in
[Existing datasets](#existing-datasets).

You need FFmpeg installed and an API key.
Depending on what keys you export, the model will be chosen.
You can use:

- `GEMINI_API_KEY`
- `OPENROUTER_API_KEY` and `ELEVENLABS_API_KEY` (text and speech)
- `OPENAI_API_KEY`

Example run commands:

```
apt-get install ffmpeg
export GEMINI_API_KEY=your_key_here
uv run create.py --target="Japanese" --native="English"
```

You can also use other models, see [llm.py](bespoke/llm.py).
The quality of generated cards varies between providers and models.

## How to start learning

Bespoke runs as an **offline-first Progressive Web App (PWA)**. The scheduling, card index, and audio BLOBs are queried entirely in the browser using SQLite compiled to WebAssembly (WASM).

### 1. Compile the cards database
Before you start learning, you need to compile your generated flat card JSON files and audio `.ogg` files into a single SQLite database:

```bash
uv run package_db.py --target="german" --native="english" --output="cards/german_english.db"
```
*(Use the language code names, e.g., `german`, `japanese`, `simp_chinese`, `trad_chinese`)*.

### 2. Launch the application
Run the local static server:

```bash
uv run learn.py
```
A new tab will automatically open in your default browser at `http://localhost:8080/`.

### 3. Study and Go Offline
- In the browser UI, choose the deck you want to learn.
- Click **Download** next to the deck. This stores the single SQLite database inside your browser's high-performance **Origin Private File System (OPFS)**.
- Once downloaded, the deck runs **100% offline**! You can close the local python server, turn off your internet, and continue learning, playing audio on demand, and tracking reviews completely offline.

---

## Existing datasets

You can download existing pre-generated language datasets:

| Language Pair | Kaggle Dataset |
| :------------ | :------------- |
| German → Traditional Chinese | [bespoke-cards-german-tradchinese](https://www.kaggle.com/datasets/google/bespoke-cards-german-tradchinese) |
| English → German | [bespoke-cards-english-german](https://www.kaggle.com/datasets/google/bespoke-cards-english-german) |
| Simplified Chinese → German | [bespoke-cards-german-simpchinese](https://www.kaggle.com/datasets/google/bespoke-cards-simpchinese-german) |

Download the dataset `.zip` file into the `cards/` directory, unzip it, and compile it to SQLite:

```bash
# Example for English to German
cd cards/
unzip bespoke-cards-english-german.zip
cd ..
uv run package_db.py --target="german" --native="english" --output="cards/german_english.db"
```

---

## Backups & Progress

All review history, ratings, and scheduling states are saved inside the local SQLite database inside your browser's secure sandboxed storage (OPFS). 

Because the app is fully serverless on the client side, your progress is tied to your browser profile. If you clear your browser site data or cookies for the local domain, your local database state (including history progress) will be reset.

## Disclaimer

This is not an officially supported Google product.
This project is not eligible for the
[Google Open Source Software Vulnerability Rewards Program](https://bughunters.google.com/open-source-security).
