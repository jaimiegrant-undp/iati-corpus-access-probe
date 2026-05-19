"""Offline tests for the document-link sampler (stdlib unittest, no pytest:
pytest would be a package beyond the SIGNAL.md stack — a stop-and-ask).

No network, no live key — the fixture is synthetic. Run:

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from iati_access_probe.models import (  # noqa: E402
    UNCATEGORISED,
    DocumentLinkOccurrence,
)
from iati_access_probe.sampler import (  # noqa: E402
    _allocate,
    dedupe_on_url,
    draw_country_sample,
    read_country_sample,
    total_distinct_urls,
    write_country_sample,
)

FIXTURE = Path(__file__).parent / "fixtures" / "sample_doclinks_fixture.json"


def load_occurrences() -> list[DocumentLinkOccurrence]:
    raw = json.loads(FIXTURE.read_text("utf-8"))["occurrences"]
    return [DocumentLinkOccurrence(**o) for o in raw]


class TestDedupe(unittest.TestCase):
    def setUp(self) -> None:
        self.distinct = dedupe_on_url(load_occurrences())
        self.by_url = {d.url: d for d in self.distinct}

    def test_collapses_to_distinct_urls(self) -> None:
        # 15 occurrences -> 12 distinct URLs (u1 x3, u3 x2, rest x1).
        self.assertEqual(len(self.distinct), 12)

    def test_returned_in_deterministic_url_order(self) -> None:
        urls = [d.url for d in self.distinct]
        self.assertEqual(urls, sorted(urls))

    def test_occurrence_count_preserved(self) -> None:
        self.assertEqual(self.by_url["https://example.org/u1.pdf"].occurrence_count, 3)
        self.assertEqual(self.by_url["https://example.org/u2.pdf"].occurrence_count, 1)

    def test_iati_identifiers_folded_in(self) -> None:
        u1 = self.by_url["https://example.org/u1.pdf"]
        self.assertEqual(u1.iati_identifiers, ("AA-1", "AA-2", "AA-3"))

    def test_modal_category_with_lexicographic_tiebreak(self) -> None:
        # u3 is linked once as A01 and once as A02 -> 1:1 tie -> smallest code.
        u3 = self.by_url["https://example.org/u3.pdf"]
        self.assertEqual(u3.primary_category, "A01")
        self.assertEqual(u3.category_counts, {"A01": 1, "A02": 1})
        self.assertTrue(u3.is_multi_category)

    def test_uncategorised_is_kept_not_dropped(self) -> None:
        cats = {d.primary_category for d in self.distinct}
        self.assertIn(UNCATEGORISED, cats)


class TestAllocation(unittest.TestCase):
    def test_proportional_largest_remainder(self) -> None:
        # sizes 3/3/4/2 (total 12), n=6 -> half each: 1.5,1.5,2,1.
        # leftover 1 goes to the largest fractional remainder, tie broken by
        # larger stratum then code asc -> A01.
        alloc = _allocate({"A01": 3, "A02": 3, "B01": 4, UNCATEGORISED: 2}, 6)
        self.assertEqual(alloc, {"A01": 2, "A02": 1, "B01": 2, UNCATEGORISED: 1})
        self.assertEqual(sum(alloc.values()), 6)

    def test_small_stratum_never_over_allocated(self) -> None:
        # A has only 1 URL; its proportional share rounds toward >1 but must
        # be capped at 1 and the freed quota redistributed to B.
        alloc = _allocate({"A": 1, "B": 10}, 6)
        self.assertEqual(alloc["A"], 1)
        self.assertEqual(alloc["B"], 5)
        self.assertEqual(sum(alloc.values()), 6)

    def test_total_always_equals_n(self) -> None:
        for n in range(1, 12):
            alloc = _allocate({"A01": 3, "A02": 3, "B01": 4, UNCATEGORISED: 2}, n)
            self.assertEqual(sum(alloc.values()), n, f"n={n}")
            for c, size in {"A01": 3, "A02": 3, "B01": 4, UNCATEGORISED: 2}.items():
                self.assertLessEqual(alloc[c], size, f"n={n} stratum {c}")


class TestDraw(unittest.TestCase):
    def setUp(self) -> None:
        self.occ = load_occurrences()

    def test_census_when_frame_smaller_than_n(self) -> None:
        s = draw_country_sample("AA", self.occ, n=100, seed="s1")
        self.assertTrue(s.is_census)
        self.assertEqual(s.drawn_n, 12)
        self.assertEqual(s.frame_size, 12)

    def test_stratified_draw_reflects_category_mix(self) -> None:
        s = draw_country_sample("AA", self.occ, n=6, seed="s1")
        self.assertFalse(s.is_census)
        self.assertEqual(s.drawn_n, 6)
        drawn_by_cat: dict[str, int] = {}
        for d in s.sampled:
            drawn_by_cat[d.primary_category] = drawn_by_cat.get(d.primary_category, 0) + 1
        self.assertEqual(drawn_by_cat, {"A01": 2, "A02": 1, "B01": 2, UNCATEGORISED: 1})
        # Every stratum's drawn count never exceeds its frame count.
        for cat, (frame_n, drawn_n) in s.stratum_breakdown.items():
            self.assertLessEqual(drawn_n, frame_n, cat)

    def test_reproducible_under_same_seed(self) -> None:
        a = draw_country_sample("AA", self.occ, n=6, seed="s1")
        b = draw_country_sample("AA", self.occ, n=6, seed="s1")
        self.assertEqual(
            [d.url for d in a.sampled], [d.url for d in b.sampled]
        )

    def test_different_seed_still_valid_draw(self) -> None:
        b = draw_country_sample("AA", self.occ, n=6, seed="different-seed")
        self.assertEqual(b.drawn_n, 6)
        self.assertEqual(len({d.url for d in b.sampled}), 6)

    def test_rejects_nonpositive_n(self) -> None:
        with self.assertRaises(ValueError):
            draw_country_sample("AA", self.occ, n=0, seed="s1")


class TestCacheRoundTrip(unittest.TestCase):
    def test_write_then_read_is_identical(self) -> None:
        s = draw_country_sample("AA", load_occurrences(), n=6, seed="s1")
        with tempfile.TemporaryDirectory() as tmp:
            path = write_country_sample(s, Path(tmp))
            self.assertTrue(path.exists())
            back = read_country_sample(path)
        self.assertEqual(back.country, s.country)
        self.assertEqual(back.seed, s.seed)
        self.assertEqual(back.is_census, s.is_census)
        self.assertEqual(
            [d.url for d in back.sampled], [d.url for d in s.sampled]
        )
        self.assertEqual(back.stratum_breakdown, s.stratum_breakdown)


class TestCrossCountryDedup(unittest.TestCase):
    def test_total_distinct_urls_dedups_across_countries(self) -> None:
        # Same URL sampled in two countries -> crawled once.
        occ = load_occurrences()
        a = draw_country_sample("AA", occ, n=100, seed="s1")
        b = draw_country_sample("BB", occ, n=100, seed="s1")
        self.assertEqual(a.drawn_n + b.drawn_n, 24)
        self.assertEqual(total_distinct_urls([a, b]), 12)


if __name__ == "__main__":
    unittest.main()
