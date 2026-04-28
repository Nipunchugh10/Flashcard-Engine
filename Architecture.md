# System Architecture & Pipeline

This document details the system design, data processing pipeline, and technology stack of **Recall — The Flashcard Engine**.

## 1. High-Level Architecture Overview

The system is built as a monolithic web application structured around a Python-based backend and a server-rendered frontend, designed to be lightweight, easy to deploy, and resilient under free-tier hosting constraints.

### Core Components
*   **Web Framework:** FastAPI handles all incoming HTTP requests, serves static files, and manages the routing for both HTML pages and JSON APIs.
*   **Database:** SQLite is used as the default relational database via SQLAlchemy, providing a lightweight, zero-configuration persistence layer. It can easily be swapped to PostgreSQL.
*   **Background Processing:** A thread-based background worker processes PDF extraction and LLM calls asynchronously to avoid blocking the main event loop and preventing request timeouts.
*   **Frontend Interface:** Server-side rendered HTML using Jinja2, styled with Tailwind CSS via CDN, and sprinkled with Alpine.js for lightweight client-side interactivity without a heavy JavaScript bundle.

---

## 2. Data Processing Pipeline

The core value proposition of the app is its automated PDF-to-Flashcard pipeline. Here is the step-by-step data flow:

### Step A: Ingestion & Upload
1.  **User Upload:** The user uploads a text-based PDF via the frontend.
2.  **File Validation:** The system validates the file size and type. The PDF is saved to the local file system (e.g., `./uploads/`) under a generated UUID to prevent path traversal attacks.
3.  **Deck Creation:** An initial database record for the Deck is created with a `processing` status, and an immediate response is returned to the client.

### Step B: Extraction & Chunking
1.  **Background Thread Activation:** A background task picks up the newly created Deck.
2.  **Text Extraction:** `PyMuPDF` reads the document text. The system limits processing to a configurable maximum number of pages (default: 50) to manage resource usage.
3.  **Intelligent Chunking:** The extracted text is split into paragraph-aligned chunks (targeting ~3000 characters). This ensures that each chunk sent to the LLM is contextually coherent and fits comfortably within token limits.

### Step C: AI Flashcard Generation
1.  **Concurrent Processing:** The chunks are processed via a `ThreadPoolExecutor` (up to 3 parallel requests) to minimize generation time.
2.  **LLM Routing:** The system selects the best available LLM provider (Groq > Gemini > Anthropic > Heuristic Fallback).
3.  **Prompting & Parsing:** A strict system prompt asks for JSON output containing concept questions, cloze deletions, and definitions. The response is parsed defensively, stripping markdown fences and gracefully handling per-item coercion.
4.  **Graceful Degradation:** If an LLM call fails for a specific chunk (e.g., rate limits), that chunk falls back to a regex-based heuristic generator, ensuring partial success instead of a total failure.

### Step D: Spaced Repetition (SM-2)
1.  **Study Session:** Cards are presented one at a time. The user self-assesses their recall using a 4-button system (Again, Hard, Good, Easy), mapping to qualities 0, 3, 4, and 5.
2.  **Algorithm Execution:** A modified SM-2 algorithm calculates the next review interval.
3.  **Lapse Handling:** Unlike vanilla SM-2 which resets intervals to 1 day on failure, lapses are rescheduled within minutes (e.g., ~10 minutes) for better within-session reinforcement.

---

## 3. Backend Architecture

The backend follows a modular monolith structure within the `app/` directory.

### Key Libraries
*   **FastAPI:** High-performance web framework.
*   **SQLAlchemy 2.x:** ORM for database interactions.
*   **PyMuPDF:** Efficient PDF parsing and text extraction.
*   **OpenAI SDK / Anthropic SDK:** Used to interface with LLM providers. (The OpenAI SDK is used for both Groq and Gemini via their OpenAI-compatible endpoints).
*   **bcrypt & itsdangerous:** Secure password hashing and signed session cookie management.

### API Endpoints
The backend exposes JSON APIs under `/api/` for client-side interactions, alongside standard HTML routes.

**Deck Management:**
*   `POST /api/decks/upload` - Handles multipart PDF uploads and triggers async generation.
*   `GET /api/decks/{id}/status` - Polled by the frontend to get real-time generation progress.
*   `GET /api/decks` - Lists all decks owned by the user, including calculated stats.
*   `GET /api/decks/{id}` - Retrieves a single deck's details.
*   `PATCH /api/decks/{id}` - Renames or updates a deck description.
*   `DELETE /api/decks/{id}` - Deletes a deck and its associated cards.

**Card Management:**
*   `GET /api/cards?deck_id=...` - Retrieves cards with filtering and search capabilities.
*   `PATCH /api/cards/{id}` - Edits the front or back of a card.
*   `DELETE /api/cards/{id}` - Deletes a specific card.

**Study Engine:**
*   `GET /api/study/{deck_id}/next` - Calculates and returns the next due card based on the SM-2 algorithm.
*   `POST /api/study/cards/{id}/rate` - Submits a rating (again/hard/good/easy) to update the card's spaced repetition state.

**Authentication:**
*   `POST /signup` - Registers a new user.
*   `POST /login` - Authenticates a user and sets a session cookie.
*   `GET /logout` - Clears the session.

---

## 4. Frontend Architecture

The frontend is designed for rapid delivery and minimal client-side overhead.

### Key Libraries
*   **Jinja2:** Server-side templating engine for generating HTML views directly from the backend. This ensures instantaneous first paints.
*   **Tailwind CSS (via CDN):** Utility-first styling framework used for rapid UI development and responsive design without needing a build step.
*   **Alpine.js:** A rugged, minimal framework for composing JavaScript behavior directly in HTML markup (used for modals, dropdowns, and simple state).

### Frontend Pipeline & Behaviors
*   **Server-Rendered Pages:** Pages like the dashboard, deck list, and settings are rendered completely on the server.
*   **AJAX Polling:** During PDF generation, the frontend uses simple JavaScript `setInterval` logic to poll `/api/decks/{id}/status` every 2 seconds, updating a progress bar until completion or failure.
*   **Study Mode Interactivity:** The study interface relies on AJAX to fetch the next card and submit ratings to provide a seamless, non-reloading experience.
*   **Keyboard Accessibility:** Custom JavaScript listeners capture keyboard events (e.g., `Space` to flip, `1-4` to rate) to optimize the study flow without requiring trackpad interaction.
