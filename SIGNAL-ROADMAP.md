# SIGNAL-ROADMAP.md — Sprint Plan & Decisions Log

*Updated: 2026-05-19*

---

## CURRENT SPRINT

### Sprint 1 — Access-and-readability probe

One sprint. Like Phase 0.5/0.6, this is a single-sprint probe.

**Ordered deliverables:**

1. **Scaffold & git.** Repo initialised. `.gitignore` covers `.env.local`,
   the metric cache, the **transient document-bytes cache**, raw extracted
   text, Python artefacts, OS/IDE files. `.env.example` documents the keys
   (the IATI key always; an OCR API key only if §4 option (b)/(c) is later
   chosen). `README.md` with the scope boundary, the retention boundary,
   setup, run order. `requirements.txt` pinned.
2. **Datastore document-link sampler.** Query the Datastore for document-link
   metadata for the 18 countries; dedupe on URL; stratify by category; draw
   the seeded per-country sample. Verify Datastore field names live before
   the draw. Cache the sample. (Building the sampler is offline work; the
   actual seeded *draw* needs the live IATI key — see the live-key note
   under the success criteria.)
3. **Field & connector verification.** Confirm every Datastore field name
   used; a thin, documented Datastore wrapper with auth, pacing, loud failure
   on an unrecognised field. (Reuses the Phase 0.5 lesson; built fresh, not
   imported.)
4. **Safe resumable crawler.** Implement the crawler to every binding rule in
   SIGNAL-METHOD §2: per-host rate limiting, timeouts, declared User-Agent,
   `robots.txt`, max file size, recorded redirects, non-public-host blocking,
   no auth, fault isolation, resumability, untrusted-content handling. Build
   and test its structure offline (against stubs/fixtures) before any live key
   or live fetch.
5. **Readability assessment.** Format detection (magic-byte + content-type),
   text extraction per format, `ocr_needed` detection, extracted-char-count,
   the derived `usable_text` and `reachable_and_readable` composites — all per
   SIGNAL-METHOD §3. OCR *yield* only if §4 is resolved to option (b)/(c).
6. **Cost & scale projection.** Before the live crawl: distinct-URL count,
   estimated wall-clock, any per-call cost. Presented to Jaimie; live crawl
   begins only on explicit go-ahead.
7. **Crawl run.** Execute the crawl against the sample, resumable, one country
   at a time if needed. Record every outcome.
8. **Analysis / findings tables.** Read the metric cache; emit the CSV
   findings tables — resolution, format-truth, readability, the
   reachable-and-readable composite, and the per-country / per-publisher /
   per-category distributions. Every rate carries its denominator and the
   crawl date.
9. **Written verdict.** Interpret the tables: the readable denominator, the
   cross-country pattern (the Pacific SIDS especially), what it means for
   Layer 2 and the corpus build, all SIGNAL-METHOD §6 limits, and the
   licensing flag for a retained corpus.

**Success criteria:**

- The crawl runs end to end within the agreed pace and cost bounds, is polite
  (no host overloaded), and is resumable from cache.
- Every fetch outcome — success or failure — is recorded as a result row; the
  run survives every bad URL.
- The retention boundary holds: no retained document store; the
  document-bytes cache is transient and gitignored; committed output is
  counts/statuses/identifiers only, no document content, no place names.
- Every figure traces to a defined metric, the sample, and the crawl date.
- The verdict answers all six core questions in SIGNAL.md, distinguishes the
  four readability sub-questions cleanly, states every §6 limit, and flags the
  licensing question for a retained corpus.
- The output is sufficient for a chat-and-human decision on whether, and how,
  to proceed to Layer 2 and the corpus build.

**The live-key boundary.** Deliverables 1–5 are built and tested entirely
offline against stubs/fixtures — no live IATI key, no live fetch. The live
IATI Datastore key is needed only to draw the actual sample (the live half of
deliverable 2), and that draw must happen before the deliverable 6
projection. The run order is therefore: build 1–5 offline → stop and request
the key → draw the live sample → produce the deliverable 6 projection → stop
for the crawl go-ahead → 7–9.

**Out of scope (do not build):** Layer 2 content assessment; a retained or
queryable document store; any tool or UI; any TRACE/Constellate integration;
full OCR of the corpus (unless §4 is explicitly resolved that way).

---

## DECISIONS LOG

Format: `Q[N]. Question / Decision / Rationale / Consequences`. Append only.

**Q1. Country set for the probe.**
*Decision:* The same 18 countries as Phase 0.5/0.6 (BD, BR, CO, FJ, IN, KE,
LR, LS, MD, ML, NG, NP, RW, SB, UG, VN, VU, WS).
*Rationale:* Consistency and comparability with the two completed baselines;
the access picture can be read against the coverage picture for the same
countries, including the Pacific SIDS equity cut.
*Consequences:* Sampler iterates the fixed 18; the verdict can cross-reference
Phase 0.5/0.6 directly.

