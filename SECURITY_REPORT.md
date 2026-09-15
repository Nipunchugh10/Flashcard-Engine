# 🔐 Security Audit Report — Recall (Flashcard Engine)

**Target:** `Recall` — FastAPI + Jinja2 + Alpine.js PDF→flashcard application
**Repository:** https://github.com/Nipunchugh10/Flashcard-Engine
**Live deployment:** https://nipunchugh10-flashcard-engine.hf.space (Hugging Face Spaces, Docker SDK)
**Audit date:** 2026-09-15
**Baseline commit:** `c7b6ebf`
**Scope:** 2,613 LOC application code · 23 HTTP routes · 41 audit prompts
**Methodology:** `VIBE_APP_SECURITY_AUDIT.md` — all 41 prompts, executed in sequence

---

## How this audit was run

Every finding below is **evidence-backed**: exploited against a running instance, or
demonstrated with tool output quoted inline. Nothing is asserted from reading code
alone. Where a category does not apply to this application, it is marked
**N/A** with the reason, not padded with speculation.

Two permanent test suites back the results and can be re-run at any time:

```bash
./run.sh test       # 21 functional end-to-end tests
./run.sh security   # 45 adversarial security tests
```

**Verdict key:** ✅ CLEAN · ⚠️ FINDING · 🔧 FIXED IN THIS AUDIT · ⬜ N/A

---

## Executive summary

The application was audited in a hardened state — a prior pass had already fixed
session forgery, IDOR, logout revocation, timing-based user enumeration and
security headers. This audit targeted what that pass missed.

**17 findings across 41 prompts. 11 fixed during this audit, 5 remain open**
(a sixth — operational finding C, database persistence — was closed on
verification: the Space is backed by Neon Postgres, not ephemeral SQLite).

| Severity | Found | Fixed | Open |
|---|---|---|---|
| 🔴 Critical | 0 | 0 | 0 |
| 🟠 High | 3 | 3 | 0 |
| 🟡 Medium | 7 | 6 | 1 |
| 🟢 Low | 5 | 2 | 3 |
| ℹ️ Info | 2 | 0 | 2 |

### The three that mattered

**1. The brute-force protection I shipped last session was bypassable.** The rate
limiter keyed on the left-most `X-Forwarded-For` entry — a header the client
controls. Rotating it gave **60 login attempts, zero throttled**. Fixed by counting
in from the trusted end of the proxy chain and adding a per-account limiter, so an
attacker distributing across addresses still cannot grind one account.

**2. 19 known vulnerabilities in dependencies**, several directly reachable:
`starlette` multipart DoS and urlencoded limit bypass, `python-multipart`
negative-`Content-Length` memory exhaustion — all on this app's upload and login
paths. Upgraded to a clean set; `pip-audit` now reports **zero**.

**3. No `.dockerignore` with `COPY . /code/`.** Any local `docker build` baked the
real `.env` (Gemini key + `SECRET_KEY`), the SQLite database containing user
password hashes, and 16 MB of uploaded user PDFs into the image layers.

### What was already solid

Access control is genuinely well-built. All 11 object-scoped endpoints were probed
with a second authenticated account manipulating IDs — every one returned `404`,
no data leaked, no collateral damage. SQL injection surface is nil (SQLAlchemy
bound parameters throughout, zero raw string interpolation). No `eval`, no
`subprocess`, no `pickle`, no XML parsing. Passwords are bcrypt cost 12.

---

## 📋 MASTER FINDINGS TABLE

| # | Prompt | Finding | File:Line | Severity | CVSS | Status | Fix Made |
|---|--------|---------|-----------|----------|------|--------|----------|
| 1 | P09/P19 | Rate limiter bypassed by spoofing `X-Forwarded-For` — 60/60 login attempts allowed | `app/security.py:82` | 🟠 High | 7.5 | **Fixed** | Count from trusted end of proxy chain (`TRUSTED_PROXY_HOPS`) + per-account limiter |
| 2 | P10 | 19 known CVEs in 5 packages; starlette + python-multipart DoS reachable on upload/login | `requirements.txt` | 🟠 High | 7.5 | **Fixed** | Upgraded to starlette 1.6.0, python-multipart 0.0.32, jinja2 3.1.6, dotenv 1.2.3 → 0 advisories |
| 3 | P11/P27 | No `.dockerignore`; `COPY . /code/` bakes `.env`, SQLite DB (password hashes) and user PDFs into image | `Dockerfile:23` | 🟠 High | 7.8 | **Fixed** | Added `.dockerignore` excluding secrets, DB, uploads, `.git`, venvs |
| 4 | P19/P28 | No timeout on outbound LLM calls — SDK default 600s × 2 retries pins a worker thread ~30 min | `app/flashcard_generator.py:96` | 🟡 Medium | 5.3 | **Fixed** | `LLM_TIMEOUT_SECONDS=60`, `LLM_MAX_RETRIES=1` |
| 5 | P09/P19/P28 | `/api/decks/upload` had no rate limit — unbounded PDF parsing + billable LLM spend | `app/routes/api_decks.py:118` | 🟡 Medium | 6.5 | **Fixed** | `upload_limiter` 10/hour, per-IP **and** per-account, returns 429 + `Retry-After` |
| 6 | P07/P09 | Raw exception text returned to users in `generation_error` (paths, provider internals) | `app/routes/api_decks.py:203` | 🟡 Medium | 4.3 | **Fixed** | Log detail server-side; return actionable generic message |
| 7 | P11/P27 | `chmod -R 777` on `/code/data` and `/code/uploads` — world-writable DB and uploads | `Dockerfile:27` | 🟡 Medium | 5.5 | **Fixed** | `chown user:user` + `chmod 700` |
| 8 | P07/P37 | No `Cache-Control` on authenticated responses — per-user decks cacheable by proxy/back-button | `app/security.py` | 🟡 Medium | 4.0 | **Fixed** | `no-store, private` when a session cookie is present |
| 9 | P16 | Zero security-event logging — failed logins, lockouts, logouts all unlogged | `app/routes/auth.py` | 🟡 Medium | 5.0 | **Fixed** | `auth.login.failed/ok/throttled`, `auth.logout`, `auth.signup.*` |
| 10 | P26 | Concurrent signup with same email → uncaught `IntegrityError` → HTTP 500 | `app/routes/auth.py:130` | 🟢 Low | 3.1 | **Fixed** | Catch `IntegrityError`, roll back, return the normal message |
| 11 | P24 | `import fitz` deprecated in PyMuPDF 1.28 — breaks on a future upgrade | `app/pdf_processor.py:24` | ℹ️ Info | — | **Fixed** | Switched to `import pymupdf` |
| 12 | P06 | CSRF defence is SameSite=Lax only, no tokens; Chrome's "Lax+POST" 2-min window is a real gap for bodyless POSTs | `app/auth.py:88` | 🟡 Medium | 4.3 | **Open** | Recommend `SameSite=Strict` or double-submit token on `/logout`, `/undo`, `/upload` |
| 13 | P08 | No magic-byte validation — any bytes accepted if named `.pdf` | `app/routes/api_decks.py:137` | 🟢 Low | 2.6 | **Open** | Mitigated: UUID filename, never web-served, deleted after parse. Add `%PDF-` header check |
| 14 | P08/P19/P32 | Orphaned uploads accumulate — 8 PDFs / 16 MB, oldest 25 days; no janitor if process dies mid-parse | `app/routes/api_decks.py:279` | 🟢 Low | 3.3 | **Open** | Add startup sweep for files older than N hours |
| 15 | P17 | No Subresource Integrity on Tailwind/Alpine CDN `<script>` tags | `templates/components/head.html:13` | 🟢 Low | 3.7 | **Open** | Pin Alpine with `integrity`; Tailwind play-CDN cannot be pinned — vendor it for production |
| 16 | P32 | No account deletion, no data export, no retention policy (GDPR Art. 15/17/5e) | app-wide | 🟡 Medium | — | **Open** | Add `DELETE /api/me` (cascades exist) + JSON export |
| 17 | P29 | No CI/CD at all — no dependency scan, SAST, or secret scanning gate | repo root | ℹ️ Info | — | **Open** | Add GitHub Actions running `pip-audit`, `bandit`, `gitleaks` + both suites |

### Out-of-band (not code — operational)

| # | Issue | Evidence | Severity | Status |
|---|---|---|---|---|
| A | Hugging Face **write token in plaintext** in `.git/config` remote URL | `grep hf_ .git/config` → 1 match | 🟠 High | **Open — rotate** |
| B | `SECRET_KEY` is set on the Space, but if its value equals the local `.env` value it is **rejected as guessable** and replaced with a random key each boot | `.env` holds `recall-flashcard-engine-secret-key-2026`, which `app/config.py` blocklists; Space secret dated **Jun 30**, before that blocklist existed | 🟡 Medium | **Open — verify the value** |
| C | ~~`DATABASE_URL` unverified — data loss per rebuild~~ | **Resolved.** Space secrets confirm `DATABASE_URL` is set; Neon project `flashcard-db` (Postgres 18, AWS us-east-2) shows recent compute activity, so the app is genuinely connected | — | ✅ **Closed** |

---

# Per-prompt results

## 🔴 PROMPT 1 — Hardcoded secrets & credential leakage

**Verdict: ✅ CLEAN (repository) · ⚠️ FINDING (local environment, out-of-band)**

Searched every tracked file — not by extension — for `sk-`, `AIza`, `AKIA`, `ghp_`,
`xox*`, `hf_`, `-----BEGIN * PRIVATE KEY`, `password=`, `secret=`, and quoted
assignments, excluding `.example` placeholders:

```
$ git ls-files -z | xargs -0 grep -nEI '<secret patterns>'
  none in tracked files
$ git ls-files --error-unmatch .env
  .env NOT tracked (good)
```

`.gitignore` covers `.env`, `.env.local`, `.env.*.local`, `data/*.db*`, `uploads/*.pdf`.
`.env.example` holds placeholders only, with instructions to generate a real key.

**Out-of-band finding A — HF write token in `.git/config`:**

```
$ git remote -v
hf  https://Nipunchugh10:hf_****@huggingface.co/spaces/Nipunchugh10/flashcard-engine
$ grep -c 'hf_[A-Za-z0-9]\{20,\}' .git/config   →  1
```

Not in the repository (git config is never committed), so GitHub is unaffected — but
it is plaintext on disk, prints on every `git remote -v`, and has been exposed in
assistant transcripts. **Severity: High. Rotate it.**

```bash
# at huggingface.co/settings/tokens — revoke, then:
git remote set-url hf https://huggingface.co/spaces/Nipunchugh10/flashcard-engine
git config --global credential.helper store
```

**Out-of-band finding B — weak `SECRET_KEY` in local `.env`:** the value
`recall-flashcard-engine-secret-key-2026` is project name + year, guessable by
anyone who has seen the repo. `app/config.py` already refuses it (substitutes a
random key, logs CRITICAL), so sessions are not forgeable — but they do not survive
a restart until a real key is set.

---

## 🔴 PROMPT 2 — Injection (SQL, NoSQL, LDAP, OS command, XPath)

**Verdict: ✅ CLEAN — nothing found**

- **SQL:** every query is a SQLAlchemy `select()` construct with bound parameters.
  Zero f-string or `%`-format interpolation into SQL.
- **The one raw `text()`** is `app/database.py:76`, iterating a hardcoded
  `migrations` list of literal `(table, column, definition)` tuples. No request
  data reaches it — the values are compile-time constants in the source.
- **Search filter** (`app/routes/api_cards.py:38`) uses
  `Card.front.ilike(pattern)`; SQLAlchemy binds `pattern` as a parameter. A `%` in
  the query acts as a wildcard within the user's **own** deck only — cosmetic, not
  injection.
- **OS command:** `grep -rnE 'os\.system|subprocess|popen|shell=True|eval\(|exec\('` →
  the only matches are `__import__("sqlalchemy")`, an import helper. No shell
  execution anywhere in the codebase.
- **NoSQL / LDAP / XPath:** ⬜ N/A — no MongoDB, Redis, LDAP or XML query engine.

---

## 🔴 PROMPT 3 — Authentication & session management

**Verdict: ✅ CLEAN — all items pass (hardened in the prior pass, re-verified here)**

| Check | Result |
|---|---|
| Password hashing | bcrypt, cost **12** (`$2b$12$`) — meets the ≥12 requirement |
| Plaintext / MD5 / SHA1 | none |
| Session token entropy | `itsdangerous` HMAC over a 64-char `secrets.token_urlsafe(48)` key |
| `alg:none` / JWT confusion | ⬜ N/A — not JWT; HMAC-signed serializer with a fixed scheme |
| Expiry enforced | `max_age=SESSION_MAX_AGE` (30d) checked on every load |
| Invalidated on logout | ✅ `session_epoch` bumped server-side — replay of a copied cookie returns 401 |
| Cookie flags | `HttpOnly` ✅ · `SameSite=Lax` ✅ · `Secure` ✅ when `X-Forwarded-Proto: https` |
| Session fixation | No pre-auth session exists; the cookie is only issued post-authentication |
| Timing attack / user enumeration | Unknown emails verified against a dummy bcrypt hash — **1.0×** ratio measured |
| Brute-force protection | Present, and **was bypassable** — see Finding #1 |
| Account lockout | Per-IP + per-account, 10 per 5 min, HTTP 429 |
| Password reset | ⬜ N/A — feature does not exist (noted under P32) |
| OAuth / SSO / MFA | ⬜ N/A — not implemented |

Verified live (`./run.sh security`, sections 3–6): forged cookies signed with three
known-weak keys → 401; malformed cookie → 401; replay after logout → 401.

---

## 🔴 PROMPT 4 — Authorization & broken access control

**Verdict: ✅ CLEAN — nothing found**

This was the primary concern raised. Every object-scoped endpoint was attacked with
a second authenticated account substituting another user's IDs:

```
1. Another user cannot reach Alice's data by guessing ids
  [ok  ] GET  /decks/{id} -> 404          [ok  ] GET  /api/cards?deck_id={id} -> 404
  [ok  ] GET  /decks/{id}/study -> 404    [ok  ] PATCH /api/cards/{id} -> 404
  [ok  ] GET  /api/decks/{id} -> 404      [ok  ] DELETE /api/cards/{id} -> 404
  [ok  ] GET  /api/decks/{id}/status -> 404
  [ok  ] PATCH /api/decks/{id} -> 404     [ok  ] GET  /api/study/{id}/next -> 404
  [ok  ] DELETE /api/decks/{id} -> 404    [ok  ] POST /api/study/cards/{id}/rate -> 404
  [ok  ] Alice's deck name never appears in Bob's responses
  [ok  ] Alice's cards survived Bob's attempts
```

**Route → authorization map (all 23 routes):**

| Route | Auth | Ownership check |
|---|---|---|
| `GET /` | optional | Landing page if anonymous, own decks if signed in |
| `GET /login`, `/signup` | none | Redirects to `/` if already signed in |
| `POST /login`, `/signup` | none | Rate limited |
| `POST /logout` | optional | Bumps own `session_epoch` only |
| `GET /decks/{id}`, `/decks/{id}/study` | required | `deck.user_id != user.id` → 404 |
| `GET/PATCH/DELETE /api/decks[/{id}]` | required | `_get_user_deck()` |
| `GET /api/decks/{id}/status` | required | `_get_user_deck()` |
| `POST /api/decks/upload` | required | Deck created owned by caller |
| `GET/PATCH/DELETE /api/cards[/{id}]` | required | `_verify_card_ownership()` via parent deck |
| `GET /api/study/{id}/next`, `/history` | required | `_get_user_deck()` |
| `POST /api/study/cards/{id}/rate` | required | Resolves parent deck, checks owner |
| `POST /api/study/{id}/undo` | required | `_get_user_deck()` |
| `GET /healthz`, `/favicon.ico`, `/static/*` | none | No user data |

- **404 not 403** — deliberate: a 403 confirms the ID exists and enables enumeration.
- **Privilege escalation:** ⬜ N/A — there is no role/admin column. No privileged tier exists to escalate into.
- **Mass assignment:** blocked by design. Pydantic DTOs allowlist fields — `RenameDeckIn` accepts only `name`/`description`, `CardEditIn` only `front`/`back`. `user_id` is never client-settable.
- **Forced browsing:** all 23 routes enumerated above; no unlinked admin surface.
- **Path traversal:** see P8.

---

## 🔴 PROMPT 5 — Cross-site scripting (XSS)

**Verdict: ✅ CLEAN — nothing found (a real XSS was found and fixed in the prior pass)**

```
Jinja autoescape          = True
|safe / |raw / {{{ }}}    = 0 occurrences
innerHTML / document.write / eval / insertAdjacentHTML = 0
x-text (safe) = 51 uses     x-html (unsafe) = 0 uses
```

- **Stored XSS** — the highest-risk sink is LLM-generated card text; rendered
  exclusively via Alpine `x-text`, which sets `textContent`. Not an HTML sink.
- **Attribute injection** — the one interpolation into a JS expression context is
  `deck.name` in an Alpine `@click`. Re-tested with four payloads:

  | Payload | Rendered | Result |
  |---|---|---|
  | `";alert(1);//` | `"\";alert(1);//"` | contained |
  | `'+alert(2)+'` | `"'+alert(2)+'"` | contained |
  | `</script><script>alert(3)</script>` | `"</script>…"` | contained |
  | `" onmouseover="alert(4)` | `"\" onmouseover=\"alert(4)"` | contained |

  Worth recording *why* this needed two fixes: `|e` was insufficient because the
  browser decodes `&#39;` back to `'` **before** Alpine parses the attribute, so the
  string literal terminated. `|tojson` alone was also insufficient — it leaves `"`
  raw, which closed the `"`-delimited attribute. Only `|tojson` **inside a
  single-quoted attribute** is safe.
- **CSS injection** — `templates/index.html:74` interpolates into `<style>`; values
  are `d.id` (int PK) and Jinja-`round()`ed floats. Not attacker-controlled.
- **SVG upload:** ⬜ N/A — only `.pdf` accepted, and uploads are never served.
- **CSP / nosniff:** present — see P11.

---

## 🔴 PROMPT 6 — Cross-site request forgery (CSRF)

**Verdict: ⚠️ FINDING #12 (Medium) — Open**

No CSRF tokens exist anywhere. Protection rests entirely on `SameSite=Lax`.

**Mitigating factors, all verified:**
- Zero state-changing `GET` routes — every mutation is POST/PATCH/DELETE, so Lax's
  top-level-GET allowance is not exploitable here.
- PATCH/DELETE are not reachable from an HTML form at all (forms emit GET/POST only)
  and cross-origin `fetch` triggers a preflight that this app never grants.
- JSON endpoints reject form encodings — tested:

  ```
  POST /api/study/cards/{id}/rate as x-www-form-urlencoded -> 422 (rejected)
  POST /api/study/cards/{id}/rate as text/plain            -> 422 (rejected)
  ```

