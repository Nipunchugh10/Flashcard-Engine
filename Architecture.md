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
2.  **Text Extraction:** `PyMuPDF` reads the document text. The system limits processing to a configurable maximum number of pages (default: **100**) to manage resource usage. PDFs longer than 100 pages have only their first 100 pages processed; the total page count is recorded separately.
3.  **Intelligent Chunking:** The extracted text is split into paragraph-aligned chunks (targeting ~3500 characters). This ensures that each chunk sent to the LLM is contextually coherent and fits comfortably within token limits.
4.  **Adaptive Card Budget:** Before any LLM call is made, the total card budget is calculated from the number of pages actually read (linear scale: 1–100 pages → 3–70 cards). A secondary character-volume check acts as a safety cap to avoid over-generating cards from image-heavy or sparse PDFs.

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
*   **AJAX Polling:** During PDF generation, the frontend uses `setInterval` to poll `/api/decks/{id}/status` every 2 seconds. When the backend reports `status=ready`, the spinner transitions to a green checkmark and `window.location.reload()` fires automatically — no manual page refresh needed. A manual "Taking too long? Click to refresh" button is always visible as a fallback. The polling timeout is 5 minutes (150 ticks × 2 s) to handle large PDFs.
*   **Study Mode Interactivity:** The study interface relies on AJAX to fetch the next card and submit ratings to provide a seamless, non-reloading experience.
*   **Keyboard Accessibility:** Custom JavaScript listeners capture keyboard events (e.g., `Space` to flip, `1-4` to rate) to optimize the study flow without requiring trackpad interaction.

---

## 5. Object-Oriented Programming (OOP) Concepts in the Backend

This section documents every OOP concept that appears in the backend codebase (`app/` directory), with the exact file, the construct used, and a concrete explanation of *how* it is applied.

---

### 5.1 Classes

A **class** is a blueprint that bundles data (attributes) and behaviour (methods) into a single unit.

#### `app/models.py` — ORM Model Classes

Four classes (`User`, `Deck`, `Card`, `ReviewLog`) define the entire database schema. Each class maps directly to a database table and owns the columns (attributes) of that table.

```python
class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, ...)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(...)
    decks: Mapped[list["Deck"]] = relationship(...)
```

Each class is a **self-contained unit** — all data about a user (columns, relationships, constraints) lives inside `User`. The same pattern holds for `Deck`, `Card`, and `ReviewLog`.

#### `app/schemas.py` — Pydantic Schema Classes

Five classes (`CardOut`, `DeckStats`, `DeckOut`, `RateCardIn`, `RenameDeckIn`, `CardEditIn`) act as **Data Transfer Objects (DTOs)** — typed contracts for what the API accepts and returns. They separate the internal database representation from the external API shape.

```python
class CardOut(BaseModel):
    id: int
    deck_id: int
    front: str
    back: str
    status: str
    interval_days: float
    ease_factor: float
    ...
```

#### `app/database.py` — Base Registry Class

```python
class Base(DeclarativeBase):
    pass
```

`Base` is an empty class whose only purpose is to act as the **SQLAlchemy model registry**. All ORM model classes inherit from it, which triggers SQLAlchemy's metaclass machinery to register the table mappings.

#### `app/routes/api_decks.py` — Inline Response Schema Class

```python
class DeckStatusOut(BaseModel):
    generation_status: str
    generation_error: str | None = None
    stats: DeckStats
```

A small class defined *inside a route file* to describe the exact shape of the status-polling response. This keeps the contract co-located with the endpoint that uses it.

---

### 5.2 Inheritance

**Inheritance** allows a class to acquire attributes and behaviour from a parent class, enabling code reuse and establishing an "is-a" relationship.

#### `app/models.py` — All ORM Models Inherit from `Base`

```python
from .database import Base

class User(Base): ...
class Deck(Base): ...
class Card(Base): ...
class ReviewLog(Base): ...
```

All four model classes inherit from `Base` (which itself inherits from `DeclarativeBase`). This inheritance does two things:
1. It makes SQLAlchemy aware of the class as a table-mapped model.
2. It grants each model all the ORM machinery (session attachment, query helpers, identity map, etc.) without writing any of that code manually.

