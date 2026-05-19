"""The document-link sampler — pure, deterministic, offline-testable.

Pipeline (SIGNAL-METHOD §1.3–1.4):

  occurrences --dedupe_on_url--> distinct URLs
              --draw_country_sample--> a reproducible, category-stratified
                                       per-country sample

Determinism is load-bearing: every figure the verdict cites must be
reproducible from the recorded seed. So: URLs are sorted before sampling,
strata are processed in sorted order, and each stratum gets its own RNG
keyed by (seed, country, category) so adding or losing one category does not
reshuffle the others.

No network here. The Datastore wrapper (deliverable 3) feeds occurrences in;
the live seeded draw is gated on the IATI key. This module is exercised
entirely against fixtures.
"""

from __future__ import annotations

import json
import random
from collections import Counter
from collections.abc import Iterable, Sequence
from pathlib import Path

from .models import (
    CountrySample,
    DistinctDocumentURL,
    DocumentLinkOccurrence,
)


def _modal(counts: dict[str, int]) -> str:
    """Most frequent key; ties broken by lexicographically smallest key.

    The tie-break is what makes `primary_category` / `primary_format`
    reproducible when a URL is linked with several different codes.
    """
    return min(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0]


def dedupe_on_url(
    occurrences: Iterable[DocumentLinkOccurrence],
) -> list[DistinctDocumentURL]:
    """Collapse occurrences to distinct URLs, folding in occurrence metadata.

    SIGNAL-METHOD §1.3: the access question is per *URL*, not per link
    occurrence. The same document is linked from many activities; crawl it
    once. Occurrence count and the observed category/format distributions are
    retained as useful context.

    Input is assumed to be one country's frame (occurrences already filtered
    to a single recipient country); the result is that country's distinct-URL
    frame. Returned in deterministic URL order.
    """
    cat_counts: dict[str, Counter[str]] = {}
    fmt_counts: dict[str, Counter[str]] = {}
    idents: dict[str, set[str]] = {}
    total: Counter[str] = Counter()

    for occ in occurrences:
        u = occ.url
        if u not in cat_counts:
            cat_counts[u] = Counter()
            fmt_counts[u] = Counter()
            idents[u] = set()
        cat_counts[u][occ.category] += 1
        fmt_counts[u][occ.declared_format] += 1
        idents[u].add(occ.iati_identifier)
        total[u] += 1

    distinct: list[DistinctDocumentURL] = []
    for u in sorted(cat_counts):
        distinct.append(
            DistinctDocumentURL(
                url=u,
                primary_category=_modal(dict(cat_counts[u])),
                primary_format=_modal(dict(fmt_counts[u])),
                occurrence_count=total[u],
                category_counts=dict(sorted(cat_counts[u].items())),
                format_counts=dict(sorted(fmt_counts[u].items())),
                iati_identifiers=tuple(sorted(idents[u])),
            )
        )
    return distinct


def _allocate(stratum_sizes: dict[str, int], n: int) -> dict[str, int]:
    """Largest-remainder (Hamilton) allocation of `n` across strata,
    proportional to stratum size, with iterative capping so no stratum is
    allocated more URLs than it has. Deterministic tie-breaks.
    """
    remaining = dict(stratum_sizes)
    alloc: dict[str, int] = {c: 0 for c in stratum_sizes}
    quota = n

    # Iterate: allocate proportionally over not-yet-capped strata; any stratum
    # whose proportional share exceeds its size is pinned to its size and the
    # freed quota is redistributed over the rest. Stable in <= len(strata)
    # passes because each pass caps at least one stratum or terminates.
    while quota > 0 and remaining:
        total = sum(remaining.values())
        if quota >= total:  # everything left is a census of these strata
            for c, size in remaining.items():
                alloc[c] += size
            break

        raw = {c: quota * size / total for c, size in remaining.items()}
        floors = {c: int(v) for c, v in raw.items()}
        leftover = quota - sum(floors.values())
        # Distribute the leftover by largest fractional remainder; ties:
        # larger stratum first, then category code ascending.
        order = sorted(
            remaining,
            key=lambda c: (-(raw[c] - floors[c]), -remaining[c], c),
        )
        for c in order[:leftover]:
            floors[c] += 1

        capped = {c for c in remaining if floors[c] >= remaining[c]}
        if not capped:
            for c, v in floors.items():
                alloc[c] += v
            break
        for c in capped:
            alloc[c] += remaining[c]
            quota -= remaining[c]
            del remaining[c]

    return alloc


