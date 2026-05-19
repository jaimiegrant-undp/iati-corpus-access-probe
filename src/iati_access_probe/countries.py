"""The fixed 18-country set for the probe.

Decisions Log Q1: the same 18 countries as the Phase 0.5/0.6 baselines, for
consistency and comparability (including the Pacific SIDS equity cut). The
sampler iterates exactly this set; the verdict cross-references the earlier
baselines by the same codes.

ISO 3166-1 alpha-2 recipient-country codes.
"""

from __future__ import annotations

COUNTRIES: tuple[str, ...] = (
    "BD",  # Bangladesh
    "BR",  # Brazil
    "CO",  # Colombia
    "FJ",  # Fiji            (Pacific SIDS)
    "IN",  # India
    "KE",  # Kenya
    "LR",  # Liberia
    "LS",  # Lesotho
    "MD",  # Moldova
    "ML",  # Mali
    "NG",  # Nigeria
    "NP",  # Nepal
    "RW",  # Rwanda
    "SB",  # Solomon Islands  (Pacific SIDS)
    "UG",  # Uganda
    "VN",  # Viet Nam
    "VU",  # Vanuatu          (Pacific SIDS)
    "WS",  # Samoa            (Pacific SIDS)
)

# Subset flagged for the equity cut in the verdict (SIGNAL.md core question 6).
PACIFIC_SIDS: frozenset[str] = frozenset({"FJ", "SB", "VU", "WS"})

assert len(COUNTRIES) == 18, "Q1 fixes the set at 18 countries"
assert PACIFIC_SIDS.issubset(set(COUNTRIES))
