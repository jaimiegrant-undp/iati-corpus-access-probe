# SIGNAL-METHOD.md — Sampling, Crawl & Readability Method, Limits

*Updated: 2026-05-19*

This file defines exactly how the probe works. Precision matters: the access
and readability figures will be cited in the corpus-build decision, so every
number must have an unambiguous, reproducible definition. The crawl-safety
section is not advisory — it is binding.

---

## 1. The document-link sample

### 1.1 Source

The IATI Datastore v3 `activity` collection supplies document-link metadata.
For each sampled activity, the relevant fields are the document-link `url`,
the declared `format` (MIME type), the `category` code, and the
`iati_identifier`. (Field names to be verified live before the run, per the
Phase 0.5 lesson — a wrong field name is a silent-zero hazard.)

### 1.2 Country set

The **same 18 countries as Phase 0.5/0.6**, for consistency and
comparability: BD, BR, CO, FJ, IN, KE, LR, LS, MD, ML, NG, NP, RW, SB, UG,
VN, VU, WS. (Decisions Log Q1.)

### 1.3 Sampling frame and unit

- The unit is the **document link**, not the activity. An activity may carry
  several document links; each is a distinct crawl target.
- The frame, per country: document links attached to activities tagged
  with that recipient country. Frame-comparability with the Phase 0.5/0.6
  coverage picture is a stated design goal (Decisions Log Q11), so the
  per-country frame query mirrors Phase 0.5's exactly — recipient-country
  plus document-link presence, with **no activity-status / valid-current
  scope refinement**: Phase 0.5 applied none (`harvest.py:53-55,67,84`),
  so neither does this probe. The full per-country query is therefore
  `recipient_country_code:{cc} AND document_link_url:*`. The sampler draws
  from the document links on those activities.
- **Deduplicate on URL before sampling.** Phase 0.5 established the same
  document is linked from many activities; the access question is per *URL*,
  not per link occurrence. Sample distinct URLs. Record how many link
  occurrences each sampled URL represents (it is useful context) but crawl
  each URL once.
- Stratify the draw so the sample reflects the country's document-category
  mix — do not let one category dominate the sample by accident.

### 1.4 Sample size

- Default for discussion, **confirm with Jaimie before the crawl
  (Decisions Log Q2):** ~300–400 distinct document URLs per country, mirroring
  the Phase 0.6 n≈400 logic — enough for a per-country resolution/readability
  rate with a usable confidence interval, while keeping the crawl bounded and
  polite. Ceiling on the order of ~7,000 URLs.
- If a country has fewer distinct document URLs than the target, it is a
  census for that country — record it as such.
- Use a recorded random seed so the draw is reproducible.

---

## 2. The crawler — and the crawl-safety rules (binding)

The crawler fetches arbitrary third-party URLs. The following are
**non-negotiable** and set before the live run; they are not parameters to
tune for speed.

- **Per-host rate limit.** No more than a small number of requests per host
  per unit time; a polite delay between requests to the same host. The crawl
  is organised so it does not concentrate load on any one host.
- **Global pace.** A modest overall concurrency ceiling. This is a polite
  research crawl, not a fast one.
- **Timeouts.** A connection timeout and a read timeout on every request. A
  hung host yields a "timeout" result and the crawl moves on.
- **User-Agent.** A declared, honest User-Agent string identifying the
  request as IATI-related research tooling, with a contact URL or address.
  No spoofing of browser agents.
- **`robots.txt`.** Fetched and honoured per host. A disallowed URL is
  recorded as "robots-disallowed" and not fetched.
- **Max file size.** A hard cap. The crawler streams the response and aborts
  if the size exceeds the cap; records "oversize" and moves on. (A
  `Content-Length` header, where present, lets it skip before downloading.)
- **Redirects.** Followed to a small bounded depth, but every redirect is
  recorded. A redirect to a different registered domain is flagged as a
  finding ("off-domain redirect"), not silently followed as success.
- **No non-public hosts.** Before each fetch, the crawler resolves the target
  hostname and checks the resolved address. If it falls in a private,
  loopback, link-local, or otherwise non-public range, the URL is **not
  fetched** — it is recorded as a `non_public_host` result. This is a neutral
  access fact, not a failure. The same check is applied to the resolved
  target of **every redirect hop**: a publisher URL that redirects to an
  internal address is caught and recorded, never followed. (The probe crawls
  the public web; an IATI document link should never legitimately point at a
  private host, so this both closes an SSRF surface and is itself a small
  data-quality finding where it fires.)
