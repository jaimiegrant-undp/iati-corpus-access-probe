"""Q8(b) OCR-yield estimate — seeded, capped sub-sample of the ocr_needed set.

The probe does not retain document bytes (retention boundary), so the bytes
of scanned docs were released after the crawl. Measuring OCR yield therefore
re-fetches a seeded, CAPPED sub-sample (never the whole set — that is (c))
through the SAME safe crawler, OCRs each body in-process with local
Tesseract, and records the recoverable CHARACTER COUNT only — never the text
(location-safety). Bytes are released as each doc is assessed.

Output: cache/ocr_yield.json (gitignored, per-doc counts) and
output/ocr_yield_summary.json (committed, aggregate counts only).
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from iati_access_probe.countries import COUNTRIES  # noqa: E402
from iati_access_probe.crawler import crawl_url  # noqa: E402
from iati_access_probe.models import CrawlPolicy  # noqa: E402
from iati_access_probe.ocr import (  # noqa: E402
    estimate_yield,
    ocr_char_count,
    resolve_tesseract_cmd,
    select_subsample,
)
from iati_access_probe.readability import _detect  # noqa: E402
from iati_access_probe.safety import (  # noqa: E402
    HostRateLimiter,
    RobotsCache,
    system_resolver,
)
from iati_access_probe.transport import requests_fetcher, robots_fetch_via  # noqa: E402

DRAW_SEED = "iati-access-probe-2026-05-19"
SUBSAMPLE_TARGET = 150
USABLE_TEXT_THRESHOLD = 250
CACHE = ROOT / "cache" / "metrics"


def _ocr_needed_urls() -> list[str]:
    urls: list[str] = []
    for cc in COUNTRIES:
        for line in (CACHE / f"{cc}.jsonl").read_text("utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("extraction_outcome") == "ocr_needed":
                urls.append(r["url"])
    return urls


def main() -> int:
    resolve_tesseract_cmd()  # loud-fail early if the binary isn't found
    population = _ocr_needed_urls()
    sub = select_subsample(population, target=SUBSAMPLE_TARGET, seed=DRAW_SEED)
    print(f"ocr_needed population: {sub.population}  subsample: "
          f"{len(sub.selected_urls)} (capped at {SUBSAMPLE_TARGET}, "
          f"is_capped={sub.is_capped})")

    policy = CrawlPolicy()
    rate_limiter = HostRateLimiter(
        policy.per_host_interval_s, clock=time.monotonic, sleep=time.sleep
    )
    fetcher = requests_fetcher()
    robots = RobotsCache(
        robots_fetch_via(
            fetcher, policy.user_agent,
            timeout=(policy.connect_timeout_s, policy.robots_timeout_s),
        ),
        rate_limiter=rate_limiter,
    )

    char_counts: dict[str, int] = {}      # successfully re-fetched + OCR'd
    refetch_failed: list[str] = []        # could not re-fetch a body this time

    def sink(result, body: bytes) -> None:
        _mime, cls = _detect(body)
        char_counts[result.url] = ocr_char_count(body, cls)

    for i, url in enumerate(sub.selected_urls, 1):
        before = len(char_counts)
        crawl_url(
            url, policy=policy, fetcher=fetcher, resolver=system_resolver,
            robots=robots, rate_limiter=rate_limiter, on_content=sink,
        )
        if len(char_counts) == before:
            refetch_failed.append(url)
        if i % 25 == 0:
            print(f"  ...{i}/{len(sub.selected_urls)} re-fetched")

    est = estimate_yield(
        char_counts, subsample=sub, usable_text_threshold=USABLE_TEXT_THRESHOLD
    )

    # gitignored per-doc detail (counts only)
    (ROOT / "cache" / "ocr_yield.json").write_text(json.dumps({
        "seed": sub.seed,
        "per_doc_char_counts": char_counts,
        "refetch_failed": refetch_failed,
    }, indent=2, sort_keys=True), encoding="utf-8")

    # committed aggregate (counts only — no urls, no text)
    summary = {
        "seed": sub.seed,
        "ocr_needed_population": sub.population,
        "subsample_target": SUBSAMPLE_TARGET,
        "subsample_selected": len(sub.selected_urls),
        "is_capped": sub.is_capped,
        "refetched_and_ocrd_n": est.n,
        "refetch_failed_n": len(refetch_failed),
        "usable_text_threshold": USABLE_TEXT_THRESHOLD,
        "mean_recoverable_chars": round(est.mean_chars, 1),
        "median_recoverable_chars": est.median_chars,
        "share_reaching_usable_pct": round(100 * est.share_reaching_usable, 1),
        "engine": "local_tesseract",
        "note": "Recoverable-text estimate on a seeded capped sub-sample; "
                "char counts only, no text retained. Re-fetch was required "
                "because document bytes are not retained (retention boundary).",
    }
    (ROOT / "output" / "ocr_yield_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
