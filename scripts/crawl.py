"""D7 — the polite, resumable publisher crawl (live).

Wires every offline-tested piece into a single live run:

  CrawlPolicy (Q10)        binding crawl-safety values, not loosened
  requests_fetcher          + robots_fetch_via with (connect, robots) timeouts
  HostRateLimiter           SHARED across countries — per-host pacing is
                            global, donor hosts repeated across countries
                            still get one 5 s gap apiece
  RobotsCache(rate_limiter) SHARED — robots.txt fetched once per host, paced
  readability_sink (Q9=250) the D4 -> D5 contract: per-url buffer assessed
                            in-process and released; the row carries metrics
                            only, no bytes/text
  mark_no_body              finalises rows the sink never reached (barrier
                            / error / redirect dead-end) so
                            reachable_and_readable is set everywhere

Resumability: each url's result row is appended to
cache/metrics/{CC}.jsonl on completion; a re-run with the same arguments
skips urls already in the file. The crawl is structured so a country is
the coherent chunk: per-country progress is written to
output/crawl_progress.jsonl and committed+pushed on the country boundary,
making the resumption point explicit on the public remote.

Real-time safety-rule surfacing (printed to the run log AND captured in
the per-country progress record so the verdict can cite them):

  * non_public_host — ANY occurrence is flagged (an IATI document link
    pointing at a private/loopback/link-local address is a small but real
    data-quality finding the SSRF check makes loud).
  * robots_disallowed — a single host accumulating >= 3 disallow rows is
    flagged (concentrated disallow is a publisher posture, not noise).

Counts only on committed output (location-safety / retention boundary).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from iati_access_probe.countries import COUNTRIES  # noqa: E402
from iati_access_probe.crawler import (  # noqa: E402
    append_result,
    crawl_url,
    load_done_urls,
)
from iati_access_probe.models import CrawlPolicy  # noqa: E402
from iati_access_probe.readability import (  # noqa: E402
    DEFAULT_USABLE_TEXT_THRESHOLD,
    mark_no_body,
    readability_sink,
)
from iati_access_probe.safety import (  # noqa: E402
    HostRateLimiter,
    RobotsCache,
    system_resolver,
)
from iati_access_probe.sampler import read_country_sample  # noqa: E402
from iati_access_probe.transport import (  # noqa: E402
    requests_fetcher,
    robots_fetch_via,
)

PROGRESS_PATH = ROOT / "output" / "crawl_progress.jsonl"
ROBOTS_CLUSTER_THRESHOLD = 3


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _metrics_path(cache_dir: Path, country: str) -> Path:
    d = cache_dir / "metrics"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{country}.jsonl"


def _git(args: list[str]) -> tuple[int, str]:
    r = subprocess.run(
        ["git", *args], cwd=str(ROOT), capture_output=True, text=True
    )
    return r.returncode, (r.stderr or r.stdout).strip()


def _commit_and_push_progress(country: str, drawn_n: int) -> None:
    """Country-boundary commit+push. Push failures are non-fatal — the
    crawl proceeds; the next boundary will push the accumulated commits."""
    code, _ = _git(["add", str(PROGRESS_PATH.relative_to(ROOT))])
    if code != 0:
        print(f"  git add failed (non-fatal); continuing.")
        return
    code, _ = _git([
        "commit", "-m",
        f"sprint 1 — D7 crawl progress: {country} complete (n={drawn_n})",
        "-m",
        "Counts only; URL-level rows live in the gitignored metric cache.\n\n"
        "Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>",
    ])
    if code != 0:
        print(f"  git commit no-op or failed (non-fatal).")
        return
    code, out = _git(["push", "origin", "master"])
    if code != 0:
        print(f"  git push failed (non-fatal): {out[:200]}")


def crawl_one_country(
    country: str,
    *,
    policy: CrawlPolicy,
    fetcher,
    resolver,
    robots: RobotsCache,
    rate_limiter: HostRateLimiter,
    sink,
    cache_dir: Path,
) -> dict:
    """Crawl one country's sample as a resumable, coherent chunk. Returns
    the progress record (counts only) that's appended to crawl_progress."""
    sample = read_country_sample(cache_dir / "sample" / f"{country}.json")
    path = _metrics_path(cache_dir, country)
    done = load_done_urls(path)
    drawn_n = len(sample.sampled)
    skipped = len(done)
    started = _now()

    barriers = Counter()
    errors = Counter()
    outcomes = Counter()
    resolved_n = 0
    reachable_n = 0
    declared_pdf_actually_html_n = 0
    offdomain_n = 0
    robots_disallow_by_host = Counter()
    robots_alerted: set[str] = set()

    print(f"\n=== {country}: starting (n={drawn_n}, already done={skipped}) ===")
    for d in sample.sampled:
        if d.url in done:
            continue
        row = crawl_url(
            d.url,
            policy=policy, fetcher=fetcher, resolver=resolver,
            robots=robots, rate_limiter=rate_limiter,
            declared_format=d.primary_format, on_content=sink,
        )
        if row.readability_pending:
            mark_no_body(row)
        append_result(path, row)

        # tally
        if row.resolved:
            resolved_n += 1
        if row.reachable_and_readable:
            reachable_n += 1
        if row.declared_pdf_actually_html:
            declared_pdf_actually_html_n += 1
        if row.redirect_offdomain:
            offdomain_n += 1
        barriers[row.access_barrier] += 1
        if row.error_category:
            errors[row.error_category] += 1
        if row.extraction_outcome:
            outcomes[row.extraction_outcome] += 1

        # real-time safety-rule surfacing
        if row.access_barrier == "non_public_host":
            print(f"  ALERT {country}: non_public_host on {row.url}")
        if row.access_barrier == "robots_disallowed":
            host = (row.final_url or row.url).split("/", 3)[2] if "//" in (row.final_url or row.url) else "?"
            robots_disallow_by_host[host] += 1
            if (
                robots_disallow_by_host[host] >= ROBOTS_CLUSTER_THRESHOLD
                and host not in robots_alerted
            ):
                print(f"  ALERT {country}: robots_disallowed cluster on "
                      f"{host} ({robots_disallow_by_host[host]} rows)")
                robots_alerted.add(host)

    finished = _now()
    rec = {
        "country": country,
        "started_iso": started,
        "finished_iso": finished,
        "drawn_n": drawn_n,
        "previously_done_skipped": skipped,
        "resolved_n": resolved_n,
        "reachable_and_readable_n": reachable_n,
        "offdomain_redirect_n": offdomain_n,
        "declared_pdf_actually_html_n": declared_pdf_actually_html_n,
        "access_barriers": dict(barriers),
        "error_categories": dict(errors),
        "extraction_outcomes": dict(outcomes),
        "robots_disallow_concentrated_hosts": [
            {"host": h, "count": c}
            for h, c in robots_disallow_by_host.items()
            if c >= ROBOTS_CLUSTER_THRESHOLD
        ],
    }
    print(
        f"=== {country} done: resolved={resolved_n}/{drawn_n} "
        f"reachable_and_readable={reachable_n} "
        f"barriers={dict(barriers)} errors={dict(errors)} "
        f"outcomes={dict(outcomes)} ==="
    )
    return rec


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="D7 publisher crawl.")
    p.add_argument(
        "--countries", default=",".join(COUNTRIES),
        help="comma-separated ISO codes; default = all 18 in order",
    )
    p.add_argument("--cache-dir", type=Path, default=ROOT / "cache")
    p.add_argument(
        "--usable-text-threshold", type=int,
        default=DEFAULT_USABLE_TEXT_THRESHOLD,
    )
    p.add_argument(
        "--no-commit", action="store_true",
        help="skip per-country git commit+push (for local dry runs)",
    )
    args = p.parse_args(argv)

    countries = tuple(c.strip() for c in args.countries.split(",") if c.strip())

    # Shared, paced infrastructure — one set of objects across the whole run.
    policy = CrawlPolicy()  # Q10 confirmed defaults
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
    sink = readability_sink(usable_text_threshold=args.usable_text_threshold)

    PROGRESS_PATH.parent.mkdir(parents=True, exist_ok=True)
    run_started = _now()
    print(f"D7 crawl started {run_started}; countries: {','.join(countries)}")

    for cc in countries:
        rec = crawl_one_country(
            cc,
            policy=policy, fetcher=fetcher, resolver=system_resolver,
            robots=robots, rate_limiter=rate_limiter, sink=sink,
            cache_dir=args.cache_dir,
        )
        with PROGRESS_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, sort_keys=True) + "\n")
        if not args.no_commit:
            _commit_and_push_progress(cc, rec["drawn_n"])

    print(f"\nD7 crawl finished {_now()} (started {run_started}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
