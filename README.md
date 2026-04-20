# Recall — The Flashcard Engine

Drop in a PDF. Get back a practice-ready deck with spaced repetition. Built for the AI Builder Build Challenge (Problem 1).

---

## What it does

1. **Ingest.** You upload a text-based PDF (a chapter, a set of lecture notes, a paper).
2. **Generate.** The app extracts the text, splits it into paragraph-coherent chunks, and asks an LLM to write a mix of concept questions, definitions, cloze deletions, and application/example cards.
3. **Study.** A focused session UI shows one card at a time. You flip the card, rate yourself (Again / Hard / Good / Easy), and the SM-2 algorithm decides when each card should next appear.
4. **Track.** Per-deck stats (total, due, new, review, mastered) and per-card state visible in a browsable, searchable card list.

---

## LLM provider — pick any one (all free options available)

The app auto-detects which provider to use based on which key you set in `.env`. You do **not** need a paid API to run this.

| Provider | Cost | Free tier | Where to get a key |
|---|---|---|---|
| **Groq** *(recommended)* | Free, no credit card | 30 req/min, 14,400 req/day, Llama 3.3 70B | [console.groq.com](https://console.groq.com) |
| **Google Gemini** | Free, no credit card | 15 req/min, 1,000 req/day, Gemini 2.5 Flash | [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey) |
| **Anthropic Claude** | Paid | — | [console.anthropic.com](https://console.anthropic.com) |
| **None** (heuristic) | Free, offline | regex-based card generation | — |

Priority order when multiple keys are set: **Groq > Gemini > Anthropic > heuristic**. Override with `LLM_PROVIDER=gemini` etc.

Groq is recommended because it has the highest request limits and is the fastest for this workload (PDF uploads feel near-instant).

---

## Stack

- **Python 3.12**, **FastAPI**, **SQLAlchemy 2.x**, **SQLite**
- **PyMuPDF** for PDF text extraction
- **OpenAI SDK** — drives both Groq and Gemini via their OpenAI-compatible endpoints
- **Anthropic SDK** — optional, for Claude
- **Jinja2 + Tailwind (CDN) + Alpine.js** for the frontend — server-rendered pages, AJAX only for study interactions

No build step, no bundler, no node_modules. One `uvicorn` process plus a SQLite file.

---

## Quick start (local)

```bash
# 1. Clone, enter the project, set up a virtualenv
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
#    Open .env and paste ONE of: GROQ_API_KEY, GEMINI_API_KEY, or ANTHROPIC_API_KEY.
#    Without any key, the app still runs using the regex-based heuristic fallback.

# 3. Run
./run.sh
#   or: uvicorn app.main:app --reload

# 4. Open http://localhost:8000
```

The SQLite DB and uploaded PDFs land under `./data/` and `./uploads/` respectively, both gitignored.

---

## Getting a Groq key (recommended path, takes 2 minutes)

1. Go to [console.groq.com](https://console.groq.com) and sign in with email or Google (no credit card).
2. Click **API Keys** in the sidebar → **Create API Key** → copy the key.
3. Paste it into `.env` as `GROQ_API_KEY=gsk_...`
4. Run `./run.sh`. You should see `Provider=groq` in the startup log.

---

## Project layout

```
flashcard-engine/
├── app/
│   ├── main.py                    FastAPI entry
│   ├── config.py                  env + provider auto-detection
│   ├── database.py                SQLAlchemy session
│   ├── models.py                  Deck / Card / ReviewLog
│   ├── schemas.py                 Pydantic DTOs
│   ├── stats.py                   deck aggregation
│   ├── pdf_processor.py           extraction + chunking
│   ├── flashcard_generator.py     Groq / Gemini / Anthropic / heuristic
│   ├── spaced_repetition.py       SM-2 algorithm
│   └── routes/
│       ├── pages.py               HTML pages
│       ├── api_decks.py           upload / list / rename / delete
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

**SM-2, not Leitner.** Leitner is simpler but coarse: five boxes, fixed intervals. SM-2 adapts the interval per card based on your actual performance, so cards you genuinely know drift further apart while shaky ones keep coming back. I kept the classic SM-2 formula but used a friendlier 4-button rating (Again / Hard / Good / Easy) mapping to qualities 0/3/4/5, which is what Anki does — exposing raw 0–5 is hostile to users.

**Lapses reschedule in minutes, not days.** Vanilla SM-2 resets the interval to 1 day on a lapse. That's brutal if you genuinely forgot. I send lapses back in ~10 minutes (still within the session), matching how modern Anki behaves.

**Chunk before prompting, don't concatenate.** I split the PDF into ~3500-character paragraph-aligned chunks and call the LLM once per chunk. This keeps each prompt focused, lets the model cover more of the document, and stays well inside safe context windows. I also dedupe cards across chunks on a normalised-front basis.

**Pluggable LLM providers.** The app supports Groq, Gemini, and Anthropic behind a single interface. Since Groq and Gemini both expose OpenAI-compatible endpoints, the same `openai` SDK drives both — I just swap the base URL and model name. This means anyone running the project can use a free provider without code changes.

**Strict JSON output + defensive parsing.** The system prompt asks for a bare JSON array and forbids markdown fences. The parser strips fences anyway, searches for the array if stray prose slipped in, and tolerates per-item type coercion. If one chunk's output fails to parse, the others still succeed.

**Graceful degradation.** If any LLM call fails mid-upload (rate limit, network blip), that specific chunk quietly falls back to the heuristic generator. The rest of the upload continues. If no API key is set at all, the whole app runs on the heuristic — not as good, but never broken.

**Server-rendered, AJAX only where it matters.** Home, deck, and study pages all render server-side with Jinja2, so first paint is instant. The study page is the only one that talks JSON to the backend, because that's where latency actually matters.

**Keyboard-first study mode.** `Space` to flip, `1/2/3/4` to rate. Forcing users onto the trackpad for every card would kill the flow.

---

## API surface (JSON)

| Method | Path | Purpose |
|---|---|---|
| `POST`   | `/api/decks/upload`             | multipart PDF upload; returns a new deck |
| `GET`    | `/api/decks`                    | list decks with stats |
| `GET`    | `/api/decks/{id}`               | single deck + stats |
| `PATCH`  | `/api/decks/{id}`               | rename / set description |
| `DELETE` | `/api/decks/{id}`               | delete deck + all its cards |
| `GET`    | `/api/cards?deck_id=…`          | list cards (filter by status, search) |
| `PATCH`  | `/api/cards/{id}`               | edit front/back |
| `DELETE` | `/api/cards/{id}`               | delete card |
| `GET`    | `/api/study/{deck_id}/next`     | next due card for a session |
| `POST`   | `/api/study/cards/{id}/rate`    | rate a card (`again`/`hard`/`good`/`easy`) |

Auto-generated OpenAPI docs live at `/docs`.

---

## What I'd do next with more time

- **User accounts.** Right now the DB is single-tenant. Adding auth + a `user_id` FK on decks is a small change but out of scope for the build window.
- **Image-heavy PDFs.** If the PDF is a scan, we currently get nothing. Hooking up OCR (Tesseract or a vision LLM pass) would fix that.
- **Smarter session heuristics.** Prioritise overdue cards, mix in new cards based on a daily budget, surface "leech" cards that keep getting rated Again.
- **Export.** Let people download their deck as `.apkg` so it opens in Anki directly.
- **Per-user streaks and heatmap.** The review log table already has everything needed.

---

## Security notes

- No API keys in the frontend. All provider keys are read server-side only.
- Upload size capped at 25 MB; PDFs are written to disk under a UUID, not the user-supplied filename, to prevent path tricks.
- SQLite is fine for small deployments; swap to Postgres by setting `DATABASE_URL`.

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
