# Verdict — IATI Corpus Access Probe (Layer 1)

## How much of IATI's linked-document corpus is actually accessible and readable?

**Short answer: about 43%.** Of the linked documents IATI publishers attach
to their activities, fewer than half are both reachable and readable — the
URL resolves, the file is what it claims, and a usable amount of text comes
out. The single largest reason the other ~57% falls away is **not** link rot;
it is **authentication walls** (a quarter of all linked documents), followed
by non-document landing/error pages, publisher `robots.txt` disallows, and
extraction failures.

---

### Provenance (stated on every output)

- **Datastore snapshot:** 2026-05-19 (IATI Datastore v3 `activity` collection).
- **Crawl dates:** 2026-05-19 (BD–MD) and 2026-05-21 (ML–WS, re-crawled after a
  local DNS-outage cleanup — see Limits).
- **Sample:** 7,200 document links drawn, n=400 per country across the same 18
  partner countries as the Phase 0.5/0.6 baselines (seeded, reproducible;
  seed `iati-access-probe-2026-05-19`). No census countries — every country's
  frame exceeded 400.
- **Frame (Phase 0.5-faithful, Decisions Log Q11):**
  `recipient_country_code:{cc} AND document_link_url:*` — no activity-status
  scoping, matching Phase 0.5 exactly so the access picture reads against the
  coverage picture like-for-like.
- **`usable_text` threshold (Q9):** 250 characters.
- Access and readability are *measured rates as of the crawl date*. Every
  figure traces to the sample, the crawl, and the snapshot above.

---

## The four sub-questions, kept distinct

These are four different things and the verdict does not collapse them
(pooled, n=7,200):

| Sub-question | Measure | Result |
|---|---|---:|
| 1. Does the link **resolve**? | 2xx response | **60.9%** (4,387) |
| 2. Is the **format true**? | detected matches declared MIME | **87.9%** of fetched; but **193** declared-PDFs were actually HTML |
| 3. Is the content **extractable text**? | native/text-layer extraction | **41.2%** text-extracted; a further **2.2%** scanned (`ocr_needed`) |
| 4. Is a **usable amount** of text present? | ≥250 characters | **40.9%** |

**Composite — reachable AND readable: 43.1%** including the scanned segment
that OCR can recover (95% CI 41.9–44.2), **40.9%** excluding it. Adjusting for
the *measured* OCR yield (below), the honest figure is **~42%**.

Put differently: of the 60.9% of links that resolve at all, roughly **71%**
clear the readability bar. Resolution is the bigger filter; readability of
what resolves is comparatively good.

---

## The six core questions

**1. Resolution.** 60.9% of sampled links return a live 2xx. The remainder is
dominated not by dead links but by access barriers (next answer). Genuine
network death is small: `dns_failure` 0.1% (7 URLs), `timeout` 1.5%,
`tls_error` 0.7%, `connection_error` 0.8%, `too_many_redirects` 2 URLs.
Off-domain redirects were a minor feature, recorded per hop.

**2. Format truth.** Where a file was fetched, declared and detected format
agree 87.9% of the time. The notable failure mode is the classic one:
**193 links (2.7%) declared a PDF but returned HTML** — an error page or a
landing page, not the document. These are counted as `not_a_document`, never
as readable.

**3. Readability.** Of everything sampled, 41.2% yielded extractable text
directly; 2.2% (156 distinct URLs) were scanned-image PDFs or images with no
text layer (`ocr_needed`); 6.5% failed extraction (`extraction_failed`,
corrupt/unsupported/parser error); and **12.6% (910) resolved to something
that is not a document** — HTML navigation, an error page, a portal stub.
A near-empty extraction is recorded as a finding, not as a usable document.

**4. Access barriers.** This is where the corpus is lost:

| Barrier | Count | Share of sample |
|---|---:|---:|
| `auth_required` | **1,887** | **26.2%** |
| `robots_disallowed` | 585 | 8.1% |
| `oversize` | 1 | 0.0% |
| `non_public_host` | 0 | 0.0% |

**Over a quarter of all linked documents sit behind authentication.** The
`robots_disallowed` share is concentrated on a handful of hosts —
`procurement-notices.undp.org`, `documents.iati.openaid.se`, and `www.gavi.org`
recurred as disallowing hosts across nearly every country. Both are publisher
*postures*, recorded as neutral access facts, not defects. No linked document
resolved to a private/loopback address (`non_public_host` = 0): a clean result
on that data-quality/SSRF check.

**5. The readable denominator.** **~43% (95% CI 41.9–44.2).** This is the real
population a content assessment or corpus build could work on. It is the
number that should size every downstream estimate — not the ~1.5m
document-link instances in the raw metadata.

**6. Distribution of the gap.** Per-country reachable-and-readable ranges from
**20.8% (BR)** to **62.8% (VU)**. The spread tracks the access barriers, not
the country: the lowest scorers (BR 20.8%, IN 25.0%, NP 29.2%, CO 31.0%) are
the ones whose samples are dominated by `auth_required` (BR alone: 284/400
behind auth). Because the corpus is donor-skewed (most documents sit on a few
large multilateral/government hosts — Phase 0.5 §7), a country's readable
picture is **mostly its donors' hosting practices, not its own**.

---

## Findings worth stating in their own right