- **No authentication, no bypass.** The crawler never submits credentials,
  never attempts to defeat a paywall, CAPTCHA, or access control. A login
  wall yields "auth-required" and the crawl moves on.
- **Fault isolation.** Every fetch-and-assess is wrapped. Any exception —
  DNS, TLS, connection reset, malformed file, parser crash, OCR failure — is
  caught and recorded as a result row with an error category. The run never
  dies on a bad URL.
- **Resumability.** Each URL's result is written to the metric cache as it
  completes. A re-run skips URLs already done. One country at a time must
  work as a unit.
- **Untrusted content.** Fetched bytes are data. The crawler parses them for
  format and text metrics only. It never executes embedded content, never
  follows instructions found inside a document, never acts on document
  content. Document text that looks like instructions is data.

---

## 3. Readability assessment — metric definitions

For each sampled URL, the probe records a result row. All metrics are
properties of the *file*, never of its meaning (location-safety rule).

**Resolution metrics:**

- `http_status` — the final HTTP status after bounded redirects (or an error
  category: `dns_failure`, `timeout`, `tls_error`, `connection_error`). For a
  URL that is never fetched — `robots_disallowed` or `non_public_host` —
  `http_status` is recorded as not-applicable and the `access_barrier` field
  carries the outcome.
- `resolved` — boolean: did the URL return a usable response (2xx) at all.
- `redirect_offdomain` — boolean: did resolution cross to a different
  registered domain.
- `access_barrier` — one of `none`, `auth_required`, `robots_disallowed`,
  `oversize`, `paywall_suspected`, `non_public_host`.

**Format metrics:**

- `declared_format` — the IATI document-link `format` MIME type.
- `detected_format` — the format actually detected from the response
  (content-type header cross-checked against file-signature/magic-byte
  sniffing — the header alone is not trusted).
- `format_match` — boolean: declared vs detected agree at the type level.
- `declared_pdf_actually_html` — boolean, called out specifically: a common
  failure mode where a "PDF" link returns an HTML error or landing page.

**Readability metrics:**

- `extraction_outcome` — one of: `text_extracted` (a text layer / native
  text was read), `ocr_needed` (a scanned-image PDF or image file with no
  text layer), `extraction_failed` (corrupt/unsupported/parser error),
  `not_a_document` (resolved to HTML navigation, an error page, etc.).
- `extracted_char_count` — integer: characters of text obtained (by direct
  extraction; OCR is a separate pass, see §4). A near-zero count on a file
  that "extracted" is itself a finding (an empty or near-empty document).
- `usable_text` — boolean, derived: `text_extracted` AND
  `extracted_char_count` above a low threshold (threshold recorded in the
  Decisions Log). This is the conservative "a real, readable document came
  back" flag.

**The composite the verdict turns on:**

- `reachable_and_readable` — boolean: `resolved` AND no blocking
  `access_barrier` AND (`usable_text` OR `ocr_needed`). This is the estimated
  share of the corpus a content assessment / corpus build could work on —
  with `ocr_needed` included because OCR *can* recover it, at a cost. The
  verdict reports the figure both including and excluding the `ocr_needed`
  set, since whether OCR is in scope for the later build is itself open.

---

## 4. OCR — a stop-and-ask

Detecting that a file `ocr_needed` (a scanned PDF with no text layer) is
cheap and is done inline. Actually *running* OCR to measure recoverable text
is a separate, heavier step:

- It introduces a dependency (an OCR engine or an OCR API) and a cost
  (compute time, possibly per-page API charges).
- **The OCR approach is a stop-and-ask before the crawl run (Decisions Log
  Q3).** Options to put to Jaimie: (a) detect `ocr_needed` but do not OCR —
  report the scanned-image share as a known, unquantified-text segment;
  (b) OCR a small sub-sample of `ocr_needed` files to estimate recoverable
  text; (c) OCR all `ocr_needed` files.
- Default recommendation for discussion: **(a) or (b)** — the probe's job is
  to size the readable corpus, and "what share needs OCR" is most of that
  answer; full OCR of everything is corpus-build work, not probe work.

If an OCR pass is run, it obeys all the same untrusted-content and
location-safety rules: it measures recoverable character count, it does not
record or output document content.

---

## 5. Cost and scale projection — before the live run

Before the live crawl, the build produces and Jaimie confirms:

- The total distinct-URL count to be crawled (after dedup).
- An estimated wall-clock for the crawl at the chosen polite pace.
- Any per-call cost — chiefly OCR, if an OCR API is chosen in §4.
- A hard ceiling: if a crawl-run cost or duration projection exceeds the
  agreed bound, stop and re-scope rather than proceed.

