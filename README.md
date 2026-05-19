# IATI Corpus Access Probe (Layer 1)

**How much of IATI's linked-document corpus is actually accessible and
readable?**

A single-sprint research probe. It draws a stratified sample of the document
links IATI publishers attach to their activities, crawls those publisher-hosted
URLs politely, and measures how many **resolve** and are **readable** (the file
is what its declared format claims, content is extractable text rather than a
scanned image, and a usable amount of text comes out).

It produces an **access-and-readability findings table** (CSV, one row per
country plus distributions) and a **written verdict**. That is the whole
deliverable.

---

## ⚠️ Two boundaries — read before touching the code

### The scope boundary

This is a **measurement probe**, not an application and not the corpus build.

- No web UI, no deployment, no tool for anyone to run.
- It is **Layer 1 (access reality)** only. It establishes whether documents
  are *readable*. It does **not** assess what they *say* — that is Layer 2
  (content assessment), a separate later project. Work drifting into content
  analysis stops and is flagged.
- It shares no code with, and does not import from, TRACE, Constellate, the
  Phase 0.5 baseline, or the Phase 0.6 pilot.

### The retention boundary

**This probe measures documents; it does not retain them.**

- Fetched document bytes are a **transient, gitignored working cache**
  (`cache/docbytes/`). They are used to compute the readability metrics and
  then discarded. They are not a deliverable.
- There is **no permanent or queryable document store**. Building one is the
  *corpus build* — a separate, later, separately-scoped project with its own
  licensing and consent decisions. If the work starts accumulating a retained
  corpus, that is a different project: stop and flag it.
- Committed output carries **counts, statuses and identifiers only** — never
  document content, never place names or beneficiary detail (location-safety
  rule). "Readable" is a property of the file, not its meaning.
- Licensing: the probe asserts no redistribution right over publisher
  documents and, because it retains nothing, raises no redistribution
  question. The verdict will *flag* — not resolve — that a future *retained*
  corpus does raise a licensing question.

---

## Crawl-safety (binding — not tunable for speed)

The crawler fetches arbitrary untrusted third-party hosts. Per-host rate
limiting and a polite global pace; real connection + read timeouts; a
declared honest User-Agent identifying IATI research tooling; `robots.txt`
honoured; a hard max file-size cap; recorded redirects with off-domain
flagged; non-public/loopback/link-local hosts resolved and **not** fetched
(re-checked on every redirect hop); no authentication and no paywall/CAPTCHA
bypass; every fetch fault-isolated and recorded as a result row; resumable
from the metric cache; fetched content treated strictly as untrusted data
(never executed, never acted on). Full definitions in `SIGNAL-METHOD.md §2`.

---

## Project layout

```
src/iati_access_probe/   probe code (sampler, Datastore wrapper, crawler, readability)
tests/                   offline tests; tests/fixtures/ stub responses & sample files
scripts/                 entry-point scripts
cache/                   ALL transient & gitignored (sample, metrics, doc bytes, text)
output/                  COMMITTED deliverable: findings tables + verdict
SIGNAL*.md               probe spec (read in the order CLAUDE.md gives)
```

## Setup

1. Python 3.10+ (developed on 3.14). Create a virtual environment:
   `python -m venv .venv` and activate it.
2. `pip install -r requirements.txt`
3. The live sample draw needs a free IATI Datastore API key. Copy
   `.env.example` to `.env.local` and set `IATI_API_KEY`. **`.env.local` is
   gitignored — never commit it.** Deliverables 1–5 run offline against
   fixtures and do not need the key.

## Run order

Deliverables 1–5 are built and tested **entirely offline** against fixtures.
Then: stop for the IATI key → draw the live sample (deliverable 2 live half)
→ cost & scale projection (deliverable 6) → **stop for explicit crawl
go-ahead** → crawl run → analysis / findings tables → written verdict
(deliverables 7–9). Run commands will be documented here as each entry point
lands.

## Status

Sprint 1, deliverable 1 (scaffold) complete. See `SIGNAL.md` build status.
