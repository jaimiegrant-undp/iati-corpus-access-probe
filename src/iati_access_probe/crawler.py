"""The safe, resumable crawler (SIGNAL-METHOD §2).

Every binding rule is enforced here and the whole fetch-and-record is
fault-isolated: any failure — DNS, TLS, timeout, reset, redirect loop,
non-public host, oversize, robots disallow, or an unexpected exception — is
caught and written as a result row. The run never dies on a bad URL and is
resumable from the JSONL metric cache (one file per country, append-on-
complete).

The crawler does NOT parse document content (that is deliverable 5). It
fetches, applies the safety rules, records the resolution/access row, and
hands the bytes to an optional in-process sink (deliverable 5's assessment).

Retention boundary (Decisions Log Q4), the strongest reading: the body of
ONE url is buffered in memory, hard-bounded by `policy.max_bytes`, passed to
the sink for that url, and then released — the local buffer goes out of
scope before the next url is fetched. Bytes are never accumulated across
urls, never written to disk, and never placed on the `CrawlResult` row (the
committed JSONL stays counts/statuses/identifiers only). With no sink
(deliverable 4 standalone) the body is counted for size and discarded chunk
by chunk — D5 is not built yet, so the default path retains nothing at all.

Network is injected (`fetcher`, `resolver`) so the whole pipeline, including
every fault path, is tested offline with no live key and no live fetch.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol
from urllib.parse import urljoin, urlsplit

from .models import CrawlPolicy, CrawlResult, CountrySample
from .safety import (
    DNSFailure,
    HostRateLimiter,
    RobotsCache,
    host_is_public,
    same_registered_domain,
)


# --- transport contract (injected; offline-stubbable) -----------------------
class FetchResponse(Protocol):
    status_code: int
    headers: dict[str, str]

    def iter_bytes(self, chunk_size: int) -> Iterator[bytes]: ...
    def close(self) -> None: ...


# fetch(url, headers, timeout) -> FetchResponse. ONE request, no auto
# redirects (the crawler follows them manually so every hop is re-checked
# and recorded). No credentials are ever attached.
Fetcher = Callable[[str, dict[str, str], tuple[float, float]], FetchResponse]

# on_content(result, body) -> None. The in-process hand-off to deliverable
# 5. Called at most once per url, only when a terminal (non-redirect) body
# was read whole within the size cap; `body` is the full response bytes for
# THAT url and is released immediately after the call returns (see module
# docstring, retention boundary). None = deliverable-4-standalone: bytes are
# counted for size and discarded, nothing retained.
ContentSink = Callable[[CrawlResult, bytes], None]


class CrawlTimeout(Exception):
    """Connect or read timeout."""


class CrawlTLSError(Exception):
    """TLS/SSL handshake or certificate failure."""


class CrawlConnectionError(Exception):
    """Connection refused/reset or other transport failure."""


class CrawlReadError(Exception):
    """Failure while streaming the response body."""


_CHUNK = 64 * 1024


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _header(headers: dict[str, str], name: str) -> str | None:
    low = name.lower()
    for k, v in headers.items():
        if k.lower() == low:
            return v
    return None


def crawl_url(
    url: str,
    *,
    policy: CrawlPolicy,
    fetcher: Fetcher,
    resolver,
    robots: RobotsCache,
    rate_limiter: HostRateLimiter,
    declared_format: str | None = None,
    on_content: ContentSink | None = None,
    now: Callable[[], str] = _now_iso,
    monotonic: Callable[[], float] = time.monotonic,
) -> CrawlResult:
    """Fetch one URL under every binding rule; always return a result row."""
    result = CrawlResult(url=url, crawl_ts=now(), declared_format=declared_format)
    started = monotonic()
    try:
        _run(url, result, policy, fetcher, resolver, robots, rate_limiter, on_content)
    except DNSFailure:
        result.error_category = "dns_failure"
    except CrawlTimeout:
        result.error_category = "timeout"
    except CrawlTLSError:
        result.error_category = "tls_error"
    except CrawlReadError:
        result.error_category = "read_error"
    except CrawlConnectionError:
        result.error_category = "connection_error"
    except Exception as exc:  # nothing escapes — fault isolation is absolute
        result.error_category = "connection_error"
        result.redirect_chain.append({"unexpected_error": type(exc).__name__})
    finally:
        # Wall-clock for this url, recorded on every path (success, barrier,
        # or any fault) — a hung host's timeout duration is itself a finding.
        result.elapsed_s = round(monotonic() - started, 3)
    return result


def _guard_host(target_url: str, resolver) -> str:
    """Resolve the host and enforce the non-public rule. Returns the
    hostname; raises DNSFailure (caught -> dns_failure) or signals a
    non-public host to the caller via _NonPublicHost."""
    host = urlsplit(target_url).hostname
    if not host:
        raise CrawlConnectionError(f"no host in URL: {target_url!r}")
    public, _ips = host_is_public(host, resolver)  # DNSFailure propagates
    if not public:
        raise _NonPublicHost(host)
    return host


class _NonPublicHost(Exception):
    """Internal: a resolved host fell in a non-public range."""


def _run(
    url: str,
    result: CrawlResult,
    policy: CrawlPolicy,
    fetcher: Fetcher,
    resolver,
    robots: RobotsCache,
    rate_limiter: HostRateLimiter,
    on_content: ContentSink | None,
) -> None:
    headers = {
        "User-Agent": policy.user_agent,
        "Accept": "*/*",
        # No Authorization, no Cookie — the probe never authenticates.
    }
    timeout = (policy.connect_timeout_s, policy.read_timeout_s)

    current = url
    for hop in range(policy.max_redirects + 1):
        # (1) Non-public-host check on EVERY hop, before any egress to it.
        try:
            host = _guard_host(current, resolver)
        except _NonPublicHost:
            result.access_barrier = "non_public_host"
            result.final_url = current
            return

        # (2) robots.txt honoured per host (its own fetch is safety-checked
        # because `host` was just confirmed public; same host).
        if not robots.can_fetch(current, policy.user_agent):
            result.access_barrier = "robots_disallowed"
            result.final_url = current
            return

        # (3) Polite per-host pacing.
        rate_limiter.wait(host)

        # (4) One request, no auto-redirects.
        resp = fetcher(current, headers, timeout)
        try:
            status = resp.status_code

            if status in (301, 302, 303, 307, 308):
                location = _header(resp.headers, "Location")
                if not location:
                    result.http_status = status
                    result.final_url = current
                    return
                nxt = urljoin(current, location)
                offdomain = not same_registered_domain(current, nxt)
                result.redirect_chain.append(
                    {
                        "from": current,
                        "status": status,
                        "location": nxt,
                        "offdomain": offdomain,
                    }
                )
                if offdomain:
                    # Recorded as a finding, not silently treated as success.
                    result.redirect_offdomain = True
                current = nxt
                continue

            # Terminal response.
            result.http_status = status
            result.final_url = current
            result.content_type = _header(resp.headers, "Content-Type")
            cl = _header(resp.headers, "Content-Length")
            if cl and cl.isdigit():
                result.content_length = int(cl)

            # (5) No authentication / no bypass.
            if status in (401, 403) or _header(resp.headers, "WWW-Authenticate"):
                result.access_barrier = "auth_required"
                return

            # (6) Hard size cap — skip before download if declared.
            if result.content_length and result.content_length > policy.max_bytes:
                result.access_barrier = "oversize"
                return

            # (7) Stream the body, aborting at the cap. The body for THIS
            # url is buffered in memory, hard-bounded by max_bytes, so it
            # can be handed to the deliverable-5 sink in-process. When the
            # cap is hit we record `oversize`, drop the partial buffer, and
            # do NOT hand off. With no sink the buffer stays None and bytes
            # are counted and discarded (retention boundary — see docstring).
            total = 0
            buf: bytearray | None = bytearray() if on_content is not None else None
            try:
                for chunk in resp.iter_bytes(_CHUNK):
                    total += len(chunk)
                    if total > policy.max_bytes:
                        result.access_barrier = "oversize"
                        result.bytes_fetched = total
                        return  # buf goes out of scope here — partial body dropped
                    if buf is not None:
                        buf += chunk
            except (CrawlTimeout, CrawlTLSError, CrawlConnectionError):
                raise
            except Exception as exc:
                raise CrawlReadError(str(exc)) from exc

            result.bytes_fetched = total
            result.resolved = 200 <= status < 300
            if buf is not None:
                # In-process hand-off for exactly this url, then release.
                # The bytes are NOT stored on `result` (the committed row is
                # metrics only) and `buf` is dropped before the next url.
                on_content(result, bytes(buf))  # type: ignore[misc]
                buf = None
            return
        finally:
            resp.close()

    result.error_category = "too_many_redirects"
    result.final_url = current


# --- resumable per-country cache (JSONL, append-on-complete) -----------------


def _metrics_path(cache_dir: Path, country: str) -> Path:
    d = Path(cache_dir) / "metrics"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{country}.jsonl"


def load_done_urls(path: Path) -> set[str]:
    """URLs already recorded — a re-run skips these (resumability)."""
    p = Path(path)
    if not p.exists():
        return set()
    done: set[str] = set()
    for line in p.read_text("utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                done.add(json.loads(line)["url"])
            except (json.JSONDecodeError, KeyError):
                continue  # a torn final line from an interrupted run
    return done


def append_result(path: Path, result: CrawlResult) -> None:
    with Path(path).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(result.to_json(), sort_keys=True) + "\n")


def crawl_country(
    sample: CountrySample,
    *,
    policy: CrawlPolicy,
    fetcher: Fetcher,
    resolver,
    robots: RobotsCache,
    rate_limiter: HostRateLimiter,
    cache_dir: Path,
    on_content: ContentSink | None = None,
    now: Callable[[], str] = _now_iso,
    monotonic: Callable[[], float] = time.monotonic,
) -> Path:
    """Crawl one country's sample as a resumable unit. Each URL's row is
    appended as it completes; an interrupted run resumes by skipping URLs
    already in the JSONL cache."""
    path = _metrics_path(cache_dir, sample.country)
    done = load_done_urls(path)
    for d in sample.sampled:
        if d.url in done:
            continue
        row = crawl_url(
            d.url,
            policy=policy,
            fetcher=fetcher,
            resolver=resolver,
            robots=robots,
            rate_limiter=rate_limiter,
            declared_format=d.primary_format,
            on_content=on_content,
            now=now,
            monotonic=monotonic,
        )
        append_result(path, row)
    return path
