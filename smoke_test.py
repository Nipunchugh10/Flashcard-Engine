"""End-to-end smoke test hitting the real FastAPI app in-process."""
import os
import pathlib
import sys

# Make sure the app runs against a fresh DB.
here = pathlib.Path(__file__).resolve().parent
db_path = here / "data" / "flashcards.db"
db_path.parent.mkdir(exist_ok=True)
if db_path.exists():
    db_path.unlink()

sys.path.insert(0, str(here))

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402


def main():
    # Use TestClient as a context manager so the lifespan startup event fires
    # (creating the SQLite tables).
    with TestClient(app) as client:
        run_tests(client)


def run_tests(client):

    # --- 1. Home page -----------------------------------------------------------
    r = client.get("/")
    assert r.status_code == 200, r.text[:500]
    assert "Your decks" in r.text
    assert "Nothing to study yet" in r.text  # empty state
    print("[1] GET /                             -> 200  (empty state renders)")

    # --- 2. List decks (empty) --------------------------------------------------
    r = client.get("/api/decks")
    assert r.status_code == 200
    assert r.json() == []
    print("[2] GET /api/decks                    -> 200  (empty list)")

    # --- 3. Upload the challenge PDF itself as the test input -------------------
    pdf_path = "/mnt/user-data/uploads/AI_Builder___Build_Challenge__2___1___1_.pdf"
    with open(pdf_path, "rb") as f:
        r = client.post(
            "/api/decks/upload",
            files={"file": ("challenge.pdf", f, "application/pdf")},
            data={"name": "Build Challenge Spec"},
        )
    assert r.status_code == 201, f"{r.status_code}: {r.text[:500]}"
    deck = r.json()
    deck_id = deck["id"]
    print(f"[3] POST /api/decks/upload            -> 201  deck_id={deck_id}  "
          f"cards={deck['stats']['total']}  pages={deck['source_pages']}")

    # --- 4. Home page now shows the deck ---------------------------------------
    r = client.get("/")
    assert r.status_code == 200
    assert "Build Challenge Spec" in r.text
    assert "Nothing to study yet" not in r.text
    print("[4] GET /  (after upload)             -> 200  (deck appears)")

    # --- 5. Deck page renders ---------------------------------------------------
    r = client.get(f"/decks/{deck_id}")
    assert r.status_code == 200, r.text[:400]
    assert "Build Challenge Spec" in r.text
    print(f"[5] GET /decks/{deck_id}                     -> 200  (deck page renders)")

    # --- 6. Card list via API ---------------------------------------------------
    r = client.get(f"/api/cards?deck_id={deck_id}")
    assert r.status_code == 200
    cards = r.json()
    assert len(cards) >= 5
    assert all("front" in c and "back" in c for c in cards)
    print(f"[6] GET /api/cards?deck_id={deck_id}          -> 200  ({len(cards)} cards returned)")
    print(f"      sample: Q: {cards[0]['front'][:70]!r}")
    print(f"              A: {cards[0]['back'][:70]!r}")

    # --- 7. Study session: fetch next card --------------------------------------
    r = client.get(f"/api/study/{deck_id}/next")
    assert r.status_code == 200
    nxt = r.json()
    assert nxt["done"] is False
    assert "card" in nxt and "remaining" in nxt
    first_card_id = nxt["card"]["id"]
    first_remaining = nxt["remaining"]
    assert nxt["card"]["status"] == "new"
    print(f"[7] GET /api/study/{deck_id}/next             -> 200  "
          f"next_card_id={first_card_id}  remaining={first_remaining}  status={nxt['card']['status']}")

    # --- 8. Rate the card "good" and verify SM-2 state updated ------------------
    r = client.post(f"/api/study/cards/{first_card_id}/rate", json={"rating": "good"})
    assert r.status_code == 200
    rated = r.json()
    assert rated["reviews_count"] == 1
    assert rated["repetitions"] == 1
    assert abs(rated["interval_days"] - 1.0) < 0.01   # first Good -> 1 day
    assert rated["status"] == "review"                # no longer "new"
    assert rated["last_reviewed"] is not None
    print(f"[8] POST /api/study/cards/{first_card_id}/rate       -> 200  "
          f"interval={rated['interval_days']}d  reps={rated['repetitions']}  status={rated['status']}")

    # --- 9. Rate a second card "again" and confirm lapse behaviour -------------
    r = client.get(f"/api/study/{deck_id}/next")
    next2 = r.json()
    card2_id = next2["card"]["id"]
    assert card2_id != first_card_id  # we got a different card
    r = client.post(f"/api/study/cards/{card2_id}/rate", json={"rating": "again"})
    assert r.status_code == 200
    lapsed = r.json()
    assert lapsed["lapses"] == 1
    assert lapsed["interval_days"] < 0.01  # ~10 minutes expressed in days
    assert lapsed["repetitions"] == 0
    print(f"[9] POST .../rate  (again)            -> 200  "
          f"lapses={lapsed['lapses']}  interval={lapsed['interval_days']:.4f}d  (~10 min)")

    # --- 10. Remaining counter should have dropped -----------------------------
    r = client.get(f"/api/study/{deck_id}/next")
    next3 = r.json()
    assert next3["done"] is False
    assert next3["remaining"] < first_remaining
    print(f"[10] remaining dropped: {first_remaining} -> {next3['remaining']}")

    # --- 11. Deck stats reflect the reviews ------------------------------------
    r = client.get(f"/api/decks/{deck_id}")
    deck_now = r.json()
    s = deck_now["stats"]
    assert s["total"] == len(cards)
    assert s["review"] >= 1       # the one we rated Good
    assert s["learning"] >= 1     # the one we rated Again (<1 day interval)
    print(f"[11] deck stats:  total={s['total']}  new={s['new']}  "
          f"learning={s['learning']}  review={s['review']}  mastered={s['mastered']}  due_now={s['due_now']}")

    # --- 12. Card search + status filter ---------------------------------------
    r = client.get(f"/api/cards?deck_id={deck_id}&status_filter=review")
    assert r.status_code == 200
    review_cards = r.json()
    assert len(review_cards) >= 1
    assert all(c["status"] == "review" for c in review_cards)
    print(f"[12] GET /api/cards?status_filter=review -> 200  ({len(review_cards)} review cards)")

    # --- 13. Edit a card --------------------------------------------------------
    r = client.patch(
        f"/api/cards/{first_card_id}",
        json={"front": "EDITED: Is the smoke test working?", "back": "Yes."},
    )
    assert r.status_code == 200
    assert r.json()["front"].startswith("EDITED:")
    print("[13] PATCH /api/cards/{id}            -> 200  (card edit works)")

    # --- 14. Delete a card ------------------------------------------------------
    r = client.delete(f"/api/cards/{card2_id}")
    assert r.status_code == 204
    r = client.get(f"/api/decks/{deck_id}")
    assert r.json()["stats"]["total"] == len(cards) - 1
    print("[14] DELETE /api/cards/{id}           -> 204  (card count decreased)")

    # --- 15. Study page renders ------------------------------------------------
    r = client.get(f"/decks/{deck_id}/study")
    assert r.status_code == 200
    assert "Show answer" in r.text
    assert "flip-card" in r.text
    print(f"[15] GET /decks/{deck_id}/study             -> 200  (study page renders)")

    # --- 16. Rename deck --------------------------------------------------------
    r = client.patch(f"/api/decks/{deck_id}", json={"name": "Renamed Deck"})
    assert r.status_code == 200
    assert r.json()["name"] == "Renamed Deck"
    print("[16] PATCH /api/decks/{id}            -> 200  (rename works)")

    # --- 17. Delete deck --------------------------------------------------------
    r = client.delete(f"/api/decks/{deck_id}")
    assert r.status_code == 204
    r = client.get("/api/decks")
    assert r.json() == []
    print("[17] DELETE /api/decks/{id}           -> 204  (deck + cards gone)")

    # --- 18. OpenAPI docs endpoint ---------------------------------------------
    r = client.get("/docs")
    assert r.status_code == 200
    print("[18] GET /docs                        -> 200  (OpenAPI UI up)")

    print("\nAll 18 smoke tests passed.")


if __name__ == "__main__":
    main()
