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
    page_count: int
    chunks: list[str]
```

`PDFExtract` is the return value of `extract_pdf()`. It bundles three related pieces of information (full text, page count, chunk list) into a single typed object. The background worker in `api_decks.py` accesses `extract.chunks` and `extract.page_count` directly.

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