**Q2. Per-country sample size.**
*Decision:* Open — confirm with Jaimie before the crawl. Default for
discussion: ~300–400 distinct document URLs per country (~7,000 ceiling).
*Rationale:* Mirrors the Phase 0.6 n≈400 logic — a usable per-country
confidence interval while keeping the crawl bounded and polite.
*Consequences:* Fixed before the crawl run; recorded here with the seed once
confirmed.

**Q3. OCR approach.**
*Decision:* Open — stop-and-ask before the crawl run. Options: (a) detect
`ocr_needed`, do not OCR; (b) OCR a sub-sample to estimate yield; (c) OCR all
scanned files.
*Rationale:* Detecting the scanned-image share answers most of the
readability question; full OCR is corpus-build work and adds dependency and
cost. (a) or (b) is the probe-appropriate scope.
*Consequences:* Determines a dependency, a possible API key and cost line, and
whether `reachable_and_readable` includes a measured or only an estimated OCR
contribution.

**Q4. Retention boundary.**
*Decision:* The probe measures documents; it does not retain them. Fetched
bytes are a transient, gitignored working cache. No permanent or queryable
document store is built.
*Rationale:* Retaining documents is the corpus build — a separate project
with its own licensing and consent decisions. Keeping the probe
non-retaining keeps it cheap, low-risk, and raises no redistribution
question.
*Consequences:* Committed output is metrics only. Layer 2 will draw and crawl
its own sample rather than re-using a store from here.

**Q5. Tier.**
*Decision:* Tier 2 (vs Tier 1 for Phase 0.5/0.6).
*Rationale:* The probe performs network egress to untrusted hosts, fetches
and transiently caches third-party content, and runs OCR — a content-fetch
surface materially beyond Tier 1. It remains single-user, local, no
deployment, so it does not reach Tier 3.
*Consequences:* Tier 2 rules on rate/spend discipline, the caching boundary,
crawl-safety, and an explicit licensing posture apply from the first commit;
tier reassessed at session close and if the probe is ever re-scoped to retain
documents.

**Q6. `usable_text` character threshold.**
*Decision:* Open — confirm with Jaimie at the pre-crawl gate (alongside Q2).
Default for discussion and wired as the code default: **250 characters**.
`usable_text` = `text_extracted` AND `extracted_char_count` ≥ threshold.
*Rationale:* SIGNAL-METHOD §3 requires the threshold be recorded here. 250
is a deliberately conservative floor for "a real, readable document came
back" — well below a one-paragraph report, high enough to exclude an empty
or stub extraction. It is a parameter, not hard-coded behaviour: the
confirmed value is injected at run time and recorded on the findings tables.
The same threshold is the floor below which an HTML body is treated as a
nav/landing/error stub (`not_a_document`) rather than a readable document.
*Consequences:* Moves the `usable_text` and therefore the
`reachable_and_readable` line; the verdict states the threshold explicitly
and, where feasible, reports sensitivity to it.

**Q7. Per-country sample size — resolved (supersedes Q2).**
*Decision:* ~300–400 distinct document URLs per country, ~7,000 ceiling
across the 18. A country with fewer distinct URLs than the target is a
**census** for that country and is recorded as such on the findings table.
*Rationale:* The Phase 0.6 n≈400 logic — a usable per-country confidence
interval while the crawl stays bounded and polite — and it keeps the access
picture comparable to the Phase 0.5/0.6 coverage picture for the same 18.
*Consequences:* Fixes the distinct-URL ceiling the D6 wall-clock projection
is built on; the seed is recorded here once the live draw is run.
*Supersedes Q2 (was "Open").*

**Q8. OCR approach — resolved (supersedes Q3): option (b).**
*Decision:* Option **(b)** — OCR a small, **seeded, recorded, reproducible
sub-sample** of the `ocr_needed` set to estimate recoverable-text yield.
Explicitly **not (a)** (the Layer 1 verdict must carry a recoverable-text
estimate, not only a scanned-share count) and explicitly **not (c)** (no
full-set OCR — the probe sizes the corpus, it does not process it).
*Rationale:* The verdict's `reachable_and_readable` figure is materially
more honest with a measured OCR-yield estimate for the scanned segment than
with that segment left entirely unquantified; full OCR is corpus-build
work, out of scope and a retention/cost escalation.
*Consequences:* Brings an OCR-engine dependency decision forward into the
D6 gate (local Tesseract vs OCR API — dependency/cost trade put to Jaimie;
no OCR library installed or imported before that confirmation). Adds an OCR
cost line to the D6 projection. The sub-sample size and selection method
are fixed at the D6 gate and recorded here. Must not drift toward (c)
regardless of how large the `ocr_needed` set proves to be.
*Supersedes Q3 (was "Open").*

