"""Offline tests for the D6 cost & scale projection (stdlib unittest).

No network, no key. Synthetic CountrySample inputs; the tests pin the
arithmetic, the cross-country dedup, census detection, the wall-clock band
shape, and the OCR cost band — local (nil) vs API (formula), capped
sub-sample.

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from iati_access_probe.models import (  # noqa: E402
    CountrySample,
    CrawlPolicy,
    DistinctDocumentURL,
)
from iati_access_probe.projection import (  # noqa: E402
    build_projection,
    corpus_scale,
    estimate_wallclock,
    ocr_cost_line,
)


def _durl(url: str) -> DistinctDocumentURL:
    return DistinctDocumentURL(
        url=url, primary_category="A01", primary_format="application/pdf",
        occurrence_count=1, category_counts={"A01": 1},
        format_counts={"application/pdf": 1}, iati_identifiers=("XX-1",),
    )


def _sample(country, urls, *, frame=None, census=False) -> CountrySample:
    return CountrySample(
        country=country, seed="s", requested_n=400,
        frame_size=frame if frame is not None else len(urls),
        is_census=census, sampled=tuple(_durl(u) for u in urls),
    )


POLICY = CrawlPolicy(per_host_interval_s=5.0)


class TestCorpusScale(unittest.TestCase):
    def test_per_country_and_cross_country_dedup(self):
        a = _sample("FJ", ["http://h1/a", "http://h1/b", "http://h2/c"])
        b = _sample("VU", ["http://h2/c", "http://h3/d"])  # h2/c shared
        scale = corpus_scale([a, b])
        self.assertEqual(scale.per_country_distinct, {"FJ": 3, "VU": 2})
        self.assertEqual(scale.union_distinct, 4)  # h2/c counted once
        self.assertEqual(scale.distinct_hosts, 3)  # h1, h2, h3

    def test_census_countries_recorded(self):
        a = _sample("WS", ["http://h/a"], frame=1, census=True)
        b = _sample("BD", ["http://h/b", "http://h/c"])
        scale = corpus_scale([a, b])
        self.assertEqual(scale.census_countries, ("WS",))


class TestWallClock(unittest.TestCase):
    def test_band_arithmetic_and_ordering(self):
        a = _sample("FJ", [f"http://h1/{i}" for i in range(10)])  # 10 urls, 1 host
        scale = corpus_scale([a])
        w = estimate_wallclock(
            scale, POLICY,
            mean_request_s_low=1.0, mean_request_s_high=2.0,
            robots_request_s=2.0, retry_fraction=0.0,
        )
        self.assertEqual(w.lower_s, 10 * 1.0)
        # upper = 10*2 + (10-1)*5 + 1*2 = 20 + 45 + 2 = 67
        self.assertEqual(w.upper_s, 67.0)
        self.assertGreater(w.upper_s, w.lower_s)

    def test_human_format(self):
        a = _sample("FJ", [f"http://h/{i}" for i in range(2000)])
        w = estimate_wallclock(corpus_scale([a]), POLICY)
        self.assertRegex(w.upper_human, r"\d+h \d+m|\d+m \d+s")


class TestOcrCostLine(unittest.TestCase):
    def test_local_engine_is_nil_cost(self):
        scale = corpus_scale([_sample("FJ", [f"http://h/{i}" for i in range(1000)])])
        line = ocr_cost_line(
            scale, engine="local_tesseract", subsample_target=150,
            seed="ocr-2026", per_page_usd=0.0, mean_pages_assumed=12.0,
        )
        self.assertTrue(all(c == 0.0 for c in line.projected_cost_usd_by_share.values()))
        self.assertIn("seeded", line.selection)

    def test_api_engine_cost_band_and_subsample_cap(self):
        scale = corpus_scale([_sample("FJ", [f"http://h/{i}" for i in range(1000)])])
        line = ocr_cost_line(
            scale, engine="ocr_api", subsample_target=150,
            seed="ocr-2026", per_page_usd=0.02, mean_pages_assumed=10.0,
            scanned_share_band=(0.10, 0.60),
        )
        # 10% scanned -> 100 est -> sub = min(150, 100) = 100 -> 100*10*0.02
        self.assertEqual(line.projected_subsample_by_share[0.10], 100)
        self.assertEqual(line.projected_cost_usd_by_share[0.10], 20.0)
        # 60% scanned -> 600 est -> sub capped at target 150 -> 150*10*0.02
        self.assertEqual(line.projected_subsample_by_share[0.60], 150)
        self.assertEqual(line.projected_cost_usd_by_share[0.60], 30.0)

    def test_subsample_never_exceeds_target(self):
        scale = corpus_scale([_sample("FJ", [f"http://h/{i}" for i in range(9000)])])
        line = ocr_cost_line(
            scale, engine="ocr_api", subsample_target=150, seed="s",
            per_page_usd=0.02, mean_pages_assumed=10.0,
            scanned_share_band=(0.99,),
        )
        self.assertLessEqual(max(line.projected_subsample_by_share.values()), 150)


class TestBuildProjection(unittest.TestCase):
    def test_assembles_and_carries_notes(self):
        samples = [
            _sample("FJ", ["http://h1/a", "http://h1/b"]),
            _sample("WS", ["http://h2/c"], frame=1, census=True),
        ]
        p = build_projection(
            samples, POLICY,
            ocr_engine="local_tesseract", ocr_subsample_target=150,
            ocr_seed="ocr-2026", ocr_per_page_usd=0.0,
            ocr_mean_pages_assumed=12.0,
        )
        self.assertEqual(p.scale.union_distinct, 3)
        self.assertTrue(any("Census countries" in n for n in p.notes))
        self.assertTrue(any("never the full scanned set" in n for n in p.notes))
        self.assertGreater(p.wallclock.upper_s, p.wallclock.lower_s)


if __name__ == "__main__":
    unittest.main()
