---
title: Recall Flashcard Engine
emoji: 📇
colorFrom: purple
colorTo: indigo
sdk: docker
app_port: 7860
---

# Recall — The Flashcard Engine

Drop in a PDF. Get back a practice-ready deck with spaced repetition.

---

## ⚡ Live Demo

Deployed on [Hugging Face Spaces](https://huggingface.co/spaces). PDF processing runs in a containerized environment with dedicated RAM so it handles large files quickly.

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
| **Google Gemini** *(recommended)* | Free, no credit card | 15 req/min, 1,000 req/day, Gemini 1.5 Flash | [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey) |
| **Anthropic Claude** | Paid | — | [console.anthropic.com](https://console.anthropic.com) |

**Google Gemini is recommended** — generous free-tier limits, no credit card needed.

Priority order: **Gemini > Anthropic > heuristic**. Override with `LLM_PROVIDER=anthropic` etc.

---

## Quick start (local)

```bash
git clone https://github.com/Nipunchugh10/Flashcard-Engine.git
cd Flashcard-Engine
./run.sh
```

That's it. On first run `run.sh` creates a virtualenv in `.venv`, installs everything in
`requirements.txt`, copies `.env.example` to `.env` if you don't have one, and starts the
server on <http://localhost:8000>. Later runs skip straight to the server, and dependencies
are reinstalled automatically whenever `requirements.txt` changes.

Then open <http://localhost:8000>, create an account, and upload a PDF.

```bash
./run.sh            # start the dev server (auto-reload)
./run.sh test       # 19 end-to-end smoke tests
./run.sh security   # 45 adversarial security tests
PORT=3000 ./run.sh  # serve on a different port
```

**Add your API key.** Until you put a `GEMINI_API_KEY` in `.env`, the app runs in offline
heuristic mode and writes noticeably worse cards. Get a free key at
[Google AI Studio](https://aistudio.google.com/app/apikey). Set `SECRET_KEY` to a random
string too — if it changes between restarts, everyone gets logged out.

<details>
<summary>Prerequisites, and doing it manually</summary>

You need Python 3.10 or newer. On a fresh Debian/Ubuntu machine:

```bash
sudo apt install python3 python3-venv python3-pip
```

`python3-venv` is the one people miss — without it `run.sh` can't create the virtualenv.
Fedora: `sudo dnf install python3 python3-pip`. Arch: `sudo pacman -S python python-pip`.

If you'd rather drive it by hand:

```bash
python3 -m venv .venv
source .venv/bin/activate          # Linux/macOS
# .venv\Scripts\activate           # Windows
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

A virtualenv created on Windows will not run on Linux (its interpreter path points at
`C:\...`). `run.sh` detects that case and rebuilds `.venv` automatically, so a project
folder copied across machines just works.

</details>

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

The number of flashcards scales with **how much text the PDF actually contains**, not with its page count — roughly one card per 350 characters, capped at 8 cards per page and 70 per deck:

| Document | Cards generated (approx.) |
|---|---|
| 1 dense page | 7 |
| 2 pages | 15 |
| 5-page paper | 37 |
| 10+ pages | 70 (maximum) |
| 20-page scanned PDF, little real text | 3 |

Driving the budget from character volume means image-heavy or sparse PDFs fall to the 3-card floor on their own, with no special casing, while a dense handout earns a deck worth studying.

> **Changed:** page count used to be the primary signal (`pages / 100 × 70`). That starved short documents — a dense 5-page paper was capped at 4 cards and a 10-page chapter at 7, however much text was on the pages. Character volume is now primary and page count only supplies the per-page ceiling.

---

## How generation works

1. **Upload** — your PDF is saved and a deck is created instantly in "processing" state.
2. **Background thread** — PDF text extraction and LLM calls happen asynchronously, so you're never blocked.
3. **Adaptive budget** — the card target is calculated from total text volume (~1 card per 350 chars), capped at 8 cards per page and 70 per deck.
4. **Concurrent API calls** — up to 3 LLM calls run in parallel for speed.
5. **Polling** — the frontend checks status every 2 seconds. The spinner shows animated progress messages while waiting.
6. **Completion** — when cards are ready, the spinner switches to a green checkmark and the page auto-reloads to show your deck — no manual refresh needed. A "Taking too long? Click to refresh" link is always visible as a fallback.

If anything fails (bad PDF, rate limit, network issue), the deck shows a clear error message. Individual chunk failures fall back to the heuristic generator so you still get partial results. The polling timeout is 5 minutes (raised from 3) to accommodate large PDFs.

---

## Deploying to Hugging Face Spaces

1. Create a new **Space** on [huggingface.co](https://huggingface.co).
2. Set the **SDK** to **Docker** (leave the "Blank" template selected).
3. Go to the **Settings** tab of your Space and add these environment secrets:
   - `GEMINI_API_KEY` — your Gemini API key from Google AI Studio.
   - `LLM_PROVIDER` — set to `gemini`.
   - `DATABASE_URL` — your persistent PostgreSQL connection URL (e.g., from Neon.tech).
   - `SECRET_KEY` — a random string for session security.
4. Link your local project to Hugging Face and push:
   ```bash
   git remote add hf https://huggingface.co/spaces/YOUR_USERNAME/YOUR_SPACE_NAME
   git push hf main
   ```
5. Hugging Face will automatically build the container and deploy the app. Tables and migrations are initialized on startup.

---

## Stack

- **Python 3.11/3.12**, **FastAPI**, **SQLAlchemy 2.x**, **PostgreSQL / SQLite**
- **Docker** for containerized deployments
- **PyMuPDF** for PDF text extraction
- **OpenAI SDK** — drives Gemini via its OpenAI-compatible endpoint
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
│   ├── auth.py                    password hashing, session tokens, deps
│   ├── security.py                rate limiting + response headers
│   ├── stats.py                   deck aggregation
│   ├── pdf_processor.py           extraction + chunking (page-limited)
│   ├── flashcard_generator.py     Gemini / Anthropic / heuristic (concurrent)
│   ├── spaced_repetition.py       SM-2 algorithm
│   └── routes/
│       ├── pages.py               HTML pages
│       ├── auth.py                login / signup / logout
│       ├── api_decks.py           upload (async) / list / rename / delete / status
│       ├── api_cards.py           list / edit / delete
│       └── api_study.py           next-card / rate
├── templates/
│   ├── landing.html               public welcome page (anonymous visitors)
│   ├── base.html                  app shell (header + upload modal)
│   ├── auth_base.html             login / signup shell
│   ├── index.html                 deck dashboard
│   ├── deck.html                  card browser
│   ├── study.html                 review session
│   └── components/
│       ├── head.html              shared <head> (fonts, Tailwind config)
│       └── upload_modal.html      PDF drop zone
├── static/                        CSS + JS
├── data/                          SQLite DB (gitignored)
├── uploads/                       raw PDFs (gitignored)
├── smoke_test.py                  end-to-end tests
├── security_test.py               adversarial security tests
├── requirements.txt
├── .env.example
└── run.sh
```

---

## Key design decisions

**Background processing.** PDF upload returns instantly. Extraction and LLM calls happen in a background thread with its own DB session. The frontend polls a lightweight `/status` endpoint every 2 seconds. This prevents request timeouts on free-tier hosts like Render.

**Concurrent LLM calls.** Up to 3 chunk-level LLM calls run in parallel via `ThreadPoolExecutor`, cutting generation time by ~3×.

**Landing page at `/`.** Anonymous visitors get a public welcome page explaining what the app does; signed-in users get their deck dashboard at the same URL. Previously `/` redirected straight to `/login`, which gave first-time visitors no context.

**SM-2, not Leitner.** Leitner is simpler but coarse: five boxes, fixed intervals. SM-2 adapts the interval per card based on your actual performance, so cards you genuinely know drift further apart while shaky ones keep coming back. I kept the classic SM-2 formula but used a friendlier 4-button rating (Again / Hard / Good / Easy) mapping to qualities 0/3/4/5, which is what Anki does — exposing raw 0–5 is hostile to users.

**Lapses reschedule in minutes, not days.** Vanilla SM-2 resets the interval to 1 day on a lapse. That's brutal if you genuinely forgot. I send lapses back in ~10 minutes (still within the session), matching how modern Anki behaves.

**Chunk before prompting, don't concatenate.** I split the PDF into ~3000-character paragraph-aligned chunks and call the LLM once per chunk. This keeps each prompt focused, lets the model cover more of the document, and stays well inside safe context windows. I also dedupe cards across chunks on a normalised-front basis.

**Pluggable LLM providers.** The app supports Gemini and Anthropic behind a single interface. Since Gemini exposes an OpenAI-compatible endpoint, the `openai` SDK drives it — we just configure the base URL and model name. This means anyone running the project can use a free provider without code changes.

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
| `GET`    | `/`                             | landing page (anonymous) or deck dashboard (signed in) |
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
