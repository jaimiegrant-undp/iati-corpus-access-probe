"""D8 — findings tables (SIGNAL-ROADMAP deliverable 8).

Reads the per-country metric caches (the authoritative source of truth —
NOT the per-country progress log, which records only each run's freshly
crawled rows) and emits the committed CSV findings tables to output/.

Every rate carries its denominator. The four readability sub-questions are
kept distinct and never collapsed (SIGNAL-METHOD output rules):
  1. resolves            — the URL returned 2xx
  2. format-true         — detected format matches the declared MIME type
  3. extractable-text    — a text layer / native text came out (vs scanned)
  4. usable-text         — enough text to be a real document (>= Q9 = 250)
plus the composite reachable_and_readable, reported BOTH including and
excluding the ocr_needed segment (SIGNAL-METHOD §3).

Counts/identifiers only — no document content (location-safety).
"""

from __future__ import annotations

import csv
import json
import math
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from iati_access_probe.countries import COUNTRIES, PACIFIC_SIDS  # noqa: E402

CACHE = ROOT / "cache" / "metrics"
OUT = ROOT / "output"
DATASTORE_SNAPSHOT = "2026-05-19"
CRAWL_DATES = "2026-05-19 (BD–MD) / 2026-05-21 (ML–WS re-crawl after DNS-outage cleanup)"
USABLE_TEXT_THRESHOLD = 250


def _wilson(k: int, n: int) -> tuple[float, float]:
    """95% Wilson score interval for a proportion (lo, hi), as percentages."""
    if n == 0:
        return (0.0, 0.0)
    z = 1.96
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / d
    return (round(100 * (centre - half), 1), round(100 * (centre + half), 1))


def _rows(cc: str) -> list[dict]:
    p = CACHE / f"{cc}.jsonl"
    return [json.loads(l) for l in p.read_text("utf-8").splitlines() if l.strip()]


def _pct(k: int, n: int) -> float:
    return round(100 * k / n, 1) if n else 0.0


