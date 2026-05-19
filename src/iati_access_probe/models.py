"""Data models for the document-link sample.

Three records, in pipeline order:

  DocumentLinkOccurrence  one document-link as it appears on one activity
                          (the raw unit the Datastore yields; an activity may
                          carry several, and the same URL recurs across many
                          activities — Phase 0.5 established this)
        |  dedupe on URL within a country frame
        v
  DistinctDocumentURL     one URL, with the occurrence metadata folded in
                          (how many link occurrences, which categories/formats
                          were declared for it, which activities)
        |  stratified seeded draw
        v
  CountrySample           the drawn sample for one country, plus the
                          reproducibility metadata (seed, sizes, census flag)

NOTE (location-safety / retention boundary): every field here is access
metadata only — URL, declared MIME type, IATI category/identifier, counts.
No document content is modelled, ever.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

# Sentinel category for occurrences whose document-link category code is
# missing/empty. Such occurrences are NOT dropped (that would silently bias
# the frame); they stratify into their own bucket and the verdict can report
# the uncategorised share honestly.
UNCATEGORISED = "__uncategorised__"


@dataclass(frozen=True, slots=True)
class DocumentLinkOccurrence:
    """One document-link as attached to one activity. The raw sampling input."""

    iati_identifier: str
    recipient_country: str  # ISO 3166-1 alpha-2, from the country frame
    url: str
    declared_format: str  # the IATI document-link `format` (a MIME type)
    category: str  # IATI document category code, or UNCATEGORISED


@dataclass(frozen=True, slots=True)
class DistinctDocumentURL:
    """One distinct URL after dedupe, with occurrence metadata folded in.

    `primary_category` / `primary_format` are the modal value across this
    URL's occurrences, with a deterministic lexicographic tie-break so the
    stratification is reproducible (see sampler.py). The full observed
    distributions are kept for honest reporting.
    """

    url: str
    primary_category: str
    primary_format: str
    occurrence_count: int
    category_counts: dict[str, int]
    format_counts: dict[str, int]
    iati_identifiers: tuple[str, ...]

    @property
    def is_multi_category(self) -> bool:
        return len(self.category_counts) > 1


@dataclass(frozen=True, slots=True)
class CountrySample:
    """The drawn sample for one country plus its reproducibility metadata."""

    country: str
    seed: str
    requested_n: int
    frame_size: int  # distinct URLs available in this country's frame
    is_census: bool  # True when frame_size <= requested_n (took all)
    sampled: tuple[DistinctDocumentURL, ...]
    # Per-category: (frame count, allocated/drawn count). Lets the verdict
    # show the draw reflects the country's category mix.
    stratum_breakdown: dict[str, tuple[int, int]] = field(default_factory=dict)

    @property
    def drawn_n(self) -> int:
        return len(self.sampled)


# --- Crawl policy & result --------------------------------------------------
# The crawl-safety parameters (SIGNAL-METHOD §2). The VALUES below are
# conservative defaults PROPOSED for confirmation with Jaimie before the live
# crawl (CLAUDE.md process rules) — they are not tuned for speed and are not
# loosened autonomously. The crawler reads policy from here; the live run
# uses the confirmed values.


@dataclass(frozen=True, slots=True)
class CrawlPolicy:
    # Honest, declared User-Agent identifying IATI research tooling, with a
    # contact. No browser-agent spoofing (SIGNAL-METHOD §2).
    user_agent: str = (
        "iati-corpus-access-probe/0.1 (IATI linked-document access & "
        "readability research; contact: jaimiegrant@gmail.com)"
    )
    connect_timeout_s: float = 10.0
    read_timeout_s: float = 30.0
    max_bytes: int = 50 * 1024 * 1024  # hard file-size cap (50 MiB)
    per_host_interval_s: float = 5.0  # polite delay between same-host hits
    max_redirects: int = 5
    robots_timeout_s: float = 15.0


# Closed vocabularies (SIGNAL-METHOD §3) — keep these exact; the analysis
# step counts on them.
ACCESS_BARRIERS = (
    "none",
    "auth_required",
    "robots_disallowed",
    "oversize",
    # `paywall_suspected` is NOT set by the crawler (deliverable 4): it is
    # inferred from response/content patterns by the readability assessment
    # (deliverable 5, SIGNAL-METHOD §3) and is best-effort (§6). It lives in
    # the vocabulary now so the result-row schema is stable across D4/D5.
    "paywall_suspected",
    "non_public_host",
)
# Crawl-time error taxonomy. Every value here has an assignment site in
# crawler.py — an unused category in a probe whose entire output is a
# result-row taxonomy is a correctness smell, so the set is kept tight.
# (`malformed_response` was removed: a torn/garbled body surfaces as
# `read_error` and an unparseable response as `connection_error`; there was
# no distinct site for it. Readability/format defects are D5's
# `extraction_outcome`, not a crawl error_category.)
#
# `unexpected_error` is its own category, NOT folded into
# `connection_error`: the verdict reports resolution rates, so a crawler
# code defect that throws on some fraction of URLs must read as a code
# defect, not as indistinguishable network failure. The exception class
# name is kept on `unexpected_error_type` for diagnosis.
ERROR_CATEGORIES = (
    "dns_failure",
    "timeout",
    "tls_error",
    "connection_error",
    "read_error",
    "too_many_redirects",
    "unexpected_error",
)


@dataclass
class CrawlResult:
    """One result row per sampled URL. Resolution/access fields are populated
    by the crawler (deliverable 4); readability fields are filled by the
    assessment (deliverable 5) and stay None until then.

    Retention/location-safety: this row carries counts, statuses, URLs and
    identifiers ONLY — never document content, never place names.
    """

    url: str
    crawl_ts: str  # ISO-8601 UTC, the crawl date this figure is dated to

    # Resolution / access (deliverable 4)
    http_status: int | None = None
    error_category: str | None = None  # one of ERROR_CATEGORIES, or None
    # Set only when error_category == "unexpected_error": the exception class
    # name, so a crawler defect is diagnosable without conflating it with a
    # network failure. None on every other path.
    unexpected_error_type: str | None = None
    resolved: bool = False
    final_url: str | None = None
    # Redirect hops ONLY — {from, status, location, offdomain} per hop.
    # Nothing else is ever appended here (was previously also carrying the
    # unexpected-error diagnostic; that now has its own field above).
    redirect_chain: list[dict] = field(default_factory=list)
    redirect_offdomain: bool = False
    access_barrier: str = "none"
    content_type: str | None = None  # server-declared header (not trusted alone)
    content_length: int | None = None  # declared header, if any
    bytes_fetched: int = 0
    elapsed_s: float = 0.0

    # Readability (deliverable 5 fills these)
    readability_pending: bool = True
    declared_format: str | None = None  # IATI document-link format (from sample)
    detected_format: str | None = None
    format_match: bool | None = None
    declared_pdf_actually_html: bool | None = None
    extraction_outcome: str | None = None
    extracted_char_count: int | None = None
    usable_text: bool | None = None
    reachable_and_readable: bool | None = None

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, o: dict) -> "CrawlResult":
        return cls(**o)
