"""
Flashcard generator with pluggable LLM providers.

Priority of providers (auto-detected from env):
    1. Groq       (OpenAI-compatible endpoint, free tier, Llama 3.3 70B)
    2. Gemini     (OpenAI-compatible endpoint, free tier, Gemini 2.5 Flash)
    3. Anthropic  (paid, Claude)
    4. Heuristic  (fully offline regex-based fallback)

Groq and Gemini both expose OpenAI-compatible chat completion APIs, so the
same `openai` Python SDK drives both -- we just swap the base_url, key, and
model name. The Anthropic path uses the official `anthropic` SDK.

Every provider gets the same prompt and returns strict JSON, which we then
parse defensively.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from . import config

logger = logging.getLogger(__name__)


@dataclass
class GeneratedCard:
    front: str
    back: str
    card_type: str = "qa"  # qa | definition | cloze | application
    source_excerpt: Optional[str] = None
    tags: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Prompting
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are an expert tutor building study flashcards from source material.

Your cards should be the kind a great teacher writes: clear, self-contained, and designed to test UNDERSTANDING, not just verbatim recall.

Rules you MUST follow:
1. Output ONLY a JSON array. No prose before or after. No markdown fences.
2. Each card is an object: {"front": str, "back": str, "type": "qa"|"definition"|"cloze"|"application", "tags": [str]}
3. Mix card types. A good batch has roughly: 40% concept Q&A, 25% definitions, 20% cloze (fill-in-the-blank), 15% application/example.
4. Questions must be self-contained. The student does NOT see the source text. Never write "According to the passage..." or "What does the text say about...".
5. For cloze cards, put the blank in the FRONT with ___ and the missing phrase in the BACK. The front should still be meaningful on its own.
6. Answers are CONCISE - ideally under 30 words, a single crisp idea. For definitions, one tight sentence.
7. NO duplicate or near-duplicate cards. Each card covers a distinct idea.
8. NO trivia-style questions about page numbers, figure numbers, authors, or meta-content.
9. NO questions with yes/no or one-word answers that don't teach anything ("Is water wet? Yes.").
10. Tags: 1-3 short lowercase keywords identifying the concept area.

Prefer cards that test: why things work, how concepts relate, when to apply them, worked examples, edge cases."""


USER_TEMPLATE = """Create up to {max_cards} high-quality flashcards from this excerpt. Fewer excellent cards beat many mediocre ones - if the passage is short or thin, return fewer.

Source excerpt:
\"\"\"
{chunk}
\"\"\"

Return ONLY a JSON array of card objects."""


# ---------------------------------------------------------------------------
# Provider calls
# ---------------------------------------------------------------------------

def _call_openai_compatible(
    chunk: str,
    max_cards: int,
    *,
    api_key: str,
    base_url: str,
    model: str,
    provider_name: str,
) -> list[GeneratedCard]:
    """Shared implementation for Groq and Gemini (both OpenAI-compatible)."""
    try:
        from openai import OpenAI
    except ImportError as e:
        raise RuntimeError("openai package not installed") from e

    client = OpenAI(api_key=api_key, base_url=base_url)
    response = client.chat.completions.create(
        model=model,
        temperature=0.3,
        max_tokens=2000,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": USER_TEMPLATE.format(max_cards=max_cards, chunk=chunk),
            },
        ],
    )
    text = (response.choices[0].message.content or "").strip()
    logger.debug("[%s] raw output length=%d", provider_name, len(text))
    return _parse_cards(text, chunk)


def _call_groq(chunk: str, max_cards: int) -> list[GeneratedCard]:
    return _call_openai_compatible(
        chunk,
        max_cards,
        api_key=config.GROQ_API_KEY,
        base_url="https://api.groq.com/openai/v1",
        model=config.GROQ_MODEL,
        provider_name="groq",
    )


def _call_gemini(chunk: str, max_cards: int) -> list[GeneratedCard]:
    return _call_openai_compatible(
        chunk,
        max_cards,
        api_key=config.GEMINI_API_KEY,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        model=config.GEMINI_MODEL,
        provider_name="gemini",
    )


def _call_anthropic(chunk: str, max_cards: int) -> list[GeneratedCard]:
    try:
        import anthropic
    except ImportError as e:
        raise RuntimeError("anthropic package not installed") from e

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=config.ANTHROPIC_MODEL,
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": USER_TEMPLATE.format(max_cards=max_cards, chunk=chunk),
            }
        ],
    )
    text = "".join(
        block.text for block in response.content if getattr(block, "type", None) == "text"
    ).strip()
    return _parse_cards(text, chunk)


_PROVIDER_DISPATCH = {
    "groq": _call_groq,
    "gemini": _call_gemini,
    "anthropic": _call_anthropic,
}


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

_JSON_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)


