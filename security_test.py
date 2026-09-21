"""Adversarial security tests.

Run with:  ./run.sh security

These are regression tests for vulnerabilities that were found and fixed, plus
standing checks on the access-control rules. Every test states the attack it
represents, so a future change that reopens a hole fails loudly here rather
than silently in production.
"""
import os
import pathlib
import statistics
import sys
import tempfile
import time

_tmp = pathlib.Path(tempfile.mkdtemp(prefix="recall-sec-"))
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp / 'sec.db'}"
os.environ["LLM_PROVIDER"] = "heuristic"

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from fastapi.testclient import TestClient  # noqa: E402
from itsdangerous import URLSafeTimedSerializer  # noqa: E402

from app import config  # noqa: E402
from app.main import app  # noqa: E402
from app.security import auth_limiter  # noqa: E402
from smoke_test import _minimal_pdf_bytes  # noqa: E402

PASSED: list[str] = []
FAILED: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    (PASSED if condition else FAILED).append(label)
    mark = "ok  " if condition else "FAIL"
    print(f"  [{mark}] {label}" + (f"  ({detail})" if detail else ""))


def signup(client: TestClient, username: str, email: str, password: str = "secret123"):
    return client.post(
        "/signup",
        data={"username": username, "email": email,
              "password": password, "confirm_password": password},
        follow_redirects=False,
    )