**Q9. `usable_text` threshold — confirmed (supersedes Q6): 250.**
*Decision:* **250 characters**, confirmed. The `usable_text` floor and the
HTML nav/stub `not_a_document` cutoff.
*Rationale:* As Q6 — conservative floor for "a real, readable document";
confirmed unchanged at the pre-crawl gate.
*Consequences:* Wired value stands; the verdict states it and reports
sensitivity where feasible.
*Supersedes Q6 (was "Open — default 250").*

**Q10. Crawl-safety parameters — confirmed (Jaimie sign-off).**
*Decision:* Per-host rate limit **1 req / 5.0 s** same host; connect
timeout **10 s**; read timeout **30 s**; hard max file size **50 MiB**;
max redirects **5** (every hop recorded + re-safety-checked); User-Agent
`iati-corpus-access-probe/0.1 (IATI linked-document access & readability
research; +https://github.com/jaimiegrant-undp/iati-corpus-access-probe)`.
*Rationale:* Polite research-crawl posture; the User-Agent is honest,
non-spoofed, and carries a resolving public contact URL (the `+URL` form is
conventional). These are binding crawl-safety values, signed off by Jaimie
per CLAUDE.md process rules — not tunable for speed, not loosened
autonomously.
*Consequences:* Wired as the `CrawlPolicy` defaults; the live crawl uses
exactly these. Any later change requires a fresh sign-off and a superseding
entry. A retained-corpus re-scope would require re-confirmation.

**Q11. Per-country frame query — confirmed (Phase 0.5-faithful, no status
scoping).**
*Decision:* The per-country sampling frame is
`recipient_country_code:{cc} AND document_link_url:*` — recipient-country
plus document-link presence, **no `activity_status_code` clause**, no other
scope refinement. Mirrors Phase 0.5's `_present()` form exactly (`:*`, not
`[* TO *]`) for byte-level frame-comparability.
*Rationale:* Read-only inspection of the Phase 0.5 repo (`iati-deeper-data/
scaffolding`, *"IATI Corpus Baseline — Phase 0.5"*) is authoritative
(read-only by user instruction, no cross-import). It applies **no**
activity-status filter and no base/default `fq`. Evidence:
`harvest.py:53-55` — `_present(f)` returns `f"{f}:*"`;
`harvest.py:67,84` — the per-country filter is exactly
`cc = [f"recipient_country_code:{iso}"]`;
`harvest.py` `country_metrics` — denominator `ds.count(fq=cc)` and document
population `doc_any = ds.count(q=_present("document_link_url"), fq=cc)`;
`country_record` records `"denominator_field": "recipient_country_code
(activity-level)"`; `iati.py:140-160` — `query()` defaults `q="*:*"`,
`fq=None`; full-tree scope-term scan (`status`/`valid`/`current`/
`pipeline`/`cancelled`) across `scaffolding/*.py` returns zero
activity-status references. Adding a status clause on its own merits was
considered and rejected: it would diverge from the Phase 0.5/0.6 coverage
baseline, and comparability outweighs a marginally tidier frame.
*Consequences:* Supersedes the wording in `SIGNAL-METHOD §1.3` that
described Phase 0.5 as "valid, current" (an inaccurate paraphrase the
probe's docs had inherited; §1.3 corrected in the same change). The
pre-draw extension to verify `activity_status_code` is dropped — nothing
to verify; `verify_fields` on the five `DOCLINK_FIELDS` stands. The
verdict must state the frame explicitly so a reader can read this probe
against Phase 0.5/0.6 by like-for-like.

**Q12. Realised draw — recorded (completes Q7).**
*Decision (record):* The seeded draw was executed on **2026-05-19** with
seed **`iati-access-probe-2026-05-19`** (the value anticipated by Q7).
`verify_fields` on the five `DOCLINK_FIELDS` passed against the live
Datastore (single probe call). Per-country sample size n=**400**
(Q7). All 18 country frames exceeded the target, so **no country is a
census**. Per-country frames ranged from VU=837 to BR=13,898;
`SB`=1,250, `WS`=1,144 for the Pacific SIDS cut.
**Total drawn pre cross-country dedup: 7,200.**
**Union distinct URLs after cross-country dedup: 6,934.**
**Distinct hosts in the union: 234.**
*Rationale:* This is the fact-record of the live half of D2, made on
Q11's confirmed Phase-0.5-faithful frame query
(`recipient_country_code:{cc} AND document_link_url:*`).
*Consequences:* D6 projection (`cache/projection.json`, gitignored) sits
on these realised numbers. Hard-ceiling check (~7,000, SIGNAL-METHOD §5):
**6,934 ≤ 7,000 — within bound, no re-scope triggered**. Per-country
samples are written to `cache/sample/{cc}.json` (gitignored, re-drawable
from this seed). The crawl go-ahead is the next gate; the D6 projection
is the artefact it is decided on.