def _parse_cards(text: str, chunk: str) -> list[GeneratedCard]:
    """Parse the model output into GeneratedCard objects. Be defensive."""
    text = text.strip()
    # strip accidental markdown fences
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)

    # If there's explanatory text around the JSON, extract the array.
    if not text.startswith("["):
        m = _JSON_ARRAY_RE.search(text)
        if m:
            text = m.group(0)

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning("Failed to parse LLM JSON output: %s", e)
        return []

    if not isinstance(data, list):
        return []

    cards: list[GeneratedCard] = []
    excerpt = (chunk[:280] + "...") if len(chunk) > 280 else chunk
    for item in data:
        if not isinstance(item, dict):
            continue
        front = str(item.get("front", "")).strip()
        back = str(item.get("back", "")).strip()
        if not front or not back:
            continue
        ctype = str(item.get("type", "qa")).strip().lower()
        if ctype not in {"qa", "definition", "cloze", "application"}:
            ctype = "qa"
        tags_raw = item.get("tags", [])
        tags: list[str] = []
        if isinstance(tags_raw, list):
            tags = [str(t).strip().lower()[:30] for t in tags_raw if str(t).strip()][:3]
        cards.append(
            GeneratedCard(
                front=front,
                back=back,
                card_type=ctype,
                source_excerpt=excerpt,
                tags=tags,
            )
        )
    return cards


# ---------------------------------------------------------------------------
# Heuristic fallback (no API key of any kind)
# ---------------------------------------------------------------------------

_DEF_PATTERNS = [
    re.compile(
        r"(?P<term>[A-Z][A-Za-z0-9\- ]{2,60})\s+is\s+(defined as|an?|the)\s+(?P<def>[^.]+\.)"
    ),
    re.compile(r"(?P<term>[A-Z][A-Za-z0-9\- ]{2,60})\s+refers to\s+(?P<def>[^.]+\.)"),
    re.compile(r"(?P<term>[A-Z][A-Za-z0-9\- ]{2,60})\s+means\s+(?P<def>[^.]+\.)"),
]


def _heuristic_cards(chunk: str, max_cards: int) -> list[GeneratedCard]:
    """Very simple pattern-based card extraction as a last-resort fallback."""
    cards: list[GeneratedCard] = []
    seen_terms: set[str] = set()
    excerpt = (chunk[:280] + "...") if len(chunk) > 280 else chunk

    for pat in _DEF_PATTERNS:
        for m in pat.finditer(chunk):
            term = m.group("term").strip().rstrip(":,-")
            definition = m.group("def").strip()
            key = term.lower()
            if key in seen_terms or len(term.split()) > 8:
                continue
            seen_terms.add(key)
            cards.append(
                GeneratedCard(
                    front=f"What is {term}?",
                    back=definition,
                    card_type="definition",
                    source_excerpt=excerpt,
                    tags=[],
                )
            )
            if len(cards) >= max_cards:
                return cards

    # Cloze from sentences containing important-looking capitalised terms.
    sentences = re.split(r"(?<=[.!?])\s+", chunk)
    for sent in sentences:
        if len(cards) >= max_cards:
            break
        if len(sent) < 60 or len(sent) > 240:
            continue
        m = re.search(r"\b([A-Z][a-zA-Z\-]{3,}(?:\s+[A-Z][a-zA-Z\-]{3,})?)\b", sent)
        if not m:
            continue
        term = m.group(1)
        if term.lower() in seen_terms:
            continue
        seen_terms.add(term.lower())
        cloze_front = sent.replace(term, "_____", 1)
        cards.append(
            GeneratedCard(
                front=cloze_front,
                back=term,
                card_type="cloze",
                source_excerpt=excerpt,
                tags=[],
            )
        )

    return cards


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_cards_for_chunks(
    chunks: list[str],
    *,
    max_total: Optional[int] = None,
    progress_cb=None,
) -> list[GeneratedCard]:
    """Generate cards across all chunks, deduping and capping the total."""
    if max_total is None:
        max_total = config.MAX_TOTAL_CARDS

    provider = config.active_provider()
    logger.info("Generating cards using provider=%s", provider)

    llm_fn = _PROVIDER_DISPATCH.get(provider)  # None for 'heuristic'

    all_cards: list[GeneratedCard] = []
    seen_fronts: set[str] = set()

    # Budget per chunk so we don't blow through max_total on the first chunk.
    per_chunk = max(3, min(config.MAX_CARDS_PER_CHUNK, max_total // max(1, len(chunks)) + 2))

    for idx, chunk in enumerate(chunks, start=1):
        if len(all_cards) >= max_total:
            break

        cards: list[GeneratedCard] = []
        if llm_fn is not None:
            try:
                cards = llm_fn(chunk, per_chunk)
            except Exception as e:
                logger.warning(
                    "Provider %s failed on chunk %d: %s. Using heuristic fallback for this chunk.",
                    provider, idx, e,
                )
                cards = _heuristic_cards(chunk, per_chunk)
        else:
            cards = _heuristic_cards(chunk, per_chunk)

        for c in cards:
            key = _normalise(c.front)
            if key in seen_fronts:
                continue
            seen_fronts.add(key)
            all_cards.append(c)
            if len(all_cards) >= max_total:
                break

        if progress_cb:
            progress_cb(idx, len(chunks), len(all_cards))

    return all_cards


def _normalise(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip()
