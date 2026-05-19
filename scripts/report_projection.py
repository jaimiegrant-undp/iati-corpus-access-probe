"""D6 — cost & scale projection over the realised samples.

Reads the per-country CountrySample files from cache/sample/, runs
projection.build_projection, prints the human-readable summary the crawl
go-ahead is decided on, and writes a machine-readable JSON copy to
cache/projection.json (gitignored — counts/IDs only, no document content).

Pure local read of already-drawn samples. No network, no key. Re-runnable.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from iati_access_probe.countries import COUNTRIES, PACIFIC_SIDS  # noqa: E402
from iati_access_probe.models import CrawlPolicy  # noqa: E402
from iati_access_probe.projection import build_projection  # noqa: E402
from iati_access_probe.sampler import read_country_sample  # noqa: E402

# Match the draw run (Decisions Log Q7).
DRAW_SEED = "iati-access-probe-2026-05-19"


def main() -> int:
    cache = ROOT / "cache" / "sample"
    samples = [read_country_sample(cache / f"{cc}.json") for cc in COUNTRIES]

    proj = build_projection(
        samples,
        CrawlPolicy(),  # confirmed defaults — Decisions Log Q10
        ocr_engine="local_tesseract",
        ocr_subsample_target=150,
        ocr_seed=DRAW_SEED,
        ocr_per_page_usd=0.0,
        ocr_mean_pages_assumed=12.0,
    )

    scale = proj.scale
    wall = proj.wallclock
    ocr = proj.ocr

    print(f"=== D6 projection — seed {DRAW_SEED} ===\n")
    print("Per-country distinct URLs drawn:")
    for cc in COUNTRIES:
        sids = " (Pacific SIDS)" if cc in PACIFIC_SIDS else ""
        print(f"  {cc}: {scale.per_country_distinct[cc]}{sids}")
    print(f"\nUnion distinct URLs (cross-country dedup): {scale.union_distinct}")
    print(f"Distinct hosts:                              {scale.distinct_hosts}")
    print(f"Census countries (frame <= target):          "
          f"{', '.join(scale.census_countries) or 'none'}")

    print("\nWall-clock band (sequential, concurrency 1):")
    print(f"  lower {wall.lower_human}  ({wall.lower_s:.0f}s)")
    print(f"  upper {wall.upper_human}  ({wall.upper_s:.0f}s)")
    print(f"  assumptions: {wall.assumptions}")

    print("\nOCR cost line (Q8 = (b), local Tesseract, sub-sample <= "
          f"{ocr.subsample_target}):")
    for share in ocr.scanned_share_band:
        n = ocr.projected_subsample_by_share[share]
        c = ocr.projected_cost_usd_by_share[share]
        print(f"  scanned-share {share:.0%}: subsample={n:3d}  cost=${c}")

    # Hard-ceiling check (Q7 / SIGNAL-METHOD §5).
    CEILING = 7000
    breach = scale.union_distinct > CEILING
    print(f"\nHard-ceiling check (~{CEILING}): union {scale.union_distinct} "
          f"=> {'BREACH — stop & re-scope' if breach else 'within bound'}")

    print("\nNotes:")
    for n in proj.notes:
        print(f"  - {n}")

    # Machine-readable for the verdict.
    out = ROOT / "cache" / "projection.json"
    out.write_text(json.dumps({
        "seed": DRAW_SEED,
        "per_country_distinct": scale.per_country_distinct,
        "union_distinct": scale.union_distinct,
        "distinct_hosts": scale.distinct_hosts,
        "census_countries": list(scale.census_countries),
        "wallclock_lower_s": wall.lower_s,
        "wallclock_upper_s": wall.upper_s,
        "wallclock_assumptions": wall.assumptions,
        "ocr_engine": ocr.engine,
        "ocr_subsample_target": ocr.subsample_target,
        "ocr_per_page_usd": ocr.per_page_usd,
        "ocr_projected_subsample_by_share": ocr.projected_subsample_by_share,
        "ocr_projected_cost_usd_by_share": ocr.projected_cost_usd_by_share,
        "hard_ceiling": CEILING,
        "hard_ceiling_breached": breach,
    }, indent=2, sort_keys=True), encoding="utf-8")
    print(f"\nWrote {out.relative_to(ROOT)} (gitignored).")
    return 1 if breach else 0


if __name__ == "__main__":
    raise SystemExit(main())