def analyse_country(cc: str, rows: list[dict]) -> dict:
    n = len(rows)
    resolved = sum(1 for r in rows if r.get("resolved"))
    barriers = Counter(r.get("access_barrier", "none") for r in rows)
    errors = Counter(r["error_category"] for r in rows if r.get("error_category"))
    outcomes = Counter(r["extraction_outcome"] for r in rows
                       if r.get("extraction_outcome"))
    offdomain = sum(1 for r in rows if r.get("redirect_offdomain"))

    fmt_assessed = [r for r in rows if r.get("format_match") is not None]
    fmt_match = sum(1 for r in fmt_assessed if r["format_match"])
    declared_pdf_html = sum(1 for r in rows if r.get("declared_pdf_actually_html"))

    text_extracted = outcomes.get("text_extracted", 0)
    ocr_needed = outcomes.get("ocr_needed", 0)
    usable = sum(1 for r in rows if r.get("usable_text"))
    rr_incl = sum(1 for r in rows if r.get("reachable_and_readable"))
    rr_excl = sum(1 for r in rows
                  if r.get("resolved") and r.get("access_barrier") == "none"
                  and r.get("usable_text"))
    rr_lo, rr_hi = _wilson(rr_incl, n)

    return {
        "country": cc,
        "pacific_sids": cc in PACIFIC_SIDS,
        "n": n,
        # 1. resolves
        "resolved_n": resolved,
        "resolved_pct": _pct(resolved, n),
        # access barriers
        "auth_required_n": barriers.get("auth_required", 0),
        "robots_disallowed_n": barriers.get("robots_disallowed", 0),
        "oversize_n": barriers.get("oversize", 0),
        "non_public_host_n": barriers.get("non_public_host", 0),
        # errors
        "dns_failure_n": errors.get("dns_failure", 0),
        "timeout_n": errors.get("timeout", 0),
        "tls_error_n": errors.get("tls_error", 0),
        "connection_error_n": errors.get("connection_error", 0),
        "too_many_redirects_n": errors.get("too_many_redirects", 0),
        "offdomain_redirect_n": offdomain,
        # 2. format-true
        "format_assessed_n": len(fmt_assessed),
        "format_match_n": fmt_match,
        "format_match_pct": _pct(fmt_match, len(fmt_assessed)),
        "declared_pdf_actually_html_n": declared_pdf_html,
        # 3. extractable-text vs scanned
        "text_extracted_n": text_extracted,
        "ocr_needed_n": ocr_needed,
        "extraction_failed_n": outcomes.get("extraction_failed", 0),
        "not_a_document_n": outcomes.get("not_a_document", 0),
        # 4. usable-text
        "usable_text_n": usable,
        "usable_text_pct": _pct(usable, n),
        # composite
        "reachable_readable_incl_ocr_n": rr_incl,
        "reachable_readable_incl_ocr_pct": _pct(rr_incl, n),
        "reachable_readable_incl_ocr_ci95": f"{rr_lo}–{rr_hi}",
        "reachable_readable_excl_ocr_n": rr_excl,
        "reachable_readable_excl_ocr_pct": _pct(rr_excl, n),
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    per_country = [analyse_country(cc, _rows(cc)) for cc in COUNTRIES]

    # pooled row
    allrows = [r for cc in COUNTRIES for r in _rows(cc)]
    pooled = analyse_country("POOLED", allrows)
    pooled["pacific_sids"] = ""

    header = list(per_country[0].keys())
    with (OUT / "findings_per_country.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        for row in per_country:
            w.writerow(row)
        w.writerow(pooled)

    # pooled distributions
    def _dist_csv(name: str, counter: Counter, denom: int) -> None:
        with (OUT / name).open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["key", "count", "pct_of_sample"])
            for k, v in counter.most_common():
                w.writerow([k, v, _pct(v, denom)])

    N = len(allrows)
    _dist_csv("distribution_access_barrier.csv",
              Counter(r.get("access_barrier", "none") for r in allrows), N)
    _dist_csv("distribution_error_category.csv",
              Counter(r["error_category"] for r in allrows if r.get("error_category")), N)
    _dist_csv("distribution_extraction_outcome.csv",
              Counter(r.get("extraction_outcome") or "not_assessed" for r in allrows), N)
    _dist_csv("distribution_detected_format.csv",
              Counter(r.get("detected_format") or "not_fetched" for r in allrows), N)

    # provenance header file
    (OUT / "findings_README.md").write_text(
        f"""# IATI Corpus Access Probe — findings tables

- **Datastore snapshot date:** {DATASTORE_SNAPSHOT}
- **Crawl dates:** {CRAWL_DATES}
- **Sample:** {N} distinct document URLs, n=400 per country across the 18
  Phase 0.5/0.6 partner countries (seeded draw, seed
  `iati-access-probe-2026-05-19`; Decisions Log Q7/Q12). No census countries.
- **Frame query (Q11, Phase 0.5-faithful):** `recipient_country_code:{{cc}} AND document_link_url:*`
- **usable_text threshold (Q9):** {USABLE_TEXT_THRESHOLD} characters.

The four readability sub-questions are distinct and must not be collapsed:
resolves / format-true / extractable-text / usable-text. The composite
`reachable_and_readable` is reported both including and excluding the
`ocr_needed` segment. Counts/identifiers only — no document content.

Files: `findings_per_country.csv` (per-country + POOLED),
`distribution_*.csv` (pooled distributions).
""", encoding="utf-8")

    # console summary
    print(f"Sample: {N} URLs, {len(COUNTRIES)} countries.")
    print(f"POOLED: resolved {pooled['resolved_pct']}% | "
          f"reachable_and_readable incl-ocr {pooled['reachable_readable_incl_ocr_pct']}% "
          f"(excl-ocr {pooled['reachable_readable_excl_ocr_pct']}%)")
    print(f"  format_match {pooled['format_match_pct']}% | "
          f"declared_pdf_actually_html {pooled['declared_pdf_actually_html_n']}")
    print(f"  barriers: auth={pooled['auth_required_n']} "
          f"robots={pooled['robots_disallowed_n']} "
          f"oversize={pooled['oversize_n']} non_public={pooled['non_public_host_n']}")
    print(f"  outcomes: text={pooled['text_extracted_n']} ocr={pooled['ocr_needed_n']} "
          f"failed={pooled['extraction_failed_n']} not_a_doc={pooled['not_a_document_n']}")
    print(f"Wrote findings to {OUT.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
