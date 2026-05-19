"""Live document-link sample draw — deliverable 2 (live half) entrypoint.

This is the FIRST step that needs the live IATI Datastore key. Everything
it calls (the Datastore wrapper, the sampler) was built and tested offline;
this script only wires them and runs the seeded draw.

Key handling — the single binding point for the variable name:

  * The Datastore connector takes `api_key` as a parameter and reads NO
    environment variable itself. The env var name therefore lives HERE and
    nowhere else: it is exactly `IATI_API_KEY` (the constant `ENV_KEY`
    below), matching `.env.example`. A stale/renamed variable is a
    silent-zero hazard, so a missing or empty key fails LOUDLY before any
    request — never a silent empty draw. `DatastoreClient` also re-guards
    an empty key, so the loud failure is doubled.

  * The key is read from the process environment first, then from
    `.env.local` (gitignored, never committed). It is never logged, never
    echoed, never written anywhere.

Order of operations (matches the agreed gate):
  1. `--verify-only`: a single live `verify_fields` call — the smallest
     possible live request — to confirm every Solr field name resolves
     before any bulk paging (the Phase 0.5 silent-zero lesson).
  2. full run: verify_fields, then per-country iter_docs -> occurrences ->
     seeded stratified draw -> write the per-country sample to the
     gitignored cache. Counts only are printed; no document content.

The recorded seed is `DRAW_SEED`; it is written into every CountrySample
and must be copied into Decisions Log Q7 when the real draw is run.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from iati_access_probe.countries import COUNTRIES  # noqa: E402
from iati_access_probe.datastore import (  # noqa: E402
    DOCLINK_FIELDS,
    DatastoreClient,
    activity_docs_to_occurrences,
)
from iati_access_probe.sampler import (  # noqa: E402
    draw_country_sample,
    write_country_sample,
)

# The ONLY place the env var name is defined. Must equal .env.example.
ENV_KEY = "IATI_API_KEY"

# Q7: ~300–400 distinct URLs/country, ~7,000 ceiling. Parameter, not magic.
DEFAULT_N = 400
# Recorded, reproducible (Q7). Copy into Decisions Log Q7 on the real draw.
DRAW_SEED = "iati-access-probe-2026-05-19"

# Frame per country (SIGNAL-METHOD §1.3): activities recipient-tagged to the
# country that actually carry a document link. The valid/current scope
# refinement is a FLAGGED query-design point — see the session note; kept
# explicit and simple here rather than silently guessed.
COUNTRY_QUERY = "recipient_country_code:{cc} AND document_link_url:[* TO *]"


def _parse_env_local(path: Path) -> dict[str, str]:
    """Minimal KEY=VALUE reader (no python-dotenv dependency — that would be
    a package beyond the SIGNAL.md stack / a stop-and-ask). Ignores blank
    lines and `#` comments; strips surrounding quotes."""
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for raw in path.read_text("utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def get_api_key(env_local: Path) -> str:
    """Resolve `IATI_API_KEY` (process env first, then .env.local). Loud
    failure if absent/empty — never returns "" to a silent draw."""
    key = os.environ.get(ENV_KEY) or _parse_env_local(env_local).get(ENV_KEY, "")
    key = key.strip()
    if not key:
        raise SystemExit(
            f"{ENV_KEY} is not set. Put `{ENV_KEY}=<your key>` in "
            f"{env_local} (gitignored) or export it. Refusing to draw with "
            f"no key (a silent empty draw would corrupt every figure)."
        )
    return key


def run_draw(
    client: DatastoreClient,
    *,
    countries: tuple[str, ...],
    n: int,
    seed: str,
    cache_dir: Path,
    verify_only: bool,
) -> dict[str, int]:
    """Verify fields (loud), then draw + cache each country. Returns the
    per-country drawn count (counts only — no content)."""
    client.verify_fields()  # loud on any unrecognised Solr field name
    if verify_only:
        print("verify_fields OK — all Solr field names resolve.")
        return {}

    drawn: dict[str, int] = {}
    for cc in countries:
        docs = list(
            client.iter_docs(COUNTRY_QUERY.format(cc=cc), DOCLINK_FIELDS)
        )
        occ, _anomalies = activity_docs_to_occurrences(docs, cc)
        sample = draw_country_sample(cc, occ, n=n, seed=seed)
        write_country_sample(sample, cache_dir)
        drawn[cc] = sample.drawn_n
        flag = " (census)" if sample.is_census else ""
        print(f"  {cc}: frame={sample.frame_size} drawn={sample.drawn_n}{flag}")
    print(f"Total drawn (pre cross-country dedup): {sum(drawn.values())}")
    return drawn


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Live document-link sample draw.")
    p.add_argument("--verify-only", action="store_true",
                   help="single live verify_fields call, no draw")
    p.add_argument("--n", type=int, default=DEFAULT_N)
    p.add_argument("--seed", default=DRAW_SEED)
    p.add_argument("--cache-dir", type=Path,
                   default=Path(__file__).resolve().parents[1] / "cache" / "sample")
    p.add_argument("--env-local", type=Path,
                   default=Path(__file__).resolve().parents[1] / ".env.local")
    args = p.parse_args(argv)

    key = get_api_key(args.env_local)  # loud-fails here if missing
    client = DatastoreClient(api_key=key)
    run_draw(
        client,
        countries=COUNTRIES,
        n=args.n,
        seed=args.seed,
        cache_dir=args.cache_dir,
        verify_only=args.verify_only,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
