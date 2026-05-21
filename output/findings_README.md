# IATI Corpus Access Probe — findings tables

- **Datastore snapshot date:** 2026-05-19
- **Crawl dates:** 2026-05-19 (BD–MD) / 2026-05-21 (ML–WS re-crawl after DNS-outage cleanup)
- **Sample:** 7200 distinct document URLs, n=400 per country across the 18
  Phase 0.5/0.6 partner countries (seeded draw, seed
  `iati-access-probe-2026-05-19`; Decisions Log Q7/Q12). No census countries.
- **Frame query (Q11, Phase 0.5-faithful):** `recipient_country_code:{cc} AND document_link_url:*`
- **usable_text threshold (Q9):** 250 characters.

The four readability sub-questions are distinct and must not be collapsed:
resolves / format-true / extractable-text / usable-text. The composite
`reachable_and_readable` is reported both including and excluding the
`ocr_needed` segment. Counts/identifiers only — no document content.

Files: `findings_per_country.csv` (per-country + POOLED),
`distribution_*.csv` (pooled distributions).