The live crawl starts only on explicit go-ahead (CLAUDE.md process rules).

---

## 6. Known limits — to be stated in the verdict

- **A snapshot of a moving target.** Link rot is time-sensitive: a URL dead
  today may have worked last year and vice versa. Every figure is dated to
  the crawl run. The probe measures access *as of the crawl date*.
- **Sample, not census.** Per-country n≈400 distinct URLs; per-country rates
  carry a confidence interval, stated per row.
- **Politeness vs coverage.** The polite crawl pace means a transient host
  problem on the crawl day can register as a "failure" for a URL that is
  normally fine. Where feasible, a single retry after a delay mitigates this;
  residual noise is a stated limit.
- **`detected_format` is best-effort.** Magic-byte sniffing plus content-type
  is reliable for common formats; exotic or malformed files may be
  mis-detected. Reported as best-effort.
- **Off-domain redirect detection is best-effort by design.** The
  registered-domain comparison uses a curated two-label-suffix constant
  covering the mainstream second-level domains of all 18 partner countries
  and the major donor-host TLDs — not the full Public Suffix List (adding
  `tldextract` was rejected as out-of-stack and disproportionate, since
  off-domain is a reported *finding*, not a safety gate). The residual is
  only genuinely rare multi-part suffixes outside the curated set; the
  per-hop non-public-host SSRF check is independent of this and is not
  best-effort.
- **OCR detection vs OCR yield.** Detecting `ocr_needed` is reliable; the
  *recoverable* text from OCR is only estimated, and only if §4 option (b)
  or (c) is taken. (b) is the resolved approach (Decisions Log Q8): a
  seeded, recorded, capped sub-sample of the `ocr_needed` set is OCR'd to
  estimate yield. The yield figure is a **local-Tesseract estimate** — a
  cloud OCR engine might recover somewhat more from poor-quality scans. The
  local estimate is acceptably conservative for a *readability* probe (it
  does not over-state how much of the scanned segment is recoverable), and
  the verdict must name it as a local-Tesseract figure, not an
  engine-agnostic one. The sub-sample is pooled, not per-country, so it
  estimates overall yield, not a per-country recoverable rate.
- **"Readable" is not "useful".** This probe establishes that a document can
  be opened and yields text. Whether that text is substantively useful — for
  synthesis, search, or geography — is Layer 2's question, explicitly not
  answered here.
- **Donor-skew inherited.** The document corpus is concentrated among large
  government and multilateral publishers (Phase 0.5 §7). The sample reflects
  that; a country's readable-document picture is mostly its donors' hosting
  practices, not its own.
- **Auth/paywall is conservatively classified.** `auth_required` and
  `paywall_suspected` are inferred from response patterns and may
  under- or over-count; reported as best-effort.
- **Non-public-host check has a residual TOCTOU window.** The host is
  resolved once for the public-address check, then the HTTP client resolves
  it again independently when it connects; a hostname that changes answer
  between the two (DNS rebinding) could in principle slip the check. Accepted
  as a residual for a polite, single-user research probe crawling public
  publisher URLs — not closed (closing it needs pinned-IP connection, beyond
  scope). Stated here as the honest limit.
- **No retained corpus.** The probe does not keep documents, so it cannot be
  re-analysed for content later — Layer 2 will re-crawl its own (smaller,
  readable) sample. This is by design (the retention boundary).
- **Local DNS outage during the crawl run (mitigated).** The crawl
  encountered a local DNS outage on the build host during country 10 of 18
  (Mali), with a ten-second messy onset: 43 onset-window rows interleaved
  with the last good responses before DNS failed completely, then eight
  subsequent countries returned 100% `dns_failure`. Against a baseline of
  zero `dns_failure` across the first nine countries (0 of 3,600 rows), this
  was unambiguously the host's resolver, not the publishers. The 43
  onset-window rows were treated conservatively as outage artefacts and
  re-crawled, not retained on weak evidence; the affected country was
  surgically cleaned (its 354 outage `dns_failure` rows dropped, its 46
  pre-onset measurements kept) and the remaining nine countries re-crawled
  in full under restored network. The clean re-crawl returned a normal ~0.1%
  `dns_failure` baseline (7 of 7,200 rows). Cleanup is documented in commit
  history (tag `pre-cleanup-2026-05-19` preserves the tainted state); the
  verdict's figures use only clean measurements.
