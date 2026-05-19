"""Cost & scale projection — deliverable 6 (SIGNAL-METHOD §5).

Pure functions, no I/O, no network — the projection *logic*, built and
tested offline. The real numbers it consumes (the distinct-URL count, the
host spread) come from the live sample draw, which needs the IATI key; this
module just turns those inputs into the projection the crawl go-ahead is
decided on.

The crawl is sequential (concurrency 1 — SIGNAL-METHOD §2 "global pace"),
so the wall-clock model is a band, not a point: a lower bound where network
time dominates and per-host pacing rarely bites, and an upper bound where
the sample is host-clustered (the donor-skew makes this realistic — most
URLs sit on a few large donor hosts) so pacing is paid on nearly every
same-host repeat. Every assumption is explicit and carried into the report
so the verdict can state it.

OCR (Decisions Log Q8 = option (b)): a seeded, recorded sub-sample of the
`ocr_needed` set is OCR'd to estimate yield. The scanned set's size is only
known after the crawl, so the OCR cost here is a conditional band over a
stated scanned-share assumption — never an instruction to OCR the whole set
(that is (c), out of scope).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlsplit

from .models import CountrySample, CrawlPolicy


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


@dataclass(frozen=True, slots=True)
class CorpusScale:
    """The shape of the draw — what the wall-clock and OCR lines build on."""

    per_country_distinct: dict[str, int]
    union_distinct: int  # distinct across all countries (URLs recur cross-country)
    distinct_hosts: int
    census_countries: tuple[str, ...]  # frame smaller than the target


def corpus_scale(samples: list[CountrySample]) -> CorpusScale:
    """Distinct-URL counts and host spread from the drawn samples.

    Per-country counts sum the per-country draws; `union_distinct` dedupes
    a URL that was sampled for more than one country (it is crawled once).
    """
    per_country: dict[str, int] = {}
    seen: set[str] = set()
    hosts: set[str] = set()
    census: list[str] = []
    for s in samples:
        urls = [d.url for d in s.sampled]
        per_country[s.country] = len(urls)
        seen.update(urls)
        hosts.update(_host(u) for u in urls if u)
        if s.is_census:
            census.append(s.country)
    return CorpusScale(
        per_country_distinct=per_country,
        union_distinct=len(seen),
        distinct_hosts=len(hosts),
        census_countries=tuple(sorted(census)),
    )


@dataclass(frozen=True, slots=True)
class WallClock:
    lower_s: float
    upper_s: float
    assumptions: dict[str, float]

    @staticmethod
    def _human(seconds: float) -> str:
        h, rem = divmod(int(seconds), 3600)
        m, s = divmod(rem, 60)
        if h:
            return f"{h}h {m}m"
        if m:
            return f"{m}m {s}s"
        return f"{s}s"

    @property
    def lower_human(self) -> str:
        return self._human(self.lower_s)

    @property
    def upper_human(self) -> str:
        return self._human(self.upper_s)


def estimate_wallclock(
    scale: CorpusScale,
    policy: CrawlPolicy,
    *,
    mean_request_s_low: float = 0.8,
    mean_request_s_high: float = 4.0,
    robots_request_s: float = 2.0,
    retry_fraction: float = 0.15,
) -> WallClock:
    """Sequential-crawl wall-clock band.

    lower  = N * fast-request                       (pacing rarely bites)
    upper  = N * slow-request
             + (N - H) * per_host_interval          (host-clustered worst case)
             + H * one robots fetch per host
             + retry_fraction * N * slow-request    (the single polite retry)

    N = union distinct URLs, H = distinct hosts. The upper term `(N - H)`
    is the donor-skew-realistic case where most URLs repeat on a few hosts
    so the per-host delay is paid on nearly every one.
    """
    n = scale.union_distinct
    h = scale.distinct_hosts
    lower = n * mean_request_s_low
    upper = (
        n * mean_request_s_high
        + max(0, n - h) * policy.per_host_interval_s
        + h * robots_request_s
        + retry_fraction * n * mean_request_s_high
    )
    return WallClock(
        lower_s=lower,
        upper_s=upper,
        assumptions={
            "mean_request_s_low": mean_request_s_low,
            "mean_request_s_high": mean_request_s_high,
            "robots_request_s": robots_request_s,
            "retry_fraction": retry_fraction,
            "per_host_interval_s": policy.per_host_interval_s,
        },
    )


@dataclass(frozen=True, slots=True)
class OcrCostLine:
    engine: str  # "local_tesseract" | "ocr_api"
    subsample_target: int
    selection: str
    per_page_usd: float  # 0.0 for local
    mean_pages_assumed: float
    # Conditional band: subsample is min(target, |ocr_needed|); |ocr_needed|
    # is unknown pre-crawl, so cost is projected over a scanned-share band.
    scanned_share_band: tuple[float, ...]
    projected_subsample_by_share: dict[float, int]
    projected_cost_usd_by_share: dict[float, float]


def ocr_cost_line(
    scale: CorpusScale,
    *,
    engine: str,
    subsample_target: int,
    seed: str,
    per_page_usd: float,
    mean_pages_assumed: float,
    scanned_share_band: tuple[float, ...] = (0.10, 0.30, 0.60),
) -> OcrCostLine:
    """Projected OCR cost for Q8 option (b).

    The sub-sample is `min(subsample_target, |ocr_needed|)` — capped, never
    the whole set. `|ocr_needed|` is unknown until the crawl, so cost is a
    band over assumed scanned-shares of the resolved-readable set. Local
    Tesseract = nil per-page cost; an API = per_page_usd × mean_pages × n.
    """
    n = scale.union_distinct
    by_share_n: dict[float, int] = {}
    by_share_cost: dict[float, float] = {}
    for share in scanned_share_band:
        scanned_est = int(round(n * share))
        sub = min(subsample_target, scanned_est)
        by_share_n[share] = sub
        by_share_cost[share] = round(sub * mean_pages_assumed * per_page_usd, 2)
    return OcrCostLine(
        engine=engine,
        subsample_target=subsample_target,
        selection=(
            f"seeded (seed={seed!r}), recorded, reproducible: a random draw "
            f"of min({subsample_target}, |ocr_needed|) URLs from the "
            f"ocr_needed set, the drawn ids written to the metric cache"
        ),
        per_page_usd=per_page_usd,
        mean_pages_assumed=mean_pages_assumed,
        scanned_share_band=scanned_share_band,
        projected_subsample_by_share=by_share_n,
        projected_cost_usd_by_share=by_share_cost,
    )


@dataclass(frozen=True, slots=True)
class Projection:
    scale: CorpusScale
    wallclock: WallClock
    ocr: OcrCostLine
    policy: CrawlPolicy
    notes: list[str] = field(default_factory=list)


def build_projection(
    samples: list[CountrySample],
    policy: CrawlPolicy,
    *,
    ocr_engine: str,
    ocr_subsample_target: int,
    ocr_seed: str,
    ocr_per_page_usd: float,
    ocr_mean_pages_assumed: float,
) -> Projection:
    """Assemble the full D6 projection from a drawn sample. Offline; the
    sample itself is the only thing that needed the live key."""
    scale = corpus_scale(samples)
    wall = estimate_wallclock(scale, policy)
    ocr = ocr_cost_line(
        scale,
        engine=ocr_engine,
        subsample_target=ocr_subsample_target,
        seed=ocr_seed,
        per_page_usd=ocr_per_page_usd,
        mean_pages_assumed=ocr_mean_pages_assumed,
    )
    notes = [
        "Wall-clock is a band: sequential crawl, concurrency 1. Upper bound "
        "assumes donor-skew host-clustering so per-host pacing is paid on "
        "nearly every same-host repeat.",
        "OCR cost is conditional on |ocr_needed|, unknown until the crawl; "
        "shown as a band over assumed scanned-shares. Sub-sample is capped "
        "at the target — never the full scanned set (Q8 = (b), not (c)).",
        "Hard ceiling check: if the realised distinct-URL count or the "
        "projected wall-clock/cost exceeds the agreed bound, stop and "
        "re-scope rather than proceed (SIGNAL-METHOD §5).",
    ]
    if scale.census_countries:
        notes.append(
            "Census countries (frame smaller than the target, recorded as "
            f"such): {', '.join(scale.census_countries)}."
        )
    return Projection(
        scale=scale, wallclock=wall, ocr=ocr, policy=policy, notes=notes
    )