The chain is: `User → Base → DeclarativeBase` (SQLAlchemy's internal class).

#### `app/schemas.py` — All Schemas Inherit from Pydantic's `BaseModel`

```python
from pydantic import BaseModel

class CardOut(BaseModel): ...
class DeckStats(BaseModel): ...
class DeckOut(BaseModel): ...
class RateCardIn(BaseModel): ...
class RenameDeckIn(BaseModel): ...
class CardEditIn(BaseModel): ...
```

Every schema inherits from Pydantic's `BaseModel`, which provides:
- Automatic field validation on construction
- `.model_dump()` / `.model_validate()` serialisation methods
- Type coercion and error messages

Without this inheritance, each schema would need to reimplement all validation logic from scratch.

#### `app/database.py` — `Base` Inherits from `DeclarativeBase`

```python
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass
```

`Base` is a thin subclass of SQLAlchemy's `DeclarativeBase`. This is the **foundation of the inheritance chain** that all models rely on.

---

### 5.3 Encapsulation

**Encapsulation** means hiding internal implementation details and exposing only what is necessary. In Python this is achieved through naming conventions (`_name` for private) and module boundaries.

#### `app/auth.py` — Private Signer Object

```python
_signer = URLSafeTimedSerializer(config.SECRET_KEY)
```

The `_signer` is module-level with a leading underscore — it is not exported and cannot be used outside `auth.py`. All session operations are performed through the public functions (`create_session_token`, `decode_session_token`, `set_session_cookie`), which act as the **controlled interface** to the signer.

#### `app/auth.py` — Private Login Redirect Helper

```python
def _login_redirect():
    from fastapi import HTTPException
    raise HTTPException(status_code=401, detail="Not authenticated")
```

`_login_redirect` is a private function. The public dependencies (`get_current_user`, `get_optional_user`) call it internally. External code never needs to know *how* a redirect is triggered — only that it happens.

#### `app/flashcard_generator.py` — Private Provider Functions

```python
def _call_openai_compatible(...): ...   # private shared implementation
def _call_groq(...): ...                # private provider wrapper
def _call_gemini(...): ...              # private provider wrapper
def _call_anthropic(...): ...           # private provider wrapper
def _heuristic_cards(...): ...          # private fallback
def _parse_cards(...): ...              # private parser
def _normalise(...): ...                # private string helper
```

All of these are prefixed with `_`, hiding the internal wiring of the LLM pipeline. The only public surface is `generate_cards_for_chunks(...)`, which is the **single entry point** the rest of the codebase uses.

#### `app/pdf_processor.py` — Private Text-Processing Helpers

```python
def _clean_page(text): ...
def _looks_like_header_footer(line, page_no): ...
def _chunk_text(text): ...
```

All text extraction internals are private. External code (e.g. `api_decks.py`) only calls the public `extract_pdf(path)` function and receives a `PDFExtract` object — it never needs to know about paragraph chunking, header/footer filtering, or whitespace normalisation.

#### `app/database.py` — Private Migration Helper

```python
def _apply_migrations() -> None: ...
```

Schema migrations are a private concern of `database.py`. The public `init_db()` function calls `_apply_migrations()` internally; route code never touches it directly.

#### `app/routes/api_decks.py` — Private Background Worker and Helpers

```python
def _process_deck_background(deck_id, pdf_path): ...
def _derive_deck_name(filename): ...
def _safe_unlink(p): ...
def _get_user_deck(deck_id, user, db): ...
def _serialize_deck(deck, db): ...
```

These five private helpers encapsulate the messy internals of upload handling: background thread management, safe file deletion, ownership verification, and serialisation. The public `upload_pdf` endpoint is clean and expressive precisely because these details are hidden.

---

### 5.4 Abstraction

**Abstraction** means exposing a simplified interface that hides complexity. You interact with *what* something does, not *how* it does it.

#### `app/flashcard_generator.py` — Provider Abstraction via Dispatch Table

```python
_PROVIDER_DISPATCH = {
    "groq":      _call_groq,
    "gemini":    _call_gemini,
    "anthropic": _call_anthropic,
}
```

The entire complexity of three different LLM SDKs (OpenAI SDK for Groq/Gemini, Anthropic SDK for Claude) is hidden behind a single dictionary lookup. The `generate_cards_for_chunks` function just calls `llm_fn(chunk, per_chunk)` — it does not know or care which SDK is executing.

```python
llm_fn = _PROVIDER_DISPATCH.get(provider)  # None for 'heuristic'
...
cards = llm_fn(chunk, per_chunk)
```

This is **behavioural abstraction**: the caller uses a uniform interface regardless of which concrete provider is selected.

#### `app/flashcard_generator.py` — Shared OpenAI-Compatible Implementation

```python
def _call_openai_compatible(chunk, max_cards, *, api_key, base_url, model, provider_name):
    """Shared implementation for Groq and Gemini (both OpenAI-compatible)."""
```

Both Groq and Gemini expose identical OpenAI-compatible APIs. Instead of duplicating code, `_call_groq` and `_call_gemini` are thin wrappers that delegate to `_call_openai_compatible`, passing only what differs (URL, key, model name). The shared function abstracts away the HTTP call, response parsing, and logging.

#### `app/database.py` — `get_db` Dependency Abstraction

```python
def get_db():
    """FastAPI dependency that yields a DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

Every route that needs a database session declares `db: Session = Depends(get_db)`. The route function never sees `SessionLocal`, connection pooling, or the `finally` cleanup — it simply receives a ready-to-use `db` object. This is the **Dependency Injection** pattern, which is itself a form of abstraction.

#### `app/config.py` — Provider Selection Abstraction

```python
def active_provider() -> str:
    if LLM_PROVIDER_OVERRIDE: return LLM_PROVIDER_OVERRIDE
    if GROQ_API_KEY:           return "groq"
    if GEMINI_API_KEY:         return "gemini"
    if ANTHROPIC_API_KEY:      return "anthropic"
    return "heuristic"
```

The rest of the codebase calls `config.active_provider()` and gets a plain string like `"groq"`. The priority logic, env-var reading, and fallback chain are fully abstracted inside `config.py`.

#### `app/spaced_repetition.py` — Algorithm Abstraction

```python
def apply_rating(*, rating, ease_factor, interval_days, repetitions, lapses, reviews_count) -> SRSState:
```

The SM-2 algorithm (ease factor adjustment, interval calculation, lapse handling, status derivation) is fully contained inside this one function. Route code in `api_study.py` calls it with six keyword arguments and receives a `SRSState` dataclass — it never sees a single formula.

---

### 5.5 Polymorphism

**Polymorphism** means that different objects can be treated through the same interface, with each providing its own implementation.

#### `app/flashcard_generator.py` — Callable Polymorphism via Dispatch Table

```python
_PROVIDER_DISPATCH = {
    "groq":      _call_groq,       # uses openai SDK, Groq base URL
    "gemini":    _call_gemini,     # uses openai SDK, Google base URL
    "anthropic": _call_anthropic,  # uses anthropic SDK
}
```

Each function in the dispatch table has the **same signature** — `(chunk: str, max_cards: int) -> list[GeneratedCard]` — but a completely different internal implementation. The loop body `llm_fn(chunk, per_chunk)` is identical regardless of which provider is active. This is **function-level polymorphism** (also called duck typing in Python).

#### `app/flashcard_generator.py` — Heuristic vs LLM Polymorphism

```python
if llm_fn is None:
    return _generate_sequential(chunks, _heuristic_cards, per_chunk, ...)
...
cards = llm_fn(chunk, per_chunk)
# or on failure:
cards = _heuristic_cards(chunk, per_chunk)
```

`_heuristic_cards` and any `llm_fn` are interchangeable — both accept `(chunk, max_cards)` and return `list[GeneratedCard]`. The caller does not distinguish between them. This is classic **substitution polymorphism**.

#### `app/schemas.py` — Pydantic's `model_dump` / `model_validate` Polymorphism

```python
CardOut.model_validate(card).model_dump(mode="json")  # api_study.py
DeckStats(...).model_dump()                            # api_study.py
```

Every schema class inherits `model_validate` and `model_dump` from `BaseModel`, but each produces different output shapes. The calling code uses the same method name on any schema, and Pydantic dispatches to the correct field set — polymorphic serialisation.

---

### 5.6 Composition

**Composition** is the "has-a" relationship — objects are built by embedding other objects as attributes rather than inheriting from them.

#### `app/schemas.py` — `DeckOut` Composes `DeckStats`

```python
class DeckOut(BaseModel):
    ...
    stats: DeckStats   # <-- DeckOut "has a" DeckStats
```

`DeckOut` embeds a `DeckStats` instance. The deck's stat breakdown (total, new, learning, review, mastered, due_now) is itself a typed object, not a flat set of fields on `DeckOut`. This is direct object composition.

#### `app/models.py` — `Deck` Composes `Card` Objects (via Relationship)

```python
class Deck(Base):
    cards: Mapped[list["Card"]] = relationship(
        "Card", back_populates="deck", cascade="all, delete-orphan"
    )
```

A `Deck` instance contains a list of `Card` instances. This is a **one-to-many composition**: a deck is composed of its cards, and the `cascade="all, delete-orphan"` rule means cards cannot exist without their deck — a hallmark of true composition.

#### `app/models.py` — `User` Composes `Deck` Objects

```python
class User(Base):
    decks: Mapped[list["Deck"]] = relationship(
        "Deck", back_populates="owner", cascade="all, delete-orphan"
    )
```

A `User` is composed of its `Deck` objects. Again, `cascade="all, delete-orphan"` enforces that decks are part of the user — they are deleted when the user is deleted.

#### `app/models.py` — `Card` Composes `ReviewLog` Objects

```python
class Card(Base):
    reviews: Mapped[list["ReviewLog"]] = relationship(
        "ReviewLog", back_populates="card", cascade="all, delete-orphan"
    )
```

Each `Card` is composed of its `ReviewLog` history. The full review timeline of a card lives inside the card object.

#### `app/routes/api_decks.py` — `DeckStatusOut` Composes `DeckStats`

```python
class DeckStatusOut(BaseModel):
    generation_status: str
    generation_error: str | None = None
    stats: DeckStats    # <-- composed object
```

The lightweight polling response reuses the `DeckStats` object by composition rather than duplicating its six integer fields.

---

### 5.7 Dataclasses

Python's `@dataclass` decorator auto-generates `__init__`, `__repr__`, and `__eq__` from field annotations, making the class a pure data holder with minimal boilerplate.

#### `app/flashcard_generator.py` — `GeneratedCard`

```python
from dataclasses import dataclass, field

@dataclass
class GeneratedCard:
    front: str
    back: str
    card_type: str = "qa"
    source_excerpt: Optional[str] = None
    tags: list[str] = field(default_factory=list)
```

`GeneratedCard` is the internal data object that flows through the entire generation pipeline: created in `_parse_cards` / `_heuristic_cards`, accumulated in `generate_cards_for_chunks`, and finally consumed in `_process_deck_background` to create `models.Card` rows. The `field(default_factory=list)` is used for the mutable `tags` list to avoid the shared-default-list bug.

#### `app/pdf_processor.py` — `PDFExtract`

```python
@dataclass
class PDFExtract:
    text: str
    page_count: int   # total pages in the PDF (including unprocessed ones)
    pages_read: int   # pages actually extracted (capped at MAX_PDF_PAGES = 100)
    chunks: list[str]
```

`PDFExtract` is the return value of `extract_pdf()`. It bundles four related pieces of information into a single typed object. `page_count` records the original PDF length; `pages_read` is the actual number of pages processed (at most 100). The background worker in `api_decks.py` passes `extract.pages_read` to `generate_cards_for_chunks()` so the adaptive budget can scale the card count proportionally.

#### `app/spaced_repetition.py` — `SRSState`

```python
@dataclass
class SRSState:
    ease_factor: float
    interval_days: float
    repetitions: int
    lapses: int
    next_review: datetime
    status: str
```

`SRSState` carries the complete result of one SM-2 review computation. The `apply_rating` function constructs and returns one; the `rate_card` route unpacks each field onto the `Card` model. Using a dataclass instead of returning a tuple makes the meaning of each value unambiguous at the call site.

---

### 5.8 Inner Classes (Nested Classes)

An **inner class** is a class defined *inside* another class. It is often used for configuration or meta-information that belongs conceptually to the outer class.

#### `app/schemas.py` — `Config` Inner Classes

```python
class CardOut(BaseModel):
    ...
    class Config:
        from_attributes = True   # allow ORM model → Pydantic conversion

class DeckOut(BaseModel):
    ...
    class Config:
        from_attributes = True
```

The `Config` inner class is Pydantic v1-style configuration. `from_attributes = True` tells Pydantic to read values from ORM model *attributes* (e.g. `card.front`) rather than dictionary keys. Without this setting, passing a SQLAlchemy `Card` object to `CardOut.model_validate(card)` would fail. The inner class keeps this config tightly scoped to the schema that needs it.

---

### 5.9 Module-Level Object Instantiation (Object Creation Pattern)

This is where a class is instantiated **once at module load time**, producing a shared singleton-like object used throughout the application.

#### `app/auth.py` — Signer Singleton

```python
_signer = URLSafeTimedSerializer(config.SECRET_KEY)
```

`URLSafeTimedSerializer` is a class from the `itsdangerous` library. One instance is created when `auth.py` is first imported, and every call to `create_session_token` / `decode_session_token` reuses this single object. This avoids re-initialising the HMAC key on every request.

#### `app/database.py` — Engine and Session Factory

```python
engine = create_engine(DATABASE_URL, ...)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
```

`create_engine` and `sessionmaker` both return class-like factory objects. `SessionLocal` is an object that, when called (`SessionLocal()`), produces a new `Session` instance. The engine itself is a connection-pool manager object — a class instance that holds active database connections.

#### `app/routes/api_decks.py` and `app/routes/pages.py` — APIRouter Instances

```python
router = APIRouter(prefix="/api/decks", tags=["decks"])
```

`APIRouter` is a FastAPI class. Each route file instantiates its own `router` object and decorates route functions onto it. `main.py` then calls `app.include_router(router)` to attach all routes. This is **object-based route grouping**.

---

### 5.10 Summary Table

| OOP Concept | Where Used | Example |
|---|---|---|
| **Class** | `models.py`, `schemas.py`, `database.py`, `api_decks.py` | `User`, `Card`, `CardOut`, `Base`, `DeckStatusOut` |
| **Inheritance** | `models.py` (→ `Base`), `schemas.py` (→ `BaseModel`) | `class User(Base)`, `class CardOut(BaseModel)` |
| **Encapsulation** | `auth.py`, `flashcard_generator.py`, `pdf_processor.py`, `database.py`, `api_decks.py` | `_signer`, `_call_groq`, `_parse_cards`, `_apply_migrations`, `_process_deck_background` |
| **Abstraction** | `flashcard_generator.py`, `config.py`, `database.py`, `spaced_repetition.py` | `generate_cards_for_chunks`, `active_provider()`, `get_db()`, `apply_rating()` |
| **Polymorphism** | `flashcard_generator.py`, `schemas.py` | `_PROVIDER_DISPATCH`, `_heuristic_cards` / `llm_fn`, `model_dump()` |
| **Composition** | `models.py`, `schemas.py`, `api_decks.py` | `Deck.cards`, `User.decks`, `DeckOut.stats`, `Card.reviews` |
| **Dataclass** | `flashcard_generator.py`, `pdf_processor.py`, `spaced_repetition.py` | `GeneratedCard`, `PDFExtract`, `SRSState` |
| **Inner Class** | `schemas.py` | `CardOut.Config`, `DeckOut.Config` |
| **Object Instantiation** | `auth.py`, `database.py`, `routes/*.py` | `_signer`, `engine`, `SessionLocal`, `router` |

---

## 6. Data Structures & Algorithms (DSA) Concepts in the Codebase

This section documents every DSA concept that appears in the codebase, with the exact file, the construct used, and a concrete explanation of *how* it is applied.

---

### 6.1 Hash Tables (Dictionaries)

A **hash table** (Python `dict`) provides O(1) average-case lookup, insertion, and deletion by mapping keys to values through a hash function.

#### `app/flashcard_generator.py` — Provider Dispatch Table

```python
_PROVIDER_DISPATCH = {
    "groq":      _call_groq,
    "gemini":    _call_gemini,
    "anthropic": _call_anthropic,
}
```

The dispatch table maps provider name strings to callable functions. At runtime, `_PROVIDER_DISPATCH.get(provider)` performs an **O(1) lookup** to select the correct LLM handler — eliminating the need for a chain of `if/elif` checks. This is the classic **strategy pattern** implemented through a hash table.

#### `app/spaced_repetition.py` — Rating-to-Quality Mapping

```python
RATING_TO_QUALITY: dict[str, int] = {
    "again": 0,
    "hard": 3,
    "good": 4,
    "easy": 5,
}
```

The four-button rating system maps human-readable strings to SM-2 quality scores via a dictionary. The `apply_rating` function does `q = RATING_TO_QUALITY[rating]` — a constant-time lookup that converts the user's input into an integer suitable for the mathematical formula.

#### `app/stats.py` — Status Counting via Dictionary Comprehension

```python
rows = db.execute(
    select(models.Card.status, func.count(models.Card.id))
    .where(models.Card.deck_id == deck_id)
    .group_by(models.Card.status)
).all()

counts = {status: count for status, count in rows}
total = sum(counts.values())
```

The SQL result (status-count pairs) is loaded into a dictionary for O(1) access when building the `DeckStats` object. Each `.get("new", 0)`, `.get("learning", 0)` etc. is a constant-time hash lookup, making the overall stat computation O(n) in the number of distinct statuses (which is fixed at 4).

#### `app/flashcard_generator.py` — Concurrent Results Accumulation

```python
results: dict[int, list[GeneratedCard]] = {}
for future in as_completed(futures):
    idx, cards = future.result()
    results[idx] = cards
```

When LLM calls complete out-of-order (due to concurrency), their results are stored in a dictionary keyed by chunk index. Later, `sorted(results.keys())` restores the original order. The dictionary serves as a **sparse array** — not all indices may be present if some calls fail, but O(1) insertion and lookup are guaranteed.

---

### 6.2 Arrays / Dynamic Lists

A **dynamic list** (Python `list`) provides O(1) amortised append, O(1) random access by index, and O(n) insertion/deletion at arbitrary positions.

#### `app/pdf_processor.py` — Buffer-Based Chunk Assembly

```python
def _chunk_text(text: str) -> list[str]:
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    buf: list[str] = []
    buf_len = 0

    def flush() -> None:
        nonlocal buf, buf_len
        if buf:
            chunks.append("\n\n".join(buf))
            buf = []
            buf_len = 0

    for para in paragraphs:
        if buf_len + len(para) + 2 > CHUNK_TARGET_CHARS and buf_len >= MIN_CHUNK_CHARS:
            flush()
        buf.append(para)
        buf_len += len(para) + 2

    flush()
```

Two lists work in tandem: `buf` is a temporary **accumulator buffer** that collects paragraphs until the size threshold is hit, and `chunks` is the **output list** that receives flushed buffers. This is a classic **linear scan with buffered output** — the entire algorithm runs in O(n) where n is the total text length.

#### `app/flashcard_generator.py` — Linear Card Collection with Early Termination

```python
all_cards: list[GeneratedCard] = []

for idx in sorted(results.keys()):
    if len(all_cards) >= max_total:
        break
    for c in results[idx]:
        key = _normalise(c.front)
        if key in seen_fronts:
            continue
        seen_fronts.add(key)
        all_cards.append(c)
        if len(all_cards) >= max_total:
            break
```

Cards are appended to `all_cards` in chunk-order, with a hard cap checked at each step. The nested loop with early `break` ensures we stop as soon as the budget is reached — a bounded linear scan.

#### `app/pdf_processor.py` — Page-by-Page Text Accumulation

```python
page_texts: list[str] = []
for page_no in range(pages_to_read):
    page = doc.load_page(page_no)
    raw = page.get_text("text") or ""
    cleaned = _clean_page(raw)
    filtered = "\n".join(
        ln for ln in cleaned.split("\n") if not _looks_like_header_footer(ln, page_no + 1)
    )
    if filtered.strip():
        page_texts.append(filtered)
```

Each PDF page's cleaned text is appended to a list in order. The final `"\n\n".join(page_texts)` merges them into a single document. This is a **producer-accumulator** pattern — pages are produced one at a time and accumulated for batch processing.

---

### 6.3 Sets (Hash Sets)

A **set** provides O(1) average-case membership testing and insertion, making it ideal for **deduplication**.

#### `app/flashcard_generator.py` — Front-Text Deduplication

```python
seen_fronts: set[str] = set()

for c in results[idx]:
    key = _normalise(c.front)
    if key in seen_fronts:   # O(1) membership check
        continue
    seen_fronts.add(key)     # O(1) insertion
    all_cards.append(c)
```

Before adding a card to the final list, its normalised front text is checked against `seen_fronts`. The set guarantees that no two cards share the same question (after whitespace normalisation and lowercasing). Without the set, this deduplication would require O(n²) pairwise comparisons.

#### `app/flashcard_generator.py` — Heuristic Term Deduplication

```python
seen_terms: set[str] = set()

for pat in _DEF_PATTERNS:
    for m in pat.finditer(chunk):
        term = m.group("term").strip().rstrip(":,-")
        key = term.lower()
        if key in seen_terms or len(term.split()) > 10:
            continue
        seen_terms.add(key)
        cards.append(...)
```

The heuristic fallback generator uses a set to ensure each definition term appears at most once. As the regex patterns iterate over the text, `seen_terms` grows and prevents duplicate `"What is X?"` cards from being emitted.

#### `app/flashcard_generator.py` — Valid Card Type Checking

```python
if ctype not in {"qa", "definition", "cloze", "application"}:
    ctype = "qa"
```

A **set literal** is used for O(1) membership testing to validate the card type returned by the LLM. If the LLM returns an unexpected type, it falls back to `"qa"`. This is more efficient than a chain of `==` comparisons.

---

### 6.4 Greedy Algorithm

A **greedy algorithm** makes the locally optimal choice at each step, hoping to reach a globally acceptable solution.

#### `app/pdf_processor.py` — Greedy Paragraph Packing (Bin Packing)

```python
for para in paragraphs:
    if len(para) > MAX_CHUNK_CHARS:
        flush()
        # Split on sentence boundaries
        sentences = re.split(r"(?<=[.!?])\s+", para)
        ...
        continue

    if buf_len + len(para) + 2 > CHUNK_TARGET_CHARS and buf_len >= MIN_CHUNK_CHARS:
        flush()
    buf.append(para)
    buf_len += len(para) + 2

# Merge trailing tiny chunk into previous.
if len(chunks) >= 2 and len(chunks[-1]) < MIN_CHUNK_CHARS:
    chunks[-2] = chunks[-2] + "\n\n" + chunks[-1]
    chunks.pop()
```

This is a **first-fit decreasing** variant of the bin-packing problem. Paragraphs are packed greedily into chunks: each paragraph is added to the current chunk if it fits within `CHUNK_TARGET_CHARS`; if not, the current chunk is flushed and a new one starts. Oversized paragraphs are split on sentence boundaries. A final pass merges any trailing runt chunk into the previous one. The greedy approach yields near-optimal chunks in O(n) time without the exponential cost of optimal bin packing.

#### `app/flashcard_generator.py` — Adaptive Card Budget

```python
_CHARS_PER_CARD = 250
_MIN_CARDS = 3

def _estimate_card_budget(chunks: list[str], hard_max: int, pages_read: int = 0) -> int:
    total_chars = sum(len(c) for c in chunks)
    char_budget = max(_MIN_CARDS, total_chars // _CHARS_PER_CARD)

    if pages_read > 0:
        # Primary: linear page-based scaling (1–100 pages → 3–70 cards)
        page_budget = max(_MIN_CARDS, round(pages_read * hard_max / config.MAX_PDF_PAGES))
        # Take the lower of the two: page count is the guide, chars prevent
        # inflating the count for very sparse / image-heavy pages.
        return min(page_budget, char_budget, hard_max)

    return min(char_budget, hard_max)  # fallback when page count unavailable
```

The budget algorithm uses two signals greedily combined:
1. **Primary (page-based):** `pages_read / MAX_PDF_PAGES × hard_max` — a linear scale from 3 cards (1 page) to 70 cards (100 pages).
2. **Secondary (char-based):** roughly 1 card per 250 characters of extracted text — prevents inflating the count for image-heavy or sparse PDFs.
The function returns the minimum of both signals, clamped to `[_MIN_CARDS, hard_max]`. This avoids both over-generating cards for short PDFs and under-generating for long, dense ones.

#### `app/flashcard_generator.py` — Per-Chunk Budget Distribution

```python
per_chunk = max(3, min(config.MAX_CARDS_PER_CHUNK, max_total // max(1, len(chunks)) + 2))
```

The total card budget is distributed across chunks using a greedy formula: divide equally and add a small buffer (+2). Each chunk gets a locally optimal budget, and the global cap is enforced during the merge phase. This is a **greedy partitioning** strategy.

---

### 6.5 Priority Queue / Scheduling Queue

A **priority queue** serves elements in order of priority rather than insertion order. The study engine implements this concept through database-backed sorted queries.

#### `app/routes/api_study.py` — Due-Card Priority Queue

```python
due_stmt = (
    select(models.Card)
    .where(models.Card.deck_id == deck_id)
    .where(models.Card.status != "new")
    .where(models.Card.next_review <= now)
    .order_by(models.Card.next_review.asc())   # <-- priority: most overdue first
    .limit(1)
)
card = db.execute(due_stmt).scalar_one_or_none()
```

The study session retrieves the **single most overdue card** by ordering all due cards by `next_review` ascending (earliest first). This is semantically a **min-priority queue** where priority = `next_review` timestamp. Cards that have been overdue the longest get studied first. The database's B-tree index on `next_review` makes this an O(log n) operation.

#### `app/routes/api_study.py` — Three-Tier Queue Cascade

```python
# Tier 1: Due cards (most overdue first)
card = db.execute(due_stmt).scalar_one_or_none()

if not card:
    # Tier 2: New cards (by insertion order)
    new_stmt = (
        select(models.Card)
        .where(models.Card.deck_id == deck_id)
        .where(models.Card.status == "new")
        .order_by(models.Card.id.asc())
        .limit(1)
    )
    card = db.execute(new_stmt).scalar_one_or_none()

if not card:
    # Tier 3: Session complete
    return {"done": True, "stats": ...}
```

The study engine implements a **multi-level priority queue**: overdue review cards → new cards → done. Each tier is a separate sorted query, and the cascade ensures the highest-priority card is always served first. This mirrors the scheduling logic of professional SRS apps like Anki.

---

### 6.6 String Matching & Pattern Matching (Regular Expressions)

**Pattern matching** uses formal grammars (regular expressions) to search, extract, and transform text. Regex matching operates in O(n × m) worst case, where n is the text length and m is the pattern complexity.

#### `app/flashcard_generator.py` — Compiled Definition Patterns

```python
_DEF_PATTERNS = [
    re.compile(
        r"(?P<term>[A-Z][A-Za-z0-9\- ]{2,60})\s+is\s+(defined as|an?|the)\s+(?P<def>[^.]+\.)"
    ),
    re.compile(r"(?P<term>[A-Z][A-Za-z0-9\- ]{2,60})\s+refers to\s+(?P<def>[^.]+\.)"),
    re.compile(r"(?P<term>[A-Z][A-Za-z0-9\- ]{2,60})\s+means\s+(?P<def>[^.]+\.)"),
    re.compile(r"(?P<term>[A-Z][A-Za-z0-9\- ]{2,60})\s*:\s*(?P<def>[^.\n]+\.)"),
]
```

Four **pre-compiled** regular expressions scan source text for definition-like sentences. Each uses **named capture groups** (`?P<term>`, `?P<def>`) to extract the term and its definition. Pre-compilation (via `re.compile`) avoids recompiling the pattern on every invocation — the compiled DFA is stored once and reused.

#### `app/flashcard_generator.py` — Sentence-Boundary Splitting

```python
sentences = re.split(r"(?<=[.!?])\s+", chunk)
```

A **lookbehind assertion** (`(?<=...)`) splits text on whitespace that follows sentence-ending punctuation *without consuming the punctuation*. This preserves complete sentences while splitting on logical boundaries — a common NLP preprocessing step.

#### `app/flashcard_generator.py` — Capitalised-Term Extraction for Cloze Cards

```python
m = re.search(r"\b([A-Z][a-zA-Z\-]{3,}(?:\s+[A-Z][a-zA-Z\-]{3,})?)\b", sent)
```

This regex identifies capitalised multi-word terms (likely proper nouns or concept names) within sentences. Matched terms are used to create cloze (fill-in-the-blank) cards where the term is replaced with `_____`. The `\b` word boundary anchors ensure partial matches are avoided.

#### `app/flashcard_generator.py` — JSON Extraction from LLM Output

```python
start = text.find("[")
end = text.rfind("]")

if start != -1 and end != -1 and end > start:
    json_str = text[start : end + 1]
```

Rather than a full regex, this uses Python's built-in **linear string search** (`find` / `rfind`) to locate the outermost JSON array brackets. `find` scans left-to-right for the first `[`, while `rfind` scans right-to-left for the last `]`. Combined, they extract the JSON payload from potentially noisy LLM output in O(n) time.

#### `app/pdf_processor.py` — Hyphenation Normalisation

```python
text = re.sub(r"(\w)-\r?\n(\w)", r"\1\2", text)
```

A regex substitution detects hyphenated line breaks (e.g., `"struc-\nture"`) and joins them into complete words (`"structure"`). The `\w` character class ensures only actual word-internal hyphens are joined, not list items or dashes.

#### `app/flashcard_generator.py` — Normalisation for Deduplication

```python
def _normalise(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip()
```

Before comparing card fronts for duplicates, whitespace is collapsed to single spaces and the string is lowercased. This ensures that `"What  is  X?"` and `"what is x?"` are treated as the same question — a classic **text canonicalisation** step.

---

### 6.7 Tree / Hierarchical Data Structure

A **tree** is a hierarchical structure where each node has a parent (except the root) and zero or more children. Relational databases model trees through foreign key relationships.

#### `app/models.py` — Four-Level Entity Tree

```
User (root)
 └── Deck (child of User)
      └── Card (child of Deck)
           └── ReviewLog (child of Card)
```

```python
class User(Base):
    decks: Mapped[list["Deck"]] = relationship("Deck", ..., cascade="all, delete-orphan")

class Deck(Base):
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    cards: Mapped[list["Card"]] = relationship("Card", ..., cascade="all, delete-orphan")

class Card(Base):
    deck_id: Mapped[int] = mapped_column(ForeignKey("decks.id", ondelete="CASCADE"))
    reviews: Mapped[list["ReviewLog"]] = relationship("ReviewLog", ..., cascade="all, delete-orphan")

class ReviewLog(Base):
    card_id: Mapped[int] = mapped_column(ForeignKey("cards.id", ondelete="CASCADE"))
```

The data model forms a **4-level tree**: `User → Deck → Card → ReviewLog`. Each level is connected by `ForeignKey` + `relationship` with `cascade="all, delete-orphan"`, which enforces **cascading delete** — deleting a user removes all their decks, cards, and review logs in a single recursive operation. The database uses **B-tree indexes** on all foreign key columns for O(log n) traversal.

---

### 6.8 Concurrency — Thread Pool (Bounded Parallelism)

A **thread pool** is a concurrency pattern that maintains a fixed set of worker threads, scheduling tasks across them to achieve parallelism while bounding resource usage.

#### `app/flashcard_generator.py` — Bounded-Parallel LLM Calls

```python
_LLM_CONCURRENCY = 3

with ThreadPoolExecutor(max_workers=_LLM_CONCURRENCY) as pool:
    futures = {
        pool.submit(_process_chunk, (idx, chunk)): idx
        for idx, chunk in enumerate(chunks, start=1)
    }

    results: dict[int, list[GeneratedCard]] = {}
    for future in as_completed(futures):
        idx, cards = future.result()
        results[idx] = cards
```

All text chunks are submitted to a `ThreadPoolExecutor` with a hard limit of 3 concurrent workers. The `as_completed` iterator yields futures in **completion order** (not submission order), enabling progress tracking as each chunk finishes. Results are stored in a dictionary keyed by chunk index, then merged in original order — achieving **out-of-order execution with in-order assembly**.

This bounds both memory (no more than 3 LLM responses in flight) and API rate pressure, while still being ~3× faster than sequential processing.

---

### 6.9 SM-2 Spaced Repetition Algorithm

The **SM-2 algorithm** is a mathematical scheduling algorithm from cognitive science that determines optimal review intervals using an ease factor and repetition count.

#### `app/spaced_repetition.py` — Full SM-2 Implementation

```python
def apply_rating(*, rating, ease_factor, interval_days, repetitions, lapses, reviews_count) -> SRSState:
    q = RATING_TO_QUALITY[rating]

    # Ease factor adjustment formula
    new_ef = ease_factor + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
    new_ef = max(1.3, new_ef)

    if q < 3:
        # Lapse: reset to ~10 minutes
        new_interval = 10 / (60 * 24)
        new_reps = 0
        new_lapses = lapses + 1
    else:
        if repetitions == 0:
            new_interval = 1.0        # First success: 1 day
        elif repetitions == 1:
            new_interval = 6.0        # Second success: 6 days
        else:
            base_interval = max(interval_days, 1.0)
            new_interval = round(base_interval * new_ef)  # Multiply by ease factor

        # Rating modifiers
        if rating == "hard":
            new_interval = max(1.0, new_interval * 0.8)
        elif rating == "easy":
            new_interval = new_interval * 1.3

    next_review = _now() + timedelta(days=new_interval)
    status = _derive_status(new_reps, new_interval, reviews_count + 1)
    return SRSState(...)
```

The algorithm implements three key DSA-relevant ideas:

1. **Recurrence relation:** Each review's output (`new_interval`, `new_ef`) feeds into the next review's input — a classic **dynamic/iterative computation** where current state depends on prior state.
2. **Clamping (bounded values):** The ease factor is clamped to `>= 1.3` to prevent intervals from collapsing to zero after repeated failures.
3. **State machine:** Cards transition between four states (`new → learning → review → mastered`) based on their interval and repetition count, implemented via `_derive_status()`.

#### `app/spaced_repetition.py` — Status Derivation (Decision Tree)

```python
def _derive_status(repetitions: int, interval_days: float, reviews_count: int) -> str:
    if reviews_count == 0:
        return "new"
    if interval_days < 1:
        return "learning"
    if interval_days >= 21 and repetitions >= 4:
        return "mastered"
    return "review"
```

This is a **decision tree** with three branching conditions. Each card's status is derived from its numeric state in O(1) time. The thresholds (1 day for learning, 21 days + 4 reps for mastered) encode cognitive science heuristics.

---

### 6.10 Linear Search with Filtering

**Linear search** scans elements one by one, applying a predicate to find matching items.

#### `app/routes/api_cards.py` — Filtered Card Search

```python
stmt = select(models.Card).where(models.Card.deck_id == deck_id)
if search:
    pattern = f"%{search.strip()}%"
    stmt = stmt.where(
        or_(models.Card.front.ilike(pattern), models.Card.back.ilike(pattern))
    )
if status_filter and status_filter != "all":
    stmt = stmt.where(models.Card.status == status_filter)
stmt = stmt.order_by(models.Card.id)
```

The card listing endpoint builds a SQL query that filters by deck, then optionally applies a **substring search** (`ILIKE %pattern%`) and a **status filter**. At the database level, this is a **linear scan** over the card table (or an index scan if indexes exist), with multiple predicate filters applied conjunctively.

---

### 6.11 Summary Table

| DSA Concept | Where Used | Example |
|---|---|---|
| **Hash Table (Dictionary)** | `flashcard_generator.py`, `spaced_repetition.py`, `stats.py` | `_PROVIDER_DISPATCH`, `RATING_TO_QUALITY`, `counts` dict |
| **Dynamic Array (List)** | `pdf_processor.py`, `flashcard_generator.py` | `chunks`, `buf`, `all_cards`, `page_texts` |
| **Hash Set** | `flashcard_generator.py` | `seen_fronts`, `seen_terms`, card-type validation set |
| **Greedy Algorithm** | `pdf_processor.py`, `flashcard_generator.py` | Paragraph packing, adaptive card budget, per-chunk distribution |
| **Priority Queue** | `api_study.py` | Due-card selection ordered by `next_review ASC` |
| **Pattern Matching (Regex)** | `flashcard_generator.py`, `pdf_processor.py` | `_DEF_PATTERNS`, sentence splitting, hyphenation fix, normalisation |
| **Tree (Hierarchical Data)** | `models.py` | `User → Deck → Card → ReviewLog` entity hierarchy |
| **Thread Pool (Concurrency)** | `flashcard_generator.py` | `ThreadPoolExecutor` with bounded parallelism |
| **Recurrence Relation (SM-2)** | `spaced_repetition.py` | Ease factor and interval computation across reviews |
| **Decision Tree** | `spaced_repetition.py` | `_derive_status()` branching logic |
| **Linear Search + Filter** | `api_cards.py`, `api_study.py` | `ILIKE` substring search, status filtering |