def draw_country_sample(
    country: str,
    occurrences: Iterable[DocumentLinkOccurrence],
    *,
    n: int,
    seed: str,
) -> CountrySample:
    """Draw the stratified, seeded per-country sample.

    SIGNAL-METHOD §1.4:
      - dedupe on URL first;
      - stratify by document category so the sample reflects the country's
        category mix (no category dominates by accident);
      - if the country has fewer distinct URLs than `n`, it is a census;
      - the draw is reproducible from `seed`.

    `n` is a parameter, never hardcoded — the final per-country size is
    Decisions Log Q2 (confirmed with Jaimie before the crawl).
    """
    if n <= 0:
        raise ValueError(f"sample size n must be positive, got {n!r}")

    distinct = dedupe_on_url(occurrences)
    frame_size = len(distinct)

    if frame_size <= n:  # census: take the whole frame
        breakdown = {
            cat: (cnt, cnt)
            for cat, cnt in sorted(
                Counter(d.primary_category for d in distinct).items()
            )
        }
        return CountrySample(
            country=country,
            seed=seed,
            requested_n=n,
            frame_size=frame_size,
            is_census=True,
            sampled=tuple(distinct),
            stratum_breakdown=breakdown,
        )

    strata: dict[str, list[DistinctDocumentURL]] = {}
    for d in distinct:
        strata.setdefault(d.primary_category, []).append(d)

    sizes = {c: len(v) for c, v in strata.items()}
    alloc = _allocate(sizes, n)

    drawn: list[DistinctDocumentURL] = []
    breakdown: dict[str, tuple[int, int]] = {}
    for cat in sorted(strata):
        members = sorted(strata[cat], key=lambda d: d.url)
        k = alloc[cat]
        rng = random.Random(f"{seed}|{country}|{cat}")
        picked = members if k >= len(members) else rng.sample(members, k)
        drawn.extend(picked)
        breakdown[cat] = (len(members), len(picked))

    drawn.sort(key=lambda d: d.url)
    return CountrySample(
        country=country,
        seed=seed,
        requested_n=n,
        frame_size=frame_size,
        is_census=False,
        sampled=tuple(drawn),
        stratum_breakdown=breakdown,
    )


# --- Sample cache I/O ---------------------------------------------------------
# The drawn sample is cached under cache/sample/ (gitignored — the retention
# boundary: the sample is re-drawable from the Datastore with the recorded
# seed, it is not a committed deliverable). JSON, one file per country.


def _distinct_to_json(d: DistinctDocumentURL) -> dict:
    return {
        "url": d.url,
        "primary_category": d.primary_category,
        "primary_format": d.primary_format,
        "occurrence_count": d.occurrence_count,
        "category_counts": d.category_counts,
        "format_counts": d.format_counts,
        "iati_identifiers": list(d.iati_identifiers),
    }


def _distinct_from_json(o: dict) -> DistinctDocumentURL:
    return DistinctDocumentURL(
        url=o["url"],
        primary_category=o["primary_category"],
        primary_format=o["primary_format"],
        occurrence_count=o["occurrence_count"],
        category_counts=dict(o["category_counts"]),
        format_counts=dict(o["format_counts"]),
        iati_identifiers=tuple(o["iati_identifiers"]),
    )


def write_country_sample(sample: CountrySample, cache_dir: Path) -> Path:
    """Write one country's sample to the gitignored sample cache."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{sample.country}.json"
    payload = {
        "country": sample.country,
        "seed": sample.seed,
        "requested_n": sample.requested_n,
        "frame_size": sample.frame_size,
        "is_census": sample.is_census,
        "drawn_n": sample.drawn_n,
        "stratum_breakdown": {
            k: list(v) for k, v in sample.stratum_breakdown.items()
        },
        "sampled": [_distinct_to_json(d) for d in sample.sampled],
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), "utf-8")
    return path


def read_country_sample(path: Path) -> CountrySample:
    """Read a cached country sample back (resumability for later stages)."""
    o = json.loads(Path(path).read_text("utf-8"))
    return CountrySample(
        country=o["country"],
        seed=o["seed"],
        requested_n=o["requested_n"],
        frame_size=o["frame_size"],
        is_census=o["is_census"],
        sampled=tuple(_distinct_from_json(d) for d in o["sampled"]),
        stratum_breakdown={
            k: tuple(v) for k, v in o["stratum_breakdown"].items()
        },
    )


def total_distinct_urls(samples: Sequence[CountrySample]) -> int:
    """Distinct URLs across all country samples (crawl-once dedup).

    A URL can sit in more than one country's frame; the crawl fetches it once
    and attributes the result to every country that sampled it. This is the
    figure the deliverable-6 cost projection turns on.
    """
    return len({d.url for s in samples for d in s.sampled})