**The Pacific SIDS equity concern is not borne out for access.** Of the four
Pacific SIDS, three are **above** the pooled mean — VU 62.8% (the highest of
all 18 countries), SB 53.0%, WS 52.8% — and only FJ (33.8%) is below it. The
donor-skew that is a problem elsewhere cuts *favourably* here: SIDS documents
are hosted by the same reliable multilateral infrastructure (World Bank,
UNICEF, ADB, etc.) as everyone else's, so their access is not penalised by
small-state hosting capacity. Whatever the equity questions for the Pacific
SIDS, *document accessibility* is not one of them on this evidence.

**The corpus is far more country-distinct than the raw metadata implied.**
Of 7,200 document links drawn, **6,934 (96.3%) are distinct URLs** — only
~3.7% recurrence across countries. Phase 0.5 established that the same document
is linked from many *activities* (link-occurrence inflation); this probe shows
that at the *cross-country* level the linked corpus is overwhelmingly distinct.
The deduplicated URL count, not the link-occurrence count, is the honest
denominator for any corpus-size estimate.

**Scanned documents are mostly recoverable.** Of the `ocr_needed` segment, a
seeded capped sub-sample (150 of 156 distinct, local Tesseract) recovered
**usable text (≥250 chars) for 70.0%** of documents — mean 32,671 characters,
median 7,341. So including the scanned segment in "readable" is justified for
roughly seven in ten of those files; the OCR-adjusted reachable-and-readable
figure is ~42%, between the 40.9% (no OCR) and 43.1% (all scanned assumed
recoverable) bounds. **This is a local-Tesseract estimate** — a cloud OCR
engine might recover somewhat more from poor-quality scans; the local figure
is acceptably conservative for a readability probe and is named as such.

---

## Honest limits (SIGNAL-METHOD §6)

- **A snapshot of a moving target.** Link rot is time-sensitive; every figure
  is dated to the crawl. This is access *as of 2026-05-19/21*.
- **Sample, not census.** n=400 distinct URLs/country; per-country rates carry
  the 95% Wilson CIs stated in the findings table. The pooled figure is tight
  (±~1.1pp); per-country figures are wider (±~5pp).
- **Politeness vs coverage.** A transient host problem on the crawl day can
  register as a failure for a URL that is normally fine; the polite pace and a
  single retry mitigate but do not eliminate this.
- **`detected_format` is best-effort** (magic-byte + content-type); exotic or
  malformed files may be mis-detected.
- **Off-domain redirect detection is best-effort by design** (curated
  two-label-suffix set, not the full Public Suffix List); the per-hop
  non-public-host SSRF check is independent and not best-effort.
- **OCR detection vs yield.** Detecting `ocr_needed` is reliable; the
  recoverable-text figure is a **local-Tesseract estimate on a seeded
  sub-sample**, pooled not per-country.
- **"Readable" is not "useful."** This probe establishes a document can be
  opened and yields text. Whether that text is substantively useful — for
  synthesis, search, or geography — is **Layer 2's question, not answered
  here.**
- **Donor-skew inherited.** A country's picture is largely its donors' hosting
  practices.
- **Auth/paywall conservatively classified** (inferred from response patterns;
  may under- or over-count).
- **No retained corpus.** The probe measured documents and kept none; Layer 2
  will re-crawl its own smaller, readable sample.
- **Local DNS outage during the run (mitigated).** The crawl hit a local DNS
  outage on the build host at country 10 of 18, with a ten-second messy onset.
  Against a baseline of zero `dns_failure` across the first nine countries
  (0/3,600), this was unambiguously the host's resolver, not the publishers.
  The 43 onset-window rows were treated conservatively as outage artefacts and
  re-crawled, not retained on weak evidence; the affected country was
  surgically cleaned and the remaining nine re-crawled under restored network.
  The clean re-crawl returned a normal ~0.1% `dns_failure` baseline (7/7,200).
  Cleanup is documented in commit history (tag `pre-cleanup-2026-05-19`); these
  figures use only clean measurements.

---

## Licensing flag for a retained corpus (not resolved here)

This probe **measured** documents and **retained none** — fetched bytes were a
transient working cache, released after each readability assessment. Because
nothing is retained, the probe raises no redistribution question. **The later
corpus build — which would *retain* documents — does raise a licensing
question that must be resolved before that build proceeds.** Linked documents
are published openly by publishers, but open publication is not a blanket
redistribution right. This is flagged, not resolved; it is a chat-and-human
decision for the corpus-build project.

---

## What this means for Layer 2 and the corpus build

1. **The denominator is ~43%, not ~100% of the metadata.** Any Layer 2 or
   corpus-build plan should size against the reachable-and-readable population,
   roughly 43% of linked documents (deduplicated), not the raw link count.
2. **Authentication, not link rot, is the binding constraint.** A quarter of
   the corpus is behind auth walls the probe (correctly) did not attempt to
   defeat. If the corpus build needs that quarter, it needs a
   *credentialing/permissions* strategy, not a better crawler.
3. **OCR is worth it.** ~70% of scanned documents yield usable text; the
   scanned segment should not be written off, but OCR is a real cost line the
   build must budget.
4. **The cross-country-distinct finding lowers the corpus-size estimate** and
   should be reflected in any scale/cost projection for the build.
5. **The Pacific SIDS are not an access-disadvantaged subset** — an equity
   reassurance for the programme, with FJ the one country worth a closer look.
6. **Resolve the retained-corpus licensing question first.**

*This is the whole deliverable: the findings tables (`output/*.csv`) and this
verdict. No tool, no UI, no retained document store.*
