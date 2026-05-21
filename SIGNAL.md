# SIGNAL.md — IATI Corpus Access Probe

*Updated: 2026-05-19*

---

## What this probe produces

An **access-and-readability baseline** for IATI's linked-document corpus,
delivered as:

1. A set of **findings tables** (CSV) — one row per country, plus distributions
   over status codes, formats, and readability outcomes.
2. A **written verdict** interpreting the tables: how much of the corpus is
   reachable and readable, and what that means for the corpus build.

That is the whole deliverable. No tool, no UI, no retained document store.

## Why it exists

The corpus investigation was split into two layers. **Layer 1 (this probe) —
the access reality:** are the linked documents actually reachable and
readable? **Layer 2 (later, separate) — the content assessment:** what does
the readable corpus hold, for synthesis/search and for the geolocation
question.

Layer 1 gates Layer 2. A content assessment can only run on documents that
resolve and yield text. Phase 0.5 established the corpus is large (~1.5m
document-link instances) but its metadata is too thin to triage on
(`doc_has_description` under 5%) — so documents must be resolved and opened to
be assessed at all. What is not yet known is how many *can* be. This probe
establishes that real denominator.

## The core questions

For each country, and pooled:

1. **Resolution.** Of sampled document links, what share resolve to a live
   response? What share are dead (DNS failure, 404, 410), redirected, or
   time out? Where do redirects go — same host, or off-domain?
2. **Format truth.** Does the retrieved file match its declared `format`
   (the IATI document-link MIME type)? How often is a declared PDF actually
   HTML (an error page, a landing page), or vice versa?
3. **Readability.** Of files that resolve, what share are extractable text
   (PDF text layer, HTML, DOCX) versus scanned images requiring OCR? Of the
   text-extractable set, how much text comes out — enough to be a usable
   document, or a near-empty file?
4. **Access barriers.** What share sit behind authentication, paywalls, or
   `robots.txt` disallow?
5. **The readable denominator.** Pulling 1–4 together: of the linked-document
   corpus, what share is actually reachable AND readable — the population a
   content assessment or corpus build could work on.
6. **Distribution of the gap.** How do resolution and readability vary by
   country (does the Pacific SIDS corpus fare worse?), by publisher, and by
   document category?

## Data sources

- **IATI Datastore v3 API** — supplies the document-link metadata for the
  sample (URL, declared format, category, the activity it belongs to). Public,
  free API key.
- **Publisher-hosted document URLs** — crawled to test access and readability.
  These are arbitrary third-party hosts.

## Crawl design (summary — full detail in SIGNAL-METHOD.md)

- A Python script draws a stratified document-link sample per country from the
  Datastore.
- A safe, resumable crawler fetches each sampled URL: per-host rate limiting,
  real timeouts, declared User-Agent, `robots.txt` honoured, hard file-size
  cap, non-public hosts not fetched, every outcome (success or any failure)
  recorded as a result row.
- For each fetched file, readability is assessed: format detection, text
  extraction attempt, OCR-needed detection, extracted-text length.
- Fetched bytes are a transient working cache (gitignored, clearable). The
  computed readability metrics are cached (gitignored) so analysis re-runs
  without re-crawling.
- A separate analysis step emits the findings tables. The verdict is written
  from them.

## The retention boundary — what this probe is NOT

- **It measures documents; it does not keep them.** No retained, queryable
  document store. That is the corpus build — a separate, later project.
- Not Layer 2. It tests whether documents are readable, not what they say.
- Not a tool, not a TRACE/Constellate feature, not a crawler anyone else runs.
- Not a licensing decision. It flags that a *retained* corpus raises a
  licensing question; it does not resolve it.

## Tech stack

- Python 3. `requests` for all HTTP (Datastore queries and the crawl).
- Text extraction and format detection each need a library. The expected
  stack, to be confirmed and pinned in `requirements.txt` in deliverable 1:
  `pypdf` for PDF text extraction, `beautifulsoup4` for HTML, `python-docx`
  for DOCX, and a magic-byte detection library (`filetype` or an equivalent
  pure-Python option — no system `libmagic` dependency, as the build host is
  Windows) for format sniffing. All are well-established; CC verifies each is
  real, actively maintained, and widely used before pinning (slopsquatting
  is an active attack class — see CODING_GUARDRAILS).
- OCR is deliberately **not** pre-named. The OCR approach — and therefore
  whether an OCR engine or API becomes a dependency at all — is a
  stop-and-ask before the crawl run (SIGNAL-METHOD §4). Any OCR library is
  added only after that gate is resolved.
- No framework. No database — local JSON/CSV cache and output.
- Git for version control.

## Build status

✅ **Sprint 1 — complete.** Access-and-readability probe, end to end.

- ✅ Scaffold & git
- ✅ Datastore document-link sampler (offline, fixture-tested)
- ✅ Field & connector verification (thin Datastore wrapper)
- ✅ Safe resumable crawler (offline, fixture-tested)
- ✅ Readability assessment (format detection, text extraction, OCR-needed)
- ✅ Cost & scale projection (real numbers; 6,934 distinct URLs, within bound)
- ✅ Live sample draw (seeded, 18 countries, n=400, no censuses)
- ✅ Crawl run (7,200 URLs; DNS-outage during ML–WS caught, cleaned, re-crawled)
- ✅ OCR-yield estimate (Q8(b): 70% of scanned recover usable text)
- ✅ Analysis / findings tables (`output/*.csv`)
- ✅ Written verdict (`output/VERDICT.md`)

✅ **Headline result:** ~**43%** of linked documents are reachable AND
readable (95% CI 41.9–44.2). The gap is driven by authentication walls (26%
of all URLs), non-document pages, and `robots.txt` disallows — not link rot.
Pacific SIDS are *not* access-disadvantaged. The corpus is 96.3%
cross-country-distinct. 104 tests pass; all egress was Datastore-API + the
polite publisher crawl, no retained corpus.

**Immediate next sprint:** none planned. This is a single-sprint probe; its
output gates the chat-and-human decision on Layer 2 and the corpus build.
The retained-corpus licensing question is flagged for that decision.