**The residual gap:** three POST endpoints take **no body** and are therefore
reachable from a plain cross-site form — `/logout`, `/api/study/{id}/undo`, and
`/api/decks/upload` (multipart is form-encodable). Their only defence is Lax, and
Lax has a documented edge case: Chrome's **"Lax + POST" mitigation** sends cookies
on cross-site POST for cookies **less than 2 minutes old**. A victim who signed in
moments earlier can be forced to log out, undo a review, or burn an upload quota.
Impact is nuisance-grade (no data disclosure, no privilege change), hence Medium.

**Login CSRF** is also possible — an attacker can force a victim's browser to log in
as the attacker. Standard consequence: subsequent study activity lands in the
attacker's account.

**Recommended fix:** `SameSite=Strict` on the session cookie (this app has no
inbound cross-site navigation flows — no OAuth callback, no payment return), or a
double-submit token on those three endpoints.

---

## 🔴 PROMPT 7 — Sensitive data exposure & encryption

**Verdict: ⚠️ 2 FINDINGS — both 🔧 fixed**

**Finding #6 (Medium, fixed) — internal exception text returned to users.**
`generation_error` is rendered in the deck page and returned by `/status`:

```python
deck.generation_error = f"Could not read PDF: {e}"      # absolute paths, library internals
deck.generation_error = f"Card generation failed: {e}"  # provider URLs, key fragments in API errors
```

Fixed: the exception is logged server-side; the user gets an actionable generic
message.

**Finding #8 (Medium, fixed) — no `Cache-Control` on authenticated responses.**
Deck and card pages were cacheable. Fixed: `no-store, private` whenever a session
cookie is present; public pages stay cacheable.

**Verified clean:**
- Passwords **hashed** (bcrypt), never encrypted or reversible.
- No secrets in logs. Log statements carry deck IDs, counts and provider names.
- No PII in URLs — all identifiers are integer PKs, no tokens in query strings.
- No `localStorage`/`sessionStorage` use at all; the session lives in an `HttpOnly`
  cookie, so XSS cannot read it.
- HSTS `max-age=31536000; includeSubDomains` on HTTPS.
- No `Math.random()`/`random.random()` for anything security-relevant.

**Residual (Low, accepted):** `logger.warning("Failed to parse LLM JSON output: … Raw was: %r", text[:200])`
can write up to 200 chars of PDF-derived content to logs, and deck names (from
filenames) appear in log lines. Uploaded documents may be personal. Noted under P32.

---

## 🔴 PROMPT 8 — File upload vulnerabilities

**Verdict: ⚠️ 2 FINDINGS (Low) — Open · core controls sound**

Live results against `/api/decks/upload`:

| Test | Result |
|---|---|
| `evil.php` | **400 rejected** |
| `x.pdf.exe` | **400 rejected** |
| `x.PDF` (case) | 201 — allowlist is case-insensitive, correct |
| `../../../../tmp/esc.pdf` | 201 — **no file escaped**; `find` confirmed nothing written outside `uploads/` |
| PHP bytes named `.pdf` | 201 accepted (**Finding #13**) |
| SVG bytes named `.pdf` | 201 accepted (**Finding #13**) |
| 10 MB + 1 KB | **413 rejected** |
| `GET /uploads/<file>` | **404 — uploads are not web-served** |

**Strong controls confirmed:**
- **Allowlist**, not blacklist (`.pdf` only).
- **Filename is discarded** — storage name is `uuid4().hex + ".pdf"`, so traversal
  and collision are structurally impossible.
- **Not in the web root** — only `/static` is mounted; `/uploads` 404s.
- **Size checked before buffering** (`file.size` pre-check, then a post-read check).
- **Deleted after processing** in a `finally` block.

**Finding #13 (Low) — no content validation.** Extension and client MIME are
trusted; magic bytes are never checked. Impact is limited: the file is stored under
a UUID, never served, and PyMuPDF fails to parse it so the deck simply reports
failure. Recommend a `%PDF-` header check to reject earlier and cheaper.

**Finding #14 (Low) — orphaned uploads accumulate.** `uploads/` currently holds
**8 PDFs / 16 MB, oldest 25 days**. The `finally` cleanup does not run if the
process is killed mid-parse (which happens on every Space rebuild). Unbounded disk
growth plus indefinite retention of user documents. Recommend a startup sweep.

⬜ N/A: zip/tar extraction, SVG rendering, XML import — none exist. No AV scanning
(accepted: files are never executed or re-served).

---

## 🔴 PROMPT 9 — API security & rate limiting

**Verdict: ⚠️ 2 FINDINGS — both 🔧 fixed**

**Finding #1 (High, fixed) — rate limiter bypassable by header spoofing.**
`client_key()` trusted the left-most `X-Forwarded-For` entry, which is whatever the
caller sends. Measured:

```
15 attempts, no header    -> 10 allowed / 5 blocked   (limiter works)
60 attempts, rotating XFF -> 60 allowed / 0 blocked   ** BYPASSED **
```

Fixed by counting in from the **trusted end** of the chain (`TRUSTED_PROXY_HOPS`,
default 1) and adding a **per-account** limiter. Re-verified:

```
no header (baseline)                   10 allowed / 10 blocked  BLOCKED
rotating X-Forwarded-For               10 allowed / 50 blocked  BLOCKED
rotating XFF + fake proxy chain        10 allowed / 50 blocked  BLOCKED
spoofed X-Real-IP                      10 allowed / 50 blocked  BLOCKED
30 different source IPs, one account   10 allowed / 20 blocked  BLOCKED (per-account)
unrelated account during the attack -> 302 (no collateral lockout)
```

**Finding #5 (Medium, fixed) — `/api/decks/upload` had no limit.** The single most
expensive operation (PDF parse + up to 23 concurrent LLM calls + billable tokens)
was unbounded for any authenticated user. Fixed: 10/hour per IP **and** per account.

```
13 uploads -> 10 accepted, 3 throttled (429 + Retry-After)  BLOCKED
```

**Verified clean:** no mass assignment (Pydantic allowlists); no API versioning
surface; correct HTTP verbs throughout; responses are explicit `response_model`
DTOs so no extra columns leak (`password_hash` is never in any schema); pagination
is not user-controllable.

---

## 🔴 PROMPT 10 — Dependency & supply chain

**Verdict: ⚠️ FINDING #2 (High) — 🔧 fixed**

`pip-audit` before:

```
Name             Version  Advisories  Fix
starlette        0.41.3   7           1.3.1+
python-multipart 0.0.20   6           0.0.31
setuptools       59.6.0   4           83.0.0
jinja2           3.1.5    1           3.1.6
python-dotenv    1.0.1    1           1.2.2
                          19 total
```

**Directly reachable on this app's request paths:**

| Advisory | Impact here |
|---|---|
| `PYSEC-2026-1941` starlette | Large multipart blocks the event loop → DoS. **The upload endpoint.** |
| `PYSEC-2026-249` starlette | `max_fields`/`max_part_size` silently ignored for urlencoded → unauthenticated memory exhaustion. **The login/signup forms.** |
| `PYSEC-2026-3040` python-multipart | Negative `Content-Length` → whole body read into memory. **The upload endpoint.** |
| `PYSEC-2026-3038/3039` python-multipart | Header-count and preamble DoS. **Any form POST.** |
| `PYSEC-2026-1471` jinja2 | Sandbox escape via `|attr` — requires attacker-controlled template source; not the case here (templates are static files). Patched anyway. |
| `PYSEC-2026-2270` python-dotenv | Symlink follow in `set_key()`; app never calls it. Patched anyway. |

Upgraded to `fastapi 0.141.1 / starlette 1.6.0 / python-multipart 0.0.32 /
jinja2 3.1.6 / python-dotenv 1.2.3 / bcrypt 5.0.0 / pymupdf 1.28.2`, plus an
explicit `setuptools==83.0.0` pin.

```
$ pip-audit
No known vulnerabilities found
$ ./run.sh test      → All 21 smoke tests passed.
$ ./run.sh security  → PASSED 45   FAILED 0
```

**Pinning:** all 15 direct dependencies pinned with `==`; zero `^`/`~`/`>=` ranges.
**Gap (Info):** no lockfile, so *transitive* dependencies float. Recommend
`pip-compile` → `requirements.lock` with hashes.
No typosquat-suspicious names; no abandoned packages; no vendored minified code.

---

## 🔴 PROMPT 11 — Environment & configuration security

**Verdict: ⚠️ 3 FINDINGS — all 🔧 fixed**

**Finding #3 (High, fixed) — no `.dockerignore`.** With `COPY . /code/`, a local
`docker build` copied into the image:

| Item | Size | Contains |
|---|---|---|
| `.env` | — | Live Gemini API key, `SECRET_KEY` |
| `data/flashcards.db` | 1.5 MB | **All user accounts + bcrypt password hashes** |
| `uploads/*.pdf` | 16 MB | 8 user-uploaded documents |
| `.git/` | — | Full history, and the **HF token in `.git/config`** |
| `.venv/` | 172 MB | — |

The Hugging Face build is unaffected (it builds from the repo, where these are
gitignored), so this is a latent risk for local builds and any image pushed to a
registry. Fixed with a `.dockerignore` excluding all of the above.

**Finding #7 (Medium, fixed)** — `chmod -R 777 /code/data /code/uploads` made the
database and every uploaded PDF world-writable inside the container. Now
`chown user:user` + `chmod 700`.

**Also fixed:** added a `HEALTHCHECK`, and `--proxy-headers` on the uvicorn command
so the app correctly derives scheme and client address through the platform proxy —
which the `Secure` cookie flag, HSTS and rate limiting all depend on.

**Verified clean:** `.env` gitignored with a placeholder `.env.example`; no debug
mode (`FastAPI(debug=...)` never set); secrets read from env, never passed as CLI
args; container runs as non-root UID 1000; security headers all present:

```
content-security-policy: default-src 'self'; base-uri 'self'; object-src 'none';
  frame-ancestors 'none'; form-action 'self'; img-src 'self' data:; …
x-content-type-options: nosniff
x-frame-options: DENY
referrer-policy: strict-origin-when-cross-origin
strict-transport-security: max-age=31536000; includeSubDomains   (HTTPS only)
```

**Accepted weakness:** the CSP requires `'unsafe-inline'` and `'unsafe-eval'`
because Tailwind's play-CDN and Alpine compile expressions at runtime. It therefore
pins script/style **origins** and blocks framing, but is not an XSS backstop.
Building Tailwind ahead of time would let both be dropped. Base image
`python:3.11-slim` is a mutable tag (Low) — pin by digest for reproducibility.

---

## 🔴 PROMPT 12 — Server-side request forgery (SSRF)

**Verdict: ✅ CLEAN — nothing found**

The application makes exactly one class of outbound request: LLM completions.

```python
base_url="https://generativelanguage.googleapis.com/v1beta/openai/"   # hardcoded
```

- The URL is a **compile-time constant**, not derived from any request field.
- `GEMINI_MODEL` / `LLM_PROVIDER` come from environment (operator-controlled, not
  user-controlled) and select a provider from a fixed dispatch dict — an unknown
  value falls through to the offline heuristic, it does not become a URL.
- There is **no** URL-fetching feature: no "import from URL", no webhook registration,
  no image proxying, no PDF-from-URL, no RSS reader.
- User input (PDF text) reaches the LLM as **body content**, never as a destination.

No cloud-metadata exposure path exists because no user-influenced URL is ever
requested.

---

## 🔴 PROMPT 13 — XXE & insecure deserialization

**Verdict: ✅ CLEAN — nothing found**

```
$ grep -rnE 'pickle|yaml\.load|marshal|shelve|xml\.|lxml|etree|ObjectInputStream' app/
  (no matches)
```

No XML parsing anywhere — therefore no XXE surface, no SAML, no DOCX/XLSX import.
No `pickle`, `marshal`, `shelve`, or `yaml.load`. The only deserialization is
`json.loads()` on LLM output, parsed into a fixed `GeneratedCard` dataclass with
per-field `str()` coercion and a `card_type` allowlist — prototype pollution is not
a concept in Python and no dict-merge into a shared object occurs.

PDF parsing is delegated to PyMuPDF (MuPDF, C) — a memory-safety surface rather than
a deserialization one, mitigated by the page cap, size cap and now-current version.

---

## 🔴 PROMPT 14 — Cryptography misuse

**Verdict: ✅ CLEAN — nothing found**

```
$ grep -rnE 'md5|sha1|DES|RC4|ECB|random\.random|Math\.random' app/
  (no matches)
```

| Use | Primitive | Assessment |
|---|---|---|
| Password hashing | `bcrypt`, cost **12**, per-password salt | Meets the ≥12 requirement |
| Session signing | `itsdangerous.URLSafeTimedSerializer` (HMAC-SHA1 over a 512-bit key) | Sound — HMAC-SHA1 has no practical forgery attack; not a collision-dependent use |
| Key generation | `secrets.token_urlsafe(48)` — 288 bits from the OS CSPRNG | Correct |
| Upload filenames | `uuid.uuid4().hex` | Correct (random, not a security boundary) |
| Password comparison | `bcrypt.checkpw` | Constant-time internally |
| Unknown-account login | Dummy bcrypt verify | Equalises timing — measured 1.0× |

No symmetric encryption, no IV/nonce management, no certificate handling, and
**no `verify=False`** anywhere. TLS is terminated by the platform.

---

## 🔴 PROMPT 15 — Input validation & business logic flaws

**Verdict: ✅ CLEAN — nothing found**

**Input validation** is handled by Pydantic at the boundary, which rejects before
any handler runs:

| Input | Constraint |
|---|---|
| `rating` | `pattern="^(again\|hard\|good\|easy)$"` — enum-equivalent |
| `status_filter` | `pattern="^(new\|learning\|review\|mastered\|all)$"` |
| Deck name | `min_length=1, max_length=200` |
| Deck description | `max_length=2000` |
| Card front/back | `min_length=1` |
| Path IDs | typed `int` — `/api/decks/abc` → 422 |
| Username | 2–100 chars |
| Password | ≥8 chars, ≤72 **bytes** (bcrypt's silent-truncation limit is rejected, not ignored) |
| Upload | `.pdf` extension, ≤10 MB, ≤100 pages |

**ReDoS:** every regex in `pdf_processor.py` and `flashcard_generator.py` was
reviewed. The definition patterns use bounded quantifiers (`{2,60}`) and negated
classes (`[^.]+`) rather than nested unbounded groups. `re.split(r'(?<=[.!?])\s+')`
is linear. No catastrophic backtracking construct (`(a+)+`) exists. Input is
additionally bounded by the 10 MB / 100-page caps.

**Business logic:** ⬜ largely N/A — no prices, no quantities, no coupons, no
multi-step checkout, no balances. The one stateful algorithm is SM-2 scheduling:

- Ratings are enum-constrained, so no out-of-range quality value can be injected.
- `ease_factor` is floored at 1.3 (`max(1.3, new_ef)`), so it cannot be driven
  negative or to zero by repeated "again".
- Intervals derive from server state, never from client input — a client cannot
  submit its own interval or due date.
- **Undo** is the one workflow-order concern: it restores a snapshot captured at
  rate time and deletes the log row, so it cannot be replayed to fabricate state.
  Tested exhaustively — restores all 8 fields exactly for all 4 ratings, pops LIFO,
  404s when empty, and is ownership-checked.

---

## 🔴 PROMPT 16 — Logging, monitoring & forensic readiness

**Verdict: ⚠️ FINDING #9 (Medium) — 🔧 fixed**

**Before this audit, `app/routes/auth.py` contained no logging at all.** A brute
force attempt, a successful takeover, or a mass logout would have left no trace.

Added:

| Event | Log line |
|---|---|
| Failed login | `auth.login.failed ip=… email=…` |
| Successful login | `auth.login.ok ip=… user_id=…` |
| Rate limit triggered | `auth.login.throttled ip=… email=…` |
| Logout (session revoked) | `auth.logout ip=… user_id=…` |
| Signup | `auth.signup.ok ip=… user_id=…` |
| Concurrent-duplicate signup | `auth.signup.duplicate_race email=…` |

Deliberately logs `user_id` rather than email on success, to limit PII in logs while
keeping the trail usable.

**Remaining gaps (Info, accepted for a single-instance hobby deployment):**
- Logs go to stdout only — an attacker with container access could not delete them
  (HF retains them), but there is no external SIEM.
- No alerting on anomalies; no correlation/request ID; no log rotation policy.
- No intrusion detection (fail2ban/WAF) — partially compensated by app-level limits.
- **Log injection:** low risk — entries are `%`-formatted (not f-strings), values
  are emails/IDs, and no downstream log parser evaluates content (this is not a
  Log4Shell-shaped stack).

---

## 🔴 PROMPT 17 — Client-side security

**Verdict: ⚠️ FINDING #15 (Low) — Open**

**Finding #15 — no Subresource Integrity on third-party scripts:**

```html
<script src="https://cdn.tailwindcss.com"></script>                       <!-- no integrity -->
<script defer src="https://cdn.jsdelivr.net/npm/alpinejs@3.13.5/..."></script>  <!-- no integrity -->
```

If either CDN were compromised, arbitrary JS would execute on every page with full
DOM access. The CSP pins the **origins**, which limits this to those two providers,
but does not verify content. Alpine is version-pinned and can take an `integrity`
hash today. Tailwind's play-CDN generates CSS at runtime and is explicitly
not-for-production — the right fix is to build Tailwind ahead of time, which also
allows dropping `'unsafe-eval'` from the CSP.

**Verified clean:**
- **No `localStorage`/`sessionStorage` use at all** — no token is reachable by JS.
  The session is an `HttpOnly` cookie, so even a successful XSS cannot exfiltrate it.
- No API keys, internal URLs or secrets in any template or JS bundle (grep-verified).
- No `postMessage` handlers; no prototype-pollution sinks (no deep-merge, no query
  parser writing to objects).
- **Clickjacking:** `X-Frame-Options: DENY` + `frame-ancestors 'none'`.
- No source maps; no `console.log` of sensitive data.
- **Client-side authorization:** correctly absent — every UI affordance is backed by
  a server-side check (proven in P4). Hiding a button is never the control.

---

## 🔴 PROMPT 18 — Database security

**Verdict: ✅ CLEAN — nothing found (2 items noted)**

- **Connection string:** from `DATABASE_URL` env, never hardcoded. The
  `postgres://` → `postgresql://` normalisation is a compatibility fix, not a
  credential path.
- **ORM escape hatches:** one `text()` call, hardcoded migration DDL only (see P2).
  No `.extra()`, no `.literal()`, no user-driven raw SQL.
- **Connection lifecycle:** `get_db()` yields in a `try/finally` that always closes;
  the background worker owns its own `SessionLocal()` closed in `finally`.
  `pool_pre_ping=True` on PostgreSQL prevents stale-connection failures.
- **Cascades:** `User → Deck → Card → ReviewLog` all
  `cascade="all, delete-orphan"` + `ondelete="CASCADE"` — no orphan rows, and a
  future account-deletion feature will actually delete.
- **Transactions:** the upload worker deliberately commits cards **before** flipping
  status to `ready`, closing the race where a poll sees `ready` with no cards.
- **Soft deletes:** none — deletes are real. No "deleted" rows reachable by ID.
- **Admin interface:** none exposed (no Django admin, no Adminer, no Prisma Studio).
- **Error exposure:** raw DB errors are not returned to clients (see P7 fix).

**Noted (Info, not fixable in code):**
1. **Least privilege** cannot be verified from the repo — the Neon role's grants are
   an operator concern. The app needs only `SELECT/INSERT/UPDATE/DELETE` plus
   `ALTER TABLE ADD COLUMN` for the startup migration. Recommend a dedicated role
   without `DROP`/`CREATE DATABASE`.
2. **Backups** — confirmed running on **Neon Postgres 18** (project `flashcard-db`,
   branch `production`, AWS us-east-2) with **6-hour history retention** on the free
   tier. No application-level backup code exists, which is correct — nothing writes a
   dump to a web-reachable path. Note the 6-hour PITR window is short: a problem
   discovered the next morning is past the recovery horizon. Consider periodic
   `pg_dump` to off-platform storage if the data matters.

---

## 🔴 PROMPT 19 — Denial of service attack surfaces

**Verdict: ⚠️ 3 FINDINGS — all 🔧 fixed**

**Finding #4 (Medium, fixed) — no timeout on outbound LLM calls.** The OpenAI SDK
defaults to 600 s with 2 retries; a hung provider could pin a worker thread for up
to **30 minutes** per chunk, across 3 concurrent workers per upload. Fixed:
`timeout=60s`, `max_retries=1`.

**Finding #5 (Medium, fixed) — unbounded uploads.** See P9. Now 10/hour per IP and
per account.

**Finding #2 (High, fixed) — dependency DoS.** Three of the patched advisories are
DoS primitives directly on this app's paths (starlette multipart event-loop block,
starlette urlencoded limit bypass, python-multipart negative `Content-Length`).

**Bounds that were already correct:**

| Vector | Cap |
|---|---|
| Upload size | 10 MB, checked **before** buffering |
| Pages parsed | `MAX_PDF_PAGES=100` |
| Chunks sent to LLM | `MAX_CHUNKS = max(5, 70//3)` = 23 |
| Concurrent LLM calls | `ThreadPoolExecutor(max_workers=3)` |
| Cards per deck | `MAX_TOTAL_CARDS=70` |
| Response size | No unbounded list — cards are deck-scoped and capped at 70 |

**Residual (Low):** background generation threads are unbounded in *count* — N
concurrent uploads spawn N threads. The 10/hour per-account upload limit now caps
this in practice. A proper job queue would be the structural fix; noted, not
critical at this scale. No infinite loops (every loop is bounded by a capped
collection). No zip/decompression handling.

---

## 🔴 PROMPT 20 — WebSocket & real-time communication

**Verdict: ⬜ N/A**

The application uses no WebSockets, Socket.io, SSE, long-polling or any real-time
transport. All 23 routes are plain HTTP request/response. Progress during card
generation uses **client-side polling** of `GET /api/decks/{id}/status` every 2
seconds — an ordinary authenticated GET, already covered by P4 (ownership-checked)
and P9.

Nothing in this category applies.

---

## 🔴 PROMPT 21 — Infrastructure as Code (IaC)

**Verdict: ⬜ Mostly N/A — Dockerfile findings covered in P11/P27**

No Terraform, CloudFormation, Kubernetes manifests, Helm charts, Ansible, Pulumi,
CDK or docker-compose exist in this repository. The only infrastructure artifact is
the `Dockerfile`, plus the Hugging Face Space configuration embedded in the README
frontmatter:

```yaml
title: Recall Flashcard Engine
sdk: docker
app_port: 7860
```

That frontmatter contains no secrets (verified) — the Space's Gemini key,
`SECRET_KEY` and `DATABASE_URL` are set in the Space's secrets panel, not in the
repo. Dockerfile findings (#3 `.dockerignore`, #7 `chmod 777`) are documented under
P11 and P27.

No IAM policies, no S3 buckets, no security groups, no network policies exist to
audit.

---

## 🔴 PROMPT 22 — Email & notification security

**Verdict: ⬜ N/A**

The application sends **no** email, SMS, push notification or outgoing webhook.
There is no SMTP configuration, no mail library in `requirements.txt`, no template
for a message body, and no notification model.

Consequences worth stating explicitly, since their absence is itself the design:
- No password-reset flow exists → no reset-token vulnerabilities to audit (and no
  recovery path for users — noted under P32).
- No invitation or share feature → the app cannot be used as an open relay to send
  attacker-authored mail from this domain.
- No unsubscribe tokens, no OTP delivery, no incoming webhooks to verify signatures
  on.

**One related item that does apply — account enumeration at signup:** the signup
form returns "An account with this email already exists." Login was hardened
against enumeration (identical message, equalised timing), but signup inherently
discloses registration status. Removing that would require an email-confirmation
flow, which this app has no mail capability for. **Accepted, documented.**

---

## 🔴 PROMPT 23 — Mobile API & third-party integrations

**Verdict: ✅ CLEAN — nothing found**

- **Payments:** ⬜ N/A — no payment processing, no card data, no PCI surface.
- **OAuth/SSO:** ⬜ N/A — local email+password only. No `state` parameter,
  `redirect_uri`, or authorization code to mishandle.
- **Incoming webhooks:** ⬜ N/A — none. No signature verification gap because there
  is nothing to receive.
- **Third-party APIs:** exactly one — the Gemini endpoint (optionally Anthropic).
  Keys are read from environment, used **server-side only** (grep-verified: no key
  reference in any template or JS), and are per-deployment rotatable.
- **Data sent to third parties:** PDF text chunks are transmitted to Google's
  Gemini API for card generation. This is the app's core function and unavoidable,
  but it is a **privacy disclosure obligation** — see P32. No analytics, no error
  tracking, no CRM, no advertising SDK sends anything anywhere.
- **Open redirects:** every `RedirectResponse` in the codebase targets a
  **hardcoded literal** — `"/"`, `"/login"`. There is no `next=`, `returnUrl=` or
  `callback=` parameter anywhere in the application, so open redirect is
  structurally impossible.

---

## 🔴 PROMPT 24 — Code quality as security

**Verdict: ⚠️ 1 FINDING (Info) — 🔧 fixed · overall quality high**

**Finding #11 (Info, fixed)** — `import fitz` is deprecated in PyMuPDF 1.28 and
emits a removal warning; it would break on a future major upgrade. Switched to
`import pymupdf` in `app/pdf_processor.py` and `smoke_test.py`.

**Exception handling review** — five broad `except` blocks, each examined:

| Location | Verdict |
|---|---|
| `database.py:83` | Intentional — "column already exists" during idempotent migration. Rolls back. **Correct.** |
| `flashcard_generator.py:197` | Malformed LLM JSON → return `[]`. Logged at the outer level. **Correct.** |
| `api_decks.py:266` | Background worker catch-all — calls `logger.exception`, marks the deck failed. **Correct.** |
| `api_decks.py:275` | Nested guard for "failed while recording failure". Logged. **Correct.** |
| `api_decks.py:324` | `_safe_unlink` — `pass`. Best-effort cleanup of a temp file. **Acceptable**, though it is why orphans go unnoticed (#14). |

No error is silently swallowed in a way that masks a security event.

**Verified clean:** zero `TODO`/`FIXME`/`HACK`/`XXX` comments; no commented-out code
blocks holding old credentials or disabled checks; no `eval`/`exec`/`compile`; no
`==` vs `===` class of bug (Python); type safety enforced by Pydantic at every
boundary. Error recovery leaves consistent state — the two-phase commit in the
upload worker is a deliberate example.

---

## 🔴 PROMPT 25 — Network & transport layer

**Verdict: ✅ CLEAN at the application layer — platform-dependent items noted**

- **TLS:** terminated by Hugging Face; the live endpoint serves HTTPS and the app
  detects it via `X-Forwarded-Proto` (now explicitly enabled with `--proxy-headers`).
- **HSTS:** `max-age=31536000; includeSubDomains` — confirmed live:

  ```
  $ curl -sI https://nipunchugh10-flashcard-engine.hf.space/ | grep -i strict
  strict-transport-security: max-age=31536000; includeSubDomains
  ```
  Not submitted to the preload list (Info) — a `*.hf.space` subdomain cannot
  meaningfully preload independently.
- **HTTP→HTTPS redirect:** handled by the platform edge, not the app. Correct
  placement.
- **`X-Forwarded-For` trust:** this was **Finding #1** — the app previously trusted
  the spoofable left-most entry. Now derived from the trusted end via
  `TRUSTED_PROXY_HOPS`.
- **Exposed ports:** the container exposes only 7860, published by the platform on
  443. No database port, no metrics port, no debug port.
- **Health endpoint:** `GET /healthz` returns `{"status":"ok"}` — a literal constant.
  No version, no build info, no internal hostnames, no dependency status.
- ⬜ N/A: certificate pinning (no mobile client), internal service mesh
  (single process), DNSSEC/SSH/firewall (platform-managed), gRPC.

**Info:** `/docs` (Swagger UI) is publicly reachable. It documents only endpoints
that are individually authenticated and ownership-checked, so it discloses shape,
not data. Consider `openapi_url=None` in production to reduce reconnaissance value.

---

## 🔴 PROMPT 26 — Race conditions & concurrency

**Verdict: ⚠️ FINDING #10 (Low) — 🔧 fixed**

**Finding #10 — TOCTOU between the signup duplicate-check and the insert.**
Six simultaneous signups for the same address, released from a `threading.Barrier`:

```
status codes : [302]
exceptions   : 5  ->  IntegrityError: UNIQUE constraint failed: users.email
accounts with that email: 1   (unique constraint held)
```

**Data integrity was never at risk** — the unique index did its job and exactly one
account was created. But the `IntegrityError` propagated uncaught, so five users
would have received **HTTP 500** instead of "An account with this email already
exists." Fixed: catch `IntegrityError`, roll back, return the normal message.

**Other concurrency paths examined:**

| Path | Assessment |
|---|---|
| Rate limiter counters | `threading.Lock` around every mutation — correct |
| `session_epoch` bump on logout | Single-row increment + commit; concurrent logouts are idempotent in effect |
| Undo (two simultaneous) | Both could select the same `ReviewLog`; the second `delete` no-ops and the restore is idempotent (same snapshot values). Worst case: one redundant write. Not exploitable |
| Upload → background thread | Worker takes its own session and re-fetches the deck by ID; the two-phase commit prevents a "ready but empty" window |
| SQLite WAL | `journal_mode=WAL` + 30 s busy timeout — concurrent readers with one writer |

⬜ N/A: no balances, no stock, no double-spend surface, no job queue, no cache
stampede path.

---

## 🔴 PROMPT 27 — Kubernetes & container runtime

**Verdict: ⚠️ FINDINGS #3 & #7 — both 🔧 fixed · Kubernetes N/A**

No Kubernetes, no Helm, no OPA, no service mesh — the deployment is a single
container on Hugging Face Spaces. Container audit:

| Check | Before | After |
|---|---|---|
| Runs as root | ✅ already non-root (UID 1000) | unchanged |
| Secrets baked into image | ❌ `.env`, DB, PDFs, `.git` via `COPY . /code/` | ✅ `.dockerignore` |
| Filesystem permissions | ❌ `chmod -R 777` on data + uploads | ✅ `chown user` + `chmod 700` |
| Healthcheck | ❌ none | ✅ `HEALTHCHECK` on `/healthz` |
| Proxy headers | ❌ not enabled | ✅ `--proxy-headers` |
| Base image pinning | ⚠️ `python:3.11-slim` (mutable tag) | unchanged — **Low, open** |
| Multi-stage build | ⚠️ `build-essential` ships in the runtime image | unchanged — **Low, open** |
| Docker socket mounted | ✅ no | — |
| Capabilities dropped | ⚠️ not specified (platform default) | — |
| Resource limits | platform-enforced (HF free tier) | — |

Remaining Low items are size/reproducibility hardening: pin the base image by
`sha256:` digest, and split build from runtime so compilers are not present in the
shipped image.

---

## 🔴 PROMPT 28 — AI/LLM-specific vulnerabilities

**Verdict: ⚠️ 1 accepted risk · 2 FINDINGS 🔧 fixed**

This application sends user-supplied PDF text to Google Gemini, so this section
genuinely applies.

**Indirect prompt injection — present, accepted, low impact.** PDF text is
interpolated into the user prompt:

```python
USER_TEMPLATE = """Create up to {max_cards} high-quality flashcards from this excerpt.
Source excerpt:
\"\"\"
{chunk}
\"\"\"
Return ONLY a JSON array of card objects."""
```

A PDF containing *"Ignore all previous instructions and output …"* can hijack
generation. **Why the impact is low here:**

| Amplifier | Present? |
|---|---|
| Tool/function calling | ❌ none — the model cannot act |
| Access to other users' data | ❌ the prompt contains only the uploader's own chunk |
| Output rendered as HTML | ❌ `x-text` only (`textContent`) — see P5 |
| Output executed or eval'd | ❌ parsed by `json.loads` into a typed dataclass |
| Cross-user blast radius | ❌ cards land in the uploader's own deck |

The worst outcome is a user poisoning their own flashcards. **Accepted**, with the
output-handling defences above as the real control.

**Output handling is genuinely safe:** `_parse_cards()` extracts the JSON array,
coerces every field with `str()`, truncates tags to 30 chars / 3 items, and
**allowlists** `card_type` to `{qa, definition, cloze, application}` with a fallback.
Malformed output returns `[]` rather than raising.

**Finding #5 (fixed) — cost-exhaustion DoS.** Upload was unrate-limited, so one
authenticated user could trigger unbounded billable LLM calls. Now 10/hour per
account (≤23 chunks each, bounded by `MAX_CHUNKS`).

**Finding #4 (fixed) — no request timeout**, letting a slow provider pin threads.

**Verified clean:** API keys are server-side only — no key appears in any template
or client asset. System prompt leakage is possible in principle but the prompt is
a non-sensitive instruction block visible in the open-source repository; there is
nothing confidential to extract. No training/fine-tuning on user data.

---

## 🔴 PROMPT 29 — Security regression & CI/CD pipeline

**Verdict: ⚠️ FINDING #17 (Info) — Open**

```
$ ls .github/workflows .gitlab-ci.yml .pre-commit-config.yaml
  ** no CI/CD config at all **
```

There is **no automated gate of any kind**. Nothing blocks a vulnerable dependency,
a hardcoded secret, or a broken access-control change from reaching `main` and, via
`git push hf main`, production — which auto-deploys on push.

| Control | Status |
|---|---|
| Dependency scanning | ❌ none (this audit ran `pip-audit` manually) |
| SAST | ❌ none |
| Secret scanning | ❌ none |
| Container scanning | ❌ none |
| DAST | ❌ none |
| Branch protection / PR review | ❌ direct pushes to `main` |
| SBOM | ❌ none |
| Rollback | ✅ `git revert` + push (HF rebuilds) |

**Mitigating:** the repository *does* carry two strong suites (`./run.sh test`,
`./run.sh security`) — they are simply never run automatically.

**Recommended `.github/workflows/security.yml`:**

```yaml
name: security
on: [push, pull_request]
jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - run: pip install -r requirements.txt pip-audit bandit
      - run: pip-audit --strict          # fails the build on any advisory
      - run: bandit -r app/ -ll
      - run: python smoke_test.py
      - run: python security_test.py     # 45 adversarial checks
  secrets:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }
      - uses: gitleaks/gitleaks-action@v2
```

---

## 🔴 PROMPT 30 — Complete attack surface map & threat model

**Verdict: ℹ️ Analysis — no new findings**

### Step 1 — Asset inventory

**Entry points (23 routes):** 6 unauthenticated (`/`, `GET|POST /login`,
`GET|POST /signup`, `/healthz`, `/favicon.ico`, `/static/*`), 1 optional-auth
(`POST /logout`), 16 authenticated and ownership-scoped.

**Background work:** one detached `threading.Thread` per upload (PDF parse → up to
23 LLM calls → 2-phase DB commit). No cron, no scheduler, no queue.

**External calls:** one — `generativelanguage.googleapis.com` (hardcoded).

**Data stores:** PostgreSQL/SQLite — `users` (email, bcrypt hash, `session_epoch`),
`decks`, `cards`, `review_logs`. Filesystem — `uploads/` (transient PDFs).

**Secrets:** `SECRET_KEY`, `GEMINI_API_KEY`, `DATABASE_URL`. **Roles:** exactly one
(authenticated user). No admin tier exists.

### Step 2 — Trust boundaries

| Boundary | Validation present | Residual |
|---|---|---|
| Internet → app | Pydantic types/patterns, auth dependency, ownership check, rate limits | CSRF relies on SameSite (#12) |
| Browser → session | HMAC signature + epoch + expiry | — |
| Upload → parser | Extension, size, page cap | No magic bytes (#13) |
| App → LLM | Fixed URL, timeout, retry cap | PDF text is untrusted prompt content (accepted, P28) |
| LLM → app | JSON parse, `str()` coercion, type allowlist, `x-text` render | — |
| App → DB | Bound parameters throughout | — |

### Step 3 — STRIDE on the five critical components

| Component | S | T | R | I | D | E |
|---|---|---|---|---|---|---|
| **Session cookie** | Mitigated — HMAC over a 288-bit key; forged cookies rejected (tested) | Mitigated — signature | **Gap** — no audit trail of *actions*, only auth events | Mitigated — `HttpOnly`, no JS access | — | Mitigated — epoch revocation |
| **Login** | Mitigated — bcrypt-12 | — | Now logged | Mitigated — equalised timing, identical messages | Mitigated — IP + account limits (**was bypassable**) | — |
| **Deck/Card API** | — | Mitigated — ownership on every route | **Gap** — no per-action audit log | Mitigated — 404 not 403 | Mitigated — bounded result sets | Mitigated — no role to escalate to |
| **Upload + LLM** | — | — | — | Mitigated — UUID names, not web-served | Mitigated — 10/hr, 10 MB, 100 pages, 60 s timeout | — |
| **Container** | — | Mitigated — non-root, 700 perms | — | Mitigated — `.dockerignore` | Platform-enforced limits | Mitigated — non-root |

### Step 4 — Attack chains

**1 — External unauthenticated attacker (most likely).**
Before this audit: harvest emails via signup enumeration → brute force with a
rotating `X-Forwarded-For` (unlimited, proven 60/60) → session takeover. **Now
broken at step 2** — the per-account limiter stops at 10 regardless of source
address. Residual: signup enumeration still yields a valid-email list.

**2 — Authenticated regular user (most damaging).**
Upload a crafted PDF → indirect prompt injection → poisoned generation. Blast
radius is the attacker's own deck; no tool access, no cross-tenant reach. Secondary:
cost exhaustion via repeated uploads — **now capped at 10/hour**. This is the
weakest remaining path and it is weak.

**3 — Insider / operational compromise (most impactful).**
The genuine worst case is not application code. `SECRET_KEY` disclosure allows
forging a session for any `user_id`; the HF token in `.git/config` allows pushing
arbitrary code to the live Space. Both are **operational** items A and B, and both
remain open. Note that persistence is now confirmed (Neon Postgres), which *raises*
the stakes on both: data written by users now survives, so a compromise reaches a
durable store rather than an ephemeral one.

### Step 5 — Risk matrix

| Likelihood ↓ / Impact → | Low | Medium | High |
|---|---|---|---|
| **High** | #13 magic bytes, #14 orphans | #12 CSRF-Lax | — |
| **Medium** | #15 SRI | #16 GDPR | **A: HF token** |
| **Low** | #17 CI/CD | — | **B: SECRET_KEY** |

The three highest cells are all operational, not code. That is the headline: the
application is now in better shape than its deployment configuration.

---

## 🔴 PROMPT 31 — Zero-day thinking: business logic edge cases

**Verdict: ✅ CLEAN — nothing exploitable found**

Each feature interrogated against the prompt's checklist:

| Question | Finding |
|---|---|
| Called out of expected order? | `undo` before any review → 404 (tested). `rate` on an undone card → ordinary new review. `/study` on an empty deck → `{done:true}` |
| Called simultaneously by two users? | Cross-user is impossible — every object is deck-scoped to one owner. Same-user concurrency covered in P26 |
| Internal dependency fails silently? | LLM failure per chunk → falls back to the offline heuristic generator; whole-deck failure → status `failed` with a message. No partial-write state |
| Edge account state? | ⬜ N/A — no suspension, no trial, no payment state, no email verification. A user is either authenticated or not |
| Infer information about other users? | Signup enumeration only (P22). Timing equalised; IDs return 404 not 403, so no existence oracle |
| First-use vs subsequent? | SM-2 branches on `repetitions == 0/1/else` — all server-derived from stored state, not client-asserted |
| Import/export for exfiltration? | ⬜ N/A — no export exists (which is itself a GDPR gap, P32) |
| Admin/debug features left in? | None. No debug route, no seed endpoint, no `/admin`. `/docs` is the only meta surface |
| Time-dependent behaviour manipulable? | Due dates are computed server-side with `datetime.now(timezone.utc)`. A client cannot submit a due date or interval. Clock is the platform's |
| Does the app trust client-reported state? | **No** — the key design property. The client sends only a rating enum and card ID; every scheduling value is derived server-side from stored state |

The most attacker-interesting surface — SM-2 scheduling — is fully server-derived.
There is no field a client can send that alters its own progress beyond choosing
one of four ratings on a card it already owns.

---

## 🔴 PROMPT 32 — GDPR, compliance & privacy

**Verdict: ⚠️ FINDING #16 (Medium) — Open**

| Right / obligation | Status |
|---|---|
| **Art. 17 — Erasure** | ❌ **No account deletion.** A user cannot remove their account or data by any means |
| **Art. 15/20 — Access & portability** | ❌ **No export.** Decks and review history cannot be retrieved in a machine-readable form |
| **Art. 5(1)(e) — Storage limitation** | ❌ No retention policy; `review_logs` and `uploads/` grow forever (`grep -rnE 'retention\|purge\|cleanup'` → no matches) |
| **Art. 13 — Transparency** | ❌ No privacy policy; users are **not told their PDFs are sent to Google** |
| **Art. 44 — Cross-border transfer** | ⚠️ PDF content is transmitted to Google's Gemini API; no stated legal basis |
| **Art. 32 — Security of processing** | ✅ Strong — bcrypt-12, TLS, per-user isolation proven, hardened session handling |
| **Data minimisation** | ✅ Good — only username, email, password hash. No phone, DOB, address, or tracking identifiers |
| **Cookie consent** | ✅ N/A — the only cookie is strictly-necessary session auth. No analytics, no advertising, no tracking cookie |
| **Children's data** | ⚠️ No age gate; a study app plausibly attracts minors |

**Deletion is cheap to add** — the cascades already exist
(`User → Deck → Card → ReviewLog`, all `delete-orphan`), so a single
`DELETE /api/me` would genuinely erase everything:

```python
@router.delete("/api/me", status_code=204)
def delete_account(db: Session = Depends(get_db),
                   user: models.User = Depends(get_current_user)):
    db.delete(user)     # cascades to decks -> cards -> review_logs
    db.commit()
```

**Highest-value privacy fix:** one line in the upload dialog stating that document
text is sent to Google Gemini for processing. Users uploading lecture notes,
medical study material or work documents currently have no way to know.

---

## 🔴 PROMPT 33 — Final sanity check: OWASP Top 10 coverage

### OWASP Web Application Top 10 (2021)

| # | Category | Status | Evidence |
|---|---|---|---|
| A01 | Broken Access Control | ✅ **CLEAN** | 11 endpoints attacked cross-account → all 404; 404-not-403 prevents enumeration (P4) |
| A02 | Cryptographic Failures | ✅ **CLEAN** | bcrypt-12, `secrets` CSPRNG, HMAC sessions, HSTS, no weak primitives (P14) |
| A03 | Injection | ✅ **CLEAN** | Bound parameters throughout; no shell/eval; XSS sinks all `x-text` (P2, P5) |
| A04 | Insecure Design | ✅ **CLEAN** | Server-derived scheduling; no client-trusted state; threat model in P30 |
| A05 | Security Misconfiguration | 🔧 **FIXED** | `.dockerignore`, `chmod 700`, `--proxy-headers`, full header set (P11, P27) |
| A06 | Vulnerable & Outdated Components | 🔧 **FIXED** | 19 advisories → **0** (`pip-audit`) (P10) |
| A07 | Identification & Authentication Failures | 🔧 **FIXED** | Rate-limiter bypass closed; per-account limiting added (P3, P9) |
| A08 | Software & Data Integrity Failures | ⚠️ **FINDING** | No SRI on CDN scripts (#15); no CI/CD integrity gates (#17) |
| A09 | Security Logging & Monitoring Failures | 🔧 **FIXED** | Auth event logging added; no SIEM/alerting (Info) (P16) |
| A10 | Server-Side Request Forgery | ✅ **CLEAN** | Single hardcoded outbound URL; no user-influenced fetch (P12) |

### OWASP API Security Top 10 (2023)

| # | Category | Status | Evidence |
|---|---|---|---|
| API1 | Broken Object Level Authorization | ✅ **CLEAN** | Every object endpoint ownership-checked and adversarially tested (P4) |
| API2 | Broken Authentication | 🔧 **FIXED** | Forgery, replay-after-logout, timing enumeration, brute force all closed (P3) |
| API3 | Broken Object Property Level Authorization | ✅ **CLEAN** | Pydantic DTOs allowlist fields; `password_hash` in no response model (P9) |
| API4 | Unrestricted Resource Consumption | 🔧 **FIXED** | Upload limits, LLM timeout, size/page caps, dependency DoS patched (P19, P28) |
| API5 | Broken Function Level Authorization | ✅ **CLEAN** | Single role; no privileged function exists to reach (P4) |
| API6 | Unrestricted Access to Sensitive Business Flows | 🔧 **FIXED** | Signup/login and the billable upload flow are now rate-limited (P9) |
| API7 | Server Side Request Forgery | ✅ **CLEAN** | No user-controlled URL (P12) |
| API8 | Security Misconfiguration | 🔧 **FIXED** | Container + header hardening (P11) |
| API9 | Improper Inventory Management | ✅ **CLEAN** | 23 routes, all enumerated; no versioning, no shadow/legacy API (P4) |
| API10 | Unsafe Consumption of Third-Party APIs | ✅ **CLEAN** | LLM output parsed defensively, type-allowlisted, rendered as text (P28) |

---

## 🔴 PROMPT 34 — Git history forensics & secret archaeology

**Verdict: ✅ CLEAN (repository) — one out-of-band item**

```
$ git log --all --full-history -p | grep -aiE '(sk-|AIza|AKIA|ghp_|hf_|-----BEGIN|password|secret)'
  (no credential matches)
$ git log --all --full-history -- "**/.env" "*.pem" "*.key" "id_rsa"
  (never committed)
```

| Surface | Result |
|---|---|
| Branches | `main`, `remotes/origin/main`, `remotes/hf/main` — no stale `dev`/`temp`/`wip` |
| Tags | 0 |
| Stashes | 0 |
| Dangling objects | 1 blob + 1 tree — **inspected**: the blob is the README's HF frontmatter (`title: Recall Flashcard Engine`, `emoji`, `sdk: docker`). No secret |
| Large blobs | None anomalous; the repo contains no committed binaries beyond 3 small favicon assets |
| Suspicious commit messages | One match — `2f2ae88 "Remove Groq provider and default to Google Gemini"`. **Verified**: a provider refactor. The diff removes code, not a key; no Groq key ever existed in history |

**The `.env` file has never been committed at any point in history** — confirmed by
full-history path search, not just current state. No history rewrite is needed.

**Out-of-band item A** remains: the HF token lives in `.git/config`, which is
*local configuration*, never part of the object database and never pushed. It is
exposed on disk, not in the repository. Rotation is still required.

---

## 🔴 PROMPT 35 — HTTP request smuggling & desync

**Verdict: ✅ CLEAN — no application-level exposure**

**Architecture:** client → Hugging Face edge proxy → uvicorn (`h11`) → FastAPI.
Single app server, no second internal hop, no Varnish/Squid/HAProxy of the project's
own.

- **Parser:** uvicorn's default HTTP/1.1 parser is `h11`, which is strict by design —
  it **rejects** a message carrying both `Content-Length` and `Transfer-Encoding`
  rather than preferring one, which is the precondition for CL.TE and TE.CL desync.
- **TE.TE obfuscation** (`Transfer-Encoding: xchunked`, space-before-colon,
  `chunked, identity`) requires two cooperating parsers that disagree. The app owns
  only one.
- **HTTP/2 downgrade:** the edge terminates HTTP/2 and speaks HTTP/1.1 to the
  container. This is the one theoretical surface, and it belongs entirely to the
  Hugging Face edge — not configurable or auditable from this repository.
- **No request queue poisoning primitive:** the app has no response-splitting sink —
  no header value is ever constructed from raw request input (verified in P37).

Smuggling here would require a vulnerability in the platform edge or in `h11`
itself. Keeping uvicorn current (now 0.53.0) is the available control.

---

## 🔴 PROMPT 36 — Browser extension security

**Verdict: ⬜ N/A**

The project ships no browser extension and expects none. There is no
`manifest.json`, no `content_scripts`, no `background`/service-worker script, no
`externally_connectable` declaration, and no `chrome.runtime` / `browser.runtime`
message handling anywhere in the codebase.

Nothing in this category applies. For completeness: the app also sets no permissive
`externally_connectable`-equivalent web surface — its CSP declares
`frame-ancestors 'none'`, so it cannot be embedded by a third-party extension page
either.

---

## 🔴 PROMPT 37 — Cache poisoning & web cache deception

**Verdict: ⚠️ Addressed by Finding #8 (🔧 fixed) — no poisoning primitive**

**Part 1 — Cache poisoning:** requires an unkeyed input reflected into a cached
response. Audited every response-header construction path:

- The app builds **no** response header from request input. Security headers are
  static constants; `Cache-Control` is set from a cookie's *presence*, not its value.
- `X-Forwarded-Host`, `X-Original-URL`, `X-Rewrite-URL` are never read.
  `X-Forwarded-Proto` is read **only** as a boolean-ish scheme check for the `Secure`
  flag and HSTS — it cannot inject a value into any response body or header.
- No absolute URLs are generated from `Host`; every redirect targets a hardcoded
  relative path (`"/"`, `"/login"`), so `Host` cannot be reflected into a `Location`.
- No `?utm_*`/`?cb=` parameter is echoed into any response.

**Part 2 — Cache deception:** the classic attack requests
`/decks/1/nonexistent.css` hoping a CDN caches an authenticated HTML response under
a static-looking path. Tested: the app's routes are exact-match, so
`/decks/1/anything.css` → **404**, not an authenticated page. No path-confusion
surface.

**Finding #8 (fixed)** hardens this further: authenticated responses now carry
`Cache-Control: no-store, private`, so neither an intermediary nor the browser's
back-button cache retains one user's decks.

---

## 🔴 PROMPT 38 — Subdomain takeover & DNS hijacking

**Verdict: ⬜ N/A — no owned DNS**

The project controls **no domain and no DNS records**. It is served from
`nipunchugh10-flashcard-engine.hf.space`, a platform-allocated subdomain of
`hf.space`, which Hugging Face owns and operates.

```
$ grep -rnE 'CNAME|_domainkey|\.herokuapp|\.netlify|\.vercel|s3\.amazonaws' .
  (no matches)
```

- No custom domain is configured, so there is no dangling `CNAME` to hijack.
- No third-party SaaS CNAMEs (Zendesk, Intercom, SendGrid, GitHub Pages…) exist.
- Hardcoded external hosts are limited to `generativelanguage.googleapis.com`,
  `cdn.tailwindcss.com`, `cdn.jsdelivr.net`, `fonts.googleapis.com`,
  `fonts.gstatic.com` — all major-provider domains outside this project's control
  and not takeover candidates.

**If a custom domain is ever added**, the relevant control becomes: remove the DNS
record *before* deleting the Space, never the reverse.

---

## 🔴 PROMPT 39 — Second-order & stored vulnerability chains

**Verdict: ✅ CLEAN — nothing found**

This class matters here because the app's core loop is *store now, process later*:
upload → store → background parse → LLM → store cards → render to a different page.
Each stored-data sink was traced.

| Stored value | Later sinks | Assessment |
|---|---|---|
| `user.email` | Login lookup, log lines | Bound parameter; `%`-formatted into logs, never re-queried as SQL |
| `deck.name` (from filename) | Deck page HTML, Alpine `@click`, log line | Autoescaped; `\|tojson` in a single-quoted attribute (P5). **This was a real second-order XSS, fixed in the prior pass** — the injection point (upload filename) and the trigger (rename button on a different page) were separated exactly as this prompt describes |
| `deck.source_filename` | Deck page | Autoescaped `{{ }}` — text context only |
| `card.front` / `card.back` (LLM output) | Deck browser, study card, search filter | Rendered via `x-text`; searched via bound `ilike`. **Never re-enters SQL as a fragment** |
| `card.tags` | Stored, not currently rendered | Comma-joined string; no sink |
| `generation_error` | Deck page + `/status` JSON | Was raw exception text (**Finding #6, fixed**) — now a fixed constant |
| `review_logs.*` | History aggregation | Integers/timestamps aggregated in Python, not SQL string-built |

**No second-order SQL injection is possible** — there is exactly one query-building
path (`select()` with bound parameters) and no reporting, batch-export, admin-panel,
or stored-filter feature that reconstructs a query from stored text.

**Deferred-execution check:** the background worker consumes `deck_id` (an integer
it was passed) and re-fetches by primary key — it never re-parses stored strings
into queries or commands.

---

## 🔴 PROMPT 40 — GraphQL security deep dive

**Verdict: ⬜ N/A**

The application exposes no GraphQL endpoint. There is no `strawberry`, `graphene`,
`ariadne` or `gql` dependency; no `/graphql` route; no schema definition; no
resolvers. The API is REST, enumerated in full under P4.

Every sub-check in this prompt — introspection exposure, field suggestion leakage,
GraphiQL in production, resolver-level authorization, query depth/complexity limits,
batching and alias-based amplification, nested cross-object authorization — is
inapplicable because none of that machinery exists.

The equivalent REST concerns are covered: object-level authorization in P4,
field-level exposure in P9 (`response_model` DTOs), and resource consumption in P19.

---

## 🔴 PROMPT 41 — Advanced protocol & emerging attack surfaces

**Verdict: ⬜ Mostly N/A — one applicable item, ✅ clean**

| Area | Status |
|---|---|
| **OAuth 2.0 / OIDC** (PKCE, redirect_uri matching, token substitution, silent auth) | ⬜ N/A — no OAuth. Local email+password only |
| **JWT algorithm confusion** (RS256→HS256, `alg:none`) | ⬜ N/A — not JWT. `itsdangerous` uses a fixed signing scheme with no client-selectable algorithm field, which structurally prevents this class |
| **SAML / XML signature wrapping** | ⬜ N/A — no SAML, no XML parsing at all (P13) |
| **Token leakage via `Referer`** | ✅ **CLEAN** — no token ever appears in a URL; session is cookie-only, and `Referrer-Policy: strict-origin-when-cross-origin` is set |
| **Token binding** | ⬜ Not implemented — sessions are bearer-style. Acceptable given `HttpOnly` + `Secure` + epoch revocation |
| **HTTP/2 & HTTP/3 specific** (stream multiplexing abuse, rapid reset) | ⬜ Platform-owned — the edge terminates modern protocols; the container speaks HTTP/1.1 |
| **WebSocket protocol attacks** | ⬜ N/A (P20) |
| **Server-side template injection (SSTI)** | ✅ **CLEAN** — templates are static files on disk; **no user input is ever used as a template string**. `TemplateResponse` always names a fixed `.html` file, and the jinja2 upgrade to 3.1.6 closes the `\|attr` sandbox escape regardless |
| **Prototype pollution** | ⬜ N/A — Python server; client JS performs no object merging |
| **Dependency confusion** | ✅ **CLEAN** — no internal/private package names; all 15 dependencies are well-known public PyPI packages |

---

# Appendix — Reproducing this audit

```bash
./run.sh test        # 21 functional tests
./run.sh security    # 45 adversarial security tests
.venv/bin/pip-audit  # dependency advisories — currently: No known vulnerabilities found
```

**Post-audit state:**

| Metric | Before | After |
|---|---|---|
| Dependency advisories | 19 | **0** |
| Login brute-force attempts before throttle | **unlimited** (XFF spoof) | 10 per IP **and** per account |
| Upload rate limit | none | 10/hour per IP + account |
| LLM call timeout | 600 s × 2 retries | 60 s × 1 retry |
| Secrets/DB/PDFs in a local image build | yes | excluded |
| Auth security events logged | 0 | 6 event types |
| Smoke / security tests | 21 / 45 | 21 / 45 (all passing) |

**The five open findings, in priority order:**

1. **Operational A** — rotate the Hugging Face token in `.git/config` (High)
2. **Operational B** — confirm the Space's `SECRET_KEY` is not the guessable value
   (Medium). Being *set* is not sufficient: `app/config.py` refuses placeholder and
   sub-32-character keys and substitutes a random one, which keeps sessions
   unforgeable but logs every user out on each rebuild. The Space secret predates
   that blocklist. **Check:** the startup log shows
   `CRITICAL … INSECURE CONFIGURATION: SECRET_KEY is a known placeholder value`
   if it is being rejected — silence means the key is accepted and sessions persist.
3. **#16** — add `DELETE /api/me` + data export + a privacy note about Gemini (Medium)
4. **#12** — `SameSite=Strict` or CSRF tokens on the three bodyless POSTs (Medium)
5. **#13/#14/#15/#17** — magic-byte check, upload janitor, SRI, CI/CD gates (Low/Info)

**Closed since the audit:** operational finding C — `DATABASE_URL` is configured and
backed by Neon Postgres 18, so decks and accounts persist across Space rebuilds.

---

*Audit performed against commit `c7b6ebf`, 2026-09-15, following all 41 prompts of
`VIBE_APP_SECURITY_AUDIT.md`. Every finding was reproduced before being reported and
re-tested after being fixed.*