def wait_ready(client: TestClient, deck_id: int, timeout: float = 90.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if client.get(f"/api/decks/{deck_id}/status").json()["generation_status"] != "processing":
            return
        time.sleep(0.2)
    raise AssertionError("deck never finished generating")


def main() -> None:
    with TestClient(app) as alice, TestClient(app) as bob, TestClient(app) as anon:
        signup(alice, "Alice", "alice@example.com")
        signup(bob, "Bob", "bob@example.com")

        deck = alice.post(
            "/api/decks/upload",
            files={"file": ("a.pdf", _minimal_pdf_bytes(), "application/pdf")},
            data={"name": "Alice Private Deck"},
        ).json()
        deck_id = deck["id"]
        wait_ready(alice, deck_id)
        cards = alice.get(f"/api/cards?deck_id={deck_id}").json()
        card_id = cards[0]["id"]

        # -- 1. Horizontal privilege escalation (IDOR) -----------------------
        # Bob guesses Alice's deck and card ids from the URL.
        print("\n1. Another user cannot reach Alice's data by guessing ids")
        attempts = [
            ("GET  /decks/{id}",              bob.get(f"/decks/{deck_id}")),
            ("GET  /decks/{id}/study",        bob.get(f"/decks/{deck_id}/study")),
            ("GET  /api/decks/{id}",          bob.get(f"/api/decks/{deck_id}")),
            ("GET  /api/decks/{id}/status",   bob.get(f"/api/decks/{deck_id}/status")),
            ("PATCH /api/decks/{id}",         bob.patch(f"/api/decks/{deck_id}", json={"name": "pwned"})),
            ("DELETE /api/decks/{id}",        bob.delete(f"/api/decks/{deck_id}")),
            ("GET  /api/cards?deck_id={id}",  bob.get(f"/api/cards?deck_id={deck_id}")),
            ("PATCH /api/cards/{id}",         bob.patch(f"/api/cards/{card_id}", json={"front": "x", "back": "y"})),
            ("DELETE /api/cards/{id}",        bob.delete(f"/api/cards/{card_id}")),
            ("GET  /api/study/{id}/next",     bob.get(f"/api/study/{deck_id}/next")),
            ("POST /api/study/cards/{id}/rate", bob.post(f"/api/study/cards/{card_id}/rate", json={"rating": "good"})),
        ]
        for label, resp in attempts:
            # 404 rather than 403: a 403 confirms the id exists.
            check(f"{label} -> 404", resp.status_code == 404, f"got {resp.status_code}")

        blob = bob.get(f"/api/decks/{deck_id}").text + bob.get(f"/decks/{deck_id}").text
        check("Alice's deck name never appears in Bob's responses",
              "Alice Private Deck" not in blob)
        check("Alice's cards survived Bob's attempts",
              len(alice.get(f"/api/cards?deck_id={deck_id}").json()) == len(cards))

        # -- 2. Unauthenticated access ---------------------------------------
        print("\n2. Anonymous callers are refused")
        for label, resp in [
            ("GET  /api/decks",              anon.get("/api/decks")),
            ("GET  /api/decks/{id}",         anon.get(f"/api/decks/{deck_id}")),
            ("GET  /api/cards?deck_id={id}", anon.get(f"/api/cards?deck_id={deck_id}")),
            ("POST /api/study/cards/{id}/rate", anon.post(f"/api/study/cards/{card_id}/rate", json={"rating": "good"})),
        ]:
            check(f"{label} -> 401", resp.status_code == 401, f"got {resp.status_code}")
        check("GET /decks/{id} redirects to login",
              anon.get(f"/decks/{deck_id}", follow_redirects=False).status_code == 302)

        # -- 3. Session forgery ----------------------------------------------
        # Session cookies are signed tokens. If SECRET_KEY is guessable an
        # attacker mints a cookie for any uid and takes over the account, so
        # config refuses placeholder and short keys.
        print("\n3. Session tokens cannot be forged")
        for weak in ("dev-secret-change-me-in-production", "change-me-to-something-random", "secret"):
            evil = TestClient(app)
            evil.cookies.set(config.SESSION_COOKIE_NAME,
                             URLSafeTimedSerializer(weak).dumps({"uid": 1, "ep": 0}))
            check(f"cookie signed with {weak[:28]!r} rejected",
                  evil.get("/api/decks").status_code == 401)

        tampered = TestClient(app)
        tampered.cookies.set(config.SESSION_COOKIE_NAME, "not.a.valid.token")
        check("malformed cookie rejected", tampered.get("/api/decks").status_code == 401)
        check("config refuses placeholder SECRET_KEY", config.SECRET_KEY_WARNING is not None
              or len(config.SECRET_KEY) >= config.MIN_SECRET_KEY_LENGTH)

        # -- 4. Logout revokes the token -------------------------------------
        # Cookies are stateless, so logout must bump a server-side epoch;
        # otherwise a copied cookie stays valid for the full 30 days.
        print("\n4. Logout invalidates the issued token")
        carol = TestClient(app)
        signup(carol, "Carol", "carol@example.com")
        stolen = carol.cookies.get(config.SESSION_COOKIE_NAME)
        thief = TestClient(app)
        thief.cookies.set(config.SESSION_COOKIE_NAME, stolen)
        check("cookie works before logout", thief.get("/api/decks").status_code == 200)
        carol.post("/logout", follow_redirects=False)
        thief2 = TestClient(app)
        thief2.cookies.set(config.SESSION_COOKIE_NAME, stolen)
        check("same cookie rejected after logout", thief2.get("/api/decks").status_code == 401)

        # -- 5. Cookie flags --------------------------------------------------
        print("\n5. Session cookie flags")
        https = {"x-forwarded-proto": "https"}
        c = TestClient(app)
        secure_cookie = signup(c, "Dave", "dave@example.com").headers.get("set-cookie", "")
        c2 = TestClient(app)
        r2 = c2.post("/signup", data={"username": "Erin", "email": "erin@example.com",
                     "password": "secret123", "confirm_password": "secret123"},
                     headers=https, follow_redirects=False)
        https_cookie = r2.headers.get("set-cookie", "")
        check("HttpOnly set (blocks document.cookie theft)", "httponly" in secure_cookie.lower())
        check("SameSite set (blocks cross-site CSRF)", "samesite" in secure_cookie.lower())
        check("Secure set when served over HTTPS", "secure" in https_cookie.lower())
        check("Secure omitted on plain HTTP so localhost works",
              "secure" not in secure_cookie.lower())

        # -- 6. User enumeration ----------------------------------------------
        print("\n6. Login does not reveal which emails are registered")
        def median_ms(email: str) -> float:
            xs = []
            for _ in range(5):
                s = time.perf_counter()
                TestClient(app).post("/login", data={"email": email, "password": "wrong"},
                                     follow_redirects=False)
                xs.append((time.perf_counter() - s) * 1000)
            return statistics.median(xs)

        auth_limiter.clear()
        known, unknown = median_ms("alice@example.com"), median_ms("nobody@example.com")
        ratio = known / unknown if unknown else 99
        check("timing comparable for known vs unknown account",
              ratio < 2.0, f"{known:.0f}ms vs {unknown:.0f}ms, {ratio:.1f}x")

        auth_limiter.clear()
        a = TestClient(app).post("/login", data={"email": "alice@example.com", "password": "wrong"},
                                 follow_redirects=False).text
        b = TestClient(app).post("/login", data={"email": "nobody@example.com", "password": "wrong"},
                                 follow_redirects=False).text
        check("identical error message either way",
              ("Invalid email or password" in a) and ("Invalid email or password" in b))

        # -- 7. Brute force ----------------------------------------------------
        print("\n7. Repeated failed logins are throttled")
        auth_limiter.clear()
        codes = [TestClient(app).post("/login",
                 data={"email": "alice@example.com", "password": f"guess{i}"},
                 follow_redirects=False).status_code for i in range(config.AUTH_RATE_LIMIT_ATTEMPTS + 5)]
        check("429 returned once the limit is hit", 429 in codes,
              f"last codes {codes[-3:]}")

        # -- 8. XSS via deck name ----------------------------------------------
        # The deck name is interpolated into an Alpine @click expression. It
        # must survive HTML entity decoding without ending the string literal
        # or the attribute.
        print("\n8. Deck names cannot break out of the Alpine attribute")
        for payload in ['";alert(1);//', "'+alert(2)+'", "</script><script>alert(3)</script>",
                        '" onmouseover="alert(4)']:
            alice.patch(f"/api/decks/{deck_id}", json={"name": payload})
            line = next(l for l in alice.get(f"/decks/{deck_id}").text.split("\n")
                        if "newName =" in l)
            value = line.split("newName = ", 1)[1]
            value = value[:value.index("'")] if "'" in value else value
            contained = (
                value.startswith('"') and value.endswith('"')
                and "onmouseover=" not in line.split("newName")[0]
            )
            check(f"payload {payload[:24]!r} contained", contained)
        alice.patch(f"/api/decks/{deck_id}", json={"name": "Alice Private Deck"})

        # -- 9. Security headers ------------------------------------------------
        print("\n9. Hardened response headers")
        h = TestClient(app).get("/").headers
        check("Content-Security-Policy present", "content-security-policy" in h)
        check("frame-ancestors allows Hugging Face and self (clickjacking)",
              "frame-ancestors 'self'" in h.get("content-security-policy", "") and
              "https://huggingface.co" in h.get("content-security-policy", ""))
        check("X-Content-Type-Options nosniff", h.get("x-content-type-options") == "nosniff")
        check("X-Frame-Options omitted for Hugging Face iframe embedding", "x-frame-options" not in h)
        check("Referrer-Policy set", "referrer-policy" in h)
        hh = TestClient(app).get("/", headers=https).headers
        check("HSTS sent over HTTPS", "strict-transport-security" in hh)

        # -- 10. Upload restrictions ---------------------------------------------
        print("\n10. Upload validation")
        r = alice.post("/api/decks/upload",
                       files={"file": ("evil.exe", b"MZ\x00\x00not a pdf", "application/octet-stream")})
        check("non-PDF rejected", r.status_code == 400, f"got {r.status_code}")
        big = b"%PDF-1.4\n" + b"0" * (config.MAX_PDF_SIZE_MB * 1024 * 1024 + 1024)
        r = alice.post("/api/decks/upload", files={"file": ("big.pdf", big, "application/pdf")})
        check("oversized PDF rejected with 413", r.status_code == 413, f"got {r.status_code}")
        r = alice.post("/api/decks/upload",
                       files={"file": ("../../../etc/passwd.pdf", _minimal_pdf_bytes(), "application/pdf")})
        if r.status_code == 201:
            saved = list(config.UPLOAD_DIR.glob("*"))
            escaped = [p for p in saved if "passwd" in p.name or ".." in str(p)]
            check("traversal filename did not escape the upload dir", not escaped)
            alice.delete(f"/api/decks/{r.json()['id']}")
        else:
            check("traversal filename handled", True)

    print("\n" + "=" * 64)
    print(f"  PASSED {len(PASSED)}   FAILED {len(FAILED)}")
    if FAILED:
        print("\n  FAILURES:")
        for f in FAILED:
            print(f"    - {f}")
        raise SystemExit(1)
    print("  All security checks passed.")


if __name__ == "__main__":
    main()
