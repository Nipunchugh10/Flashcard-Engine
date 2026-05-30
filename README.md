# Recall — The Flashcard Engine

Drop in a PDF. Get back a practice-ready deck with spaced repetition.

---

## ⚡ Live Demo

Deployed on [Render.com](https://render.com). PDF processing runs in the background so the free tier handles it without crashing.

---

## What it does

1. **Ingest.** You upload a text-based PDF (a chapter, a set of lecture notes, a paper).
2. **Generate.** The app extracts the text, splits it into paragraph-coherent chunks, and asks an LLM to write a mix of concept questions, definitions, cloze deletions, and application/example cards — all in the background so you're never stuck waiting.
3. **Study.** A focused session UI shows one card at a time. You flip the card, rate yourself (Again / Hard / Good / Easy), and the SM-2 algorithm decides when each card should next appear.
4. **Track.** Per-deck stats (total, due, new, review, mastered) and per-card state visible in a browsable, searchable card list.

---

## ⚠️ Before You Start — Read This

> **You need an API key to generate quality flashcards.** Without one, the app falls back to a basic regex-based generator which produces very limited cards.

### Getting an API key (free, 2 minutes)

| Provider | Cost | Free tier | Where to get a key |
|---|---|---|---|
| **Groq** *(recommended)* | Free, no credit card | 30 req/min, 14,400 req/day, Llama 3.3 70B | [console.groq.com](https://console.groq.com) |
| **Google Gemini** | Free, no credit card | 15 req/min, 1,000 req/day, Gemini 2.5 Flash | [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey) |
| **Anthropic Claude** | Paid | — | [console.anthropic.com](https://console.anthropic.com) |

**Groq is recommended** — fastest, highest free-tier limits, no credit card needed.

Priority order when multiple keys are set: **Groq > Gemini > Anthropic > heuristic**. Override with `LLM_PROVIDER=gemini` etc.

---

## Quick start (local)

```bash
# 1. Clone & enter the project
git clone https://github.com/Nipunchugh10/Flashcard-Engine.git
cd Flashcard-Engine

# 2. Create a virtual environment
python -m venv .venv
source .venv/bin/activate        # Linux/Mac
# .venv\Scripts\activate         # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure
cp .env.example .env
#    Open .env and paste your API key (see table above).
#    At minimum, set GROQ_API_KEY or GEMINI_API_KEY.
#    Also change SECRET_KEY to something random for production.

# 5. Run
./run.sh
#   or: uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 6. Open http://localhost:8000
#    Create an account and start uploading PDFs!
```

The SQLite DB and uploaded PDFs land under `./data/` and `./uploads/` respectively, both gitignored.

---

## Upload Limits

These keep the app stable on free-tier hosting. All configurable via environment variables.

| Limit | Default | Env variable |
|---|---|---|
| Max PDF file size | 10 MB | `MAX_PDF_SIZE_MB` |
| Max pages processed | **100** | `MAX_PDF_PAGES` |
| Max cards per PDF | **70** | `MAX_TOTAL_CARDS` |
| Cards per chunk | 8 | `MAX_CARDS_PER_CHUNK` |
| Chunk size (chars) | 3500 | `CHUNK_TARGET_CHARS` |

PDFs longer than 100 pages will have only the first 100 pages processed. Upload files are cleaned up after processing.

### Adaptive card scaling

The number of flashcards generated scales linearly with how many pages were actually processed — so a short handout doesn't get flooded with mediocre cards and a 100-page textbook hits the full 70-card ceiling:

| Pages in PDF | Cards generated (approx.) |
|---|---|
| 1–5 | 3–4 |
| 10 | 7 |
| 20 | 14 |
| 50 | 35 |
| 75 | 52 |
| 100+ | 70 (maximum) |

A secondary character-volume check prevents very sparse / image-heavy PDFs from inflating the count beyond what the actual text content justifies.

---

## How generation works

1. **Upload** — your PDF is saved and a deck is created instantly in "processing" state.
2. **Background thread** — PDF text extraction and LLM calls happen asynchronously, so you're never blocked.
3. **Adaptive budget** — the card target is calculated from the number of pages processed (linear 1–100 pages → 3–70 cards) and capped by actual text volume.
4. **Concurrent API calls** — up to 3 LLM calls run in parallel for speed.
5. **Polling** — the frontend checks status every 2 seconds. The spinner shows animated progress messages while waiting.
6. **Completion** — when cards are ready, the spinner switches to a green checkmark and the page auto-reloads to show your deck — no manual refresh needed. A "Taking too long? Click to refresh" link is always visible as a fallback.

If anything fails (bad PDF, rate limit, network issue), the deck shows a clear error message. Individual chunk failures fall back to the heuristic generator so you still get partial results. The polling timeout is 5 minutes (raised from 3) to accommodate large PDFs.

---

## Deploying to Render

1. Push this repo to GitHub.
2. Create a new **Web Service** on [render.com](https://render.com).
3. Connect your GitHub repo.
4. Set these environment variables in Render's dashboard:
   - `GROQ_API_KEY` (or `GEMINI_API_KEY`) — your LLM API key
   - `SECRET_KEY` — a random string for session security
   - `DATABASE_URL` — leave blank for SQLite, or use a Postgres URL
5. Set the **Build Command**: `pip install -r requirements.txt`
6. Set the **Start Command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
7. Deploy! The database tables and migrations are created automatically on startup.

> **Tip:** Render's free tier has 512 MB RAM. The background processing system and resource limits are specifically designed to work within this constraint.

---

## Stack

- **Python 3.12**, **FastAPI**, **SQLAlchemy 2.x**, **SQLite**
- **PyMuPDF** for PDF text extraction
- **OpenAI SDK** — drives both Groq and Gemini via their OpenAI-compatible endpoints
- **Anthropic SDK** — optional, for Claude
- **Jinja2 + Tailwind (CDN) + Alpine.js** for the frontend — server-rendered pages, AJAX only for study interactions
- **bcrypt + itsdangerous** for authentication & sessions

No build step, no bundler, no node_modules. One `uvicorn` process plus a SQLite file.

---

## Project layout

```
flashcard-engine/
├── app/
│   ├── main.py                    FastAPI entry
│   ├── config.py                  env + provider auto-detection
│   ├── database.py                SQLAlchemy session + migrations
│   ├── models.py                  User / Deck / Card / ReviewLog
│   ├── schemas.py                 Pydantic DTOs
│   ├── auth.py                    login / signup / session management
│   ├── stats.py                   deck aggregation
│   ├── pdf_processor.py           extraction + chunking (page-limited)
│   ├── flashcard_generator.py     Groq / Gemini / Anthropic / heuristic (concurrent)
│   ├── spaced_repetition.py       SM-2 algorithm
│   └── routes/
│       ├── pages.py               HTML pages
│       ├── auth.py                login / signup / logout
│       ├── api_decks.py           upload (async) / list / rename / delete / status
│       ├── api_cards.py           list / edit / delete
│       └── api_study.py           next-card / rate
├── templates/                     Jinja2 views
├── static/                        CSS + JS
├── data/                          SQLite DB (gitignored)
├── uploads/                       raw PDFs (gitignored)
├── smoke_test.py                  end-to-end tests
├── requirements.txt
├── .env.example
└── run.sh
```

---

## Key design decisions

**Background processing.** PDF upload returns instantly. Extraction and LLM calls happen in a background thread with its own DB session. The frontend polls a lightweight `/status` endpoint every 2 seconds. This prevents request timeouts on free-tier hosts like Render.

**Concurrent LLM calls.** Up to 3 chunk-level LLM calls run in parallel via `ThreadPoolExecutor`, cutting generation time by ~3×.

**SM-2, not Leitner.** Leitner is simpler but coarse: five boxes, fixed intervals. SM-2 adapts the interval per card based on your actual performance, so cards you genuinely know drift further apart while shaky ones keep coming back. I kept the classic SM-2 formula but used a friendlier 4-button rating (Again / Hard / Good / Easy) mapping to qualities 0/3/4/5, which is what Anki does — exposing raw 0–5 is hostile to users.

**Lapses reschedule in minutes, not days.** Vanilla SM-2 resets the interval to 1 day on a lapse. That's brutal if you genuinely forgot. I send lapses back in ~10 minutes (still within the session), matching how modern Anki behaves.

**Chunk before prompting, don't concatenate.** I split the PDF into ~3000-character paragraph-aligned chunks and call the LLM once per chunk. This keeps each prompt focused, lets the model cover more of the document, and stays well inside safe context windows. I also dedupe cards across chunks on a normalised-front basis.

**Pluggable LLM providers.** The app supports Groq, Gemini, and Anthropic behind a single interface. Since Groq and Gemini both expose OpenAI-compatible endpoints, the same `openai` SDK drives both — I just swap the base URL and model name. This means anyone running the project can use a free provider without code changes.

**Strict JSON output + defensive parsing.** The system prompt asks for a bare JSON array and forbids markdown fences. The parser strips fences anyway, searches for the array if stray prose slipped in, and tolerates per-item type coercion. If one chunk's output fails to parse, the others still succeed.

**Graceful degradation.** If any LLM call fails mid-upload (rate limit, network blip), that specific chunk quietly falls back to the heuristic generator. The rest of the upload continues. If no API key is set at all, the whole app runs on the heuristic — not as good, but never broken.

**Server-rendered, AJAX only where it matters.** Home, deck, and study pages all render server-side with Jinja2, so first paint is instant. The study page is the only one that talks JSON to the backend, because that's where latency actually matters.

**Keyboard-first study mode.** `Space` to flip, `1/2/3/4` to rate. Forcing users onto the trackpad for every card would kill the flow.

---

## API surface (JSON)

| Method | Path | Purpose |
|---|---|---|
| `POST`   | `/api/decks/upload`             | multipart PDF upload → creates deck (async) |
| `GET`    | `/api/decks/{id}/status`        | poll generation status |
| `GET`    | `/api/decks`                    | list decks with stats |
| `GET`    | `/api/decks/{id}`               | single deck + stats |
| `PATCH`  | `/api/decks/{id}`               | rename / set description |
| `DELETE` | `/api/decks/{id}`               | delete deck + all its cards |
| `GET`    | `/api/cards?deck_id=…`          | list cards (filter by status, search) |
| `PATCH`  | `/api/cards/{id}`               | edit front/back |
| `DELETE` | `/api/cards/{id}`               | delete card |
| `GET`    | `/api/study/{deck_id}/next`     | next due card for a session |
| `POST`   | `/api/study/cards/{id}/rate`    | rate a card (`again`/`hard`/`good`/`easy`) |
| `POST`   | `/signup`                       | create account |
| `POST`   | `/login`                        | log in |
| `GET`    | `/logout`                       | log out |

Auto-generated OpenAPI docs live at `/docs`.

---

## Security notes

- User accounts with bcrypt-hashed passwords and signed session cookies.
- All decks are per-user — you can only see and modify your own data.
- No API keys in the frontend. All provider keys are read server-side only.
- Upload size capped at 10 MB; PDFs are written to disk under a UUID, not the user-supplied filename, to prevent path tricks.
- Change `SECRET_KEY` in production — the default is insecure.
- SQLite is fine for small deployments; swap to Postgres by setting `DATABASE_URL`.

---

## What I'd do next with more time

- **Image-heavy PDFs.** If the PDF is a scan, we currently get nothing. Hooking up OCR (Tesseract or a vision LLM pass) would fix that.
- **Smarter session heuristics.** Prioritise overdue cards, mix in new cards based on a daily budget, surface "leech" cards that keep getting rated Again.
- **Export.** Let people download their deck as `.apkg` so it opens in Anki directly.
- **Per-user streaks and heatmap.** The review log table already has everything needed.
- **WebSocket progress.** Replace polling with real-time push updates during generation.

---

## License

MIT License

Copyright (c) 2026 Nipun Chugh

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
