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

from dataclasses import dataclass, field

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
