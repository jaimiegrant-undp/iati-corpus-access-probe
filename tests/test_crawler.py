"""Offline tests for the safe resumable crawler (stdlib unittest, no pytest:
pytest is a package beyond the SIGNAL.md stack — a stop-and-ask).

No network, no live key, no live fetch. The Fetcher, the DNS resolver, the
robots.txt fetch, and the rate-limiter clock/sleep are all injected stubs.
Every binding rule in SIGNAL-METHOD §2 and every fault path is exercised
here; the bar is the scaffold's — each path produces a recorded result row,
never a crash.

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

from iati_access_probe.crawler import (  # noqa: E402
    CrawlConnectionError,
    CrawlReadError,
    CrawlTimeout,
    CrawlTLSError,
    append_result,
    crawl_country,
    crawl_url,
    load_done_urls,
)
from iati_access_probe.models import (  # noqa: E402
    CountrySample,
    CrawlPolicy,
    DistinctDocumentURL,
)
from iati_access_probe.safety import (  # noqa: E402
    DNSFailure,
    HostRateLimiter,
    RobotsCache,
)

POLICY = CrawlPolicy(per_host_interval_s=0.0, max_bytes=1000)


# --- stubs ------------------------------------------------------------------


class StubResponse:
    """Implements the FetchResponse protocol. `body` is bytes; `raise_in_iter`
    (an exception instance) is raised partway through streaming instead."""

    def __init__(self, status, headers=None, body=b"", *, raise_in_iter=None):
        self.status_code = status
        self.headers = headers or {}
        self._body = body
        self._raise = raise_in_iter
        self.closed = False

    def iter_bytes(self, chunk_size):
        if self._raise is not None:
            yield self._body[:1]
            raise self._raise
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i : i + chunk_size]

    def close(self):
        self.closed = True


class ScriptedFetcher:
    """Maps a url -> StubResponse, or a url -> exception to raise. Records
    every call so tests can assert what was (and was NOT) fetched."""

    def __init__(self, script):
        self._script = script
        self.calls = []

    def __call__(self, url, headers, timeout):
        self.calls.append(url)
        # The probe must never attach credentials.
        assert "Authorization" not in headers
        assert "Cookie" not in headers
        action = self._script[url]
        if isinstance(action, Exception):
            raise action
        return action


def resolver_for(mapping, *, dns_fail=()):
    """hostname -> [ip]. Unknown host defaults to a public IP; names in
    `dns_fail` raise DNSFailure."""

    def _resolve(host):
        if host in dns_fail:
            raise DNSFailure(f"NXDOMAIN {host}")
        return [mapping.get(host, "93.184.216.34")]  # example.com, public

    return _resolve


def robots_allowing():
    # 404 -> no robots.txt -> allowed (standard convention).
    return RobotsCache(lambda url: (404, ""))


def no_pace():
    return HostRateLimiter(0.0, clock=lambda: 0.0, sleep=lambda s: None)


def run(url, *, fetcher, resolver, robots=None, rate_limiter=None,
        policy=POLICY, on_content=None):
    return crawl_url(
        url,
        policy=policy,
        fetcher=fetcher,
        resolver=resolver,
        robots=robots or robots_allowing(),
        rate_limiter=rate_limiter or no_pace(),
        on_content=on_content,
        now=lambda: "2026-05-19T00:00:00+00:00",
        monotonic=lambda: 0.0,
    )


# --- happy path & content sink ---------------------------------------------


class TestResolutionAndSink(unittest.TestCase):
    def test_2xx_resolves_and_records(self):
        f = ScriptedFetcher(
            {"http://ex.org/a": StubResponse(200, {"Content-Type": "application/pdf"}, b"hello")}
        )
        r = run("http://ex.org/a", fetcher=f, resolver=resolver_for({}))
        self.assertTrue(r.resolved)
        self.assertEqual(r.http_status, 200)
        self.assertEqual(r.bytes_fetched, 5)
        self.assertEqual(r.access_barrier, "none")
        self.assertIsNone(r.error_category)
        self.assertEqual(r.final_url, "http://ex.org/a")
        self.assertIn("elapsed_s", r.to_json())

    def test_content_sink_receives_full_body_once(self):
        seen = []
        f = ScriptedFetcher({"http://ex.org/a": StubResponse(200, {}, b"abcdef")})
        r = run("http://ex.org/a", fetcher=f, resolver=resolver_for({}),
                on_content=lambda res, b: seen.append((res.url, b)))
        self.assertEqual(seen, [("http://ex.org/a", b"abcdef")])
        # Bytes are NEVER placed on the committed row.
        self.assertNotIn("body", r.to_json())

    def test_sink_releases_between_urls_no_accumulation(self):
        """Item 1's safety property: memory is bounded by ONE url's body and
        never accumulates across urls. Two urls through one sink — the second
        hand-off must be url2's bytes alone, not url1+url2."""
        seen = []
        f = ScriptedFetcher(
            {
                "http://ex.org/1": StubResponse(200, {}, b"first-body"),
                "http://ex.org/2": StubResponse(200, {}, b"2"),
            }
        )
        sink = lambda res, b: seen.append(b)  # noqa: E731
        run("http://ex.org/1", fetcher=f, resolver=resolver_for({}), on_content=sink)
        run("http://ex.org/2", fetcher=f, resolver=resolver_for({}), on_content=sink)
        self.assertEqual(seen, [b"first-body", b"2"])  # url2 NOT b"first-body2"

    def test_no_sink_discards_body(self):
        f = ScriptedFetcher({"http://ex.org/a": StubResponse(200, {}, b"xyz")})
        r = run("http://ex.org/a", fetcher=f, resolver=resolver_for({}))
        self.assertEqual(r.bytes_fetched, 3)  # counted, not retained


# --- size cap ---------------------------------------------------------------


class TestOversize(unittest.TestCase):
    def test_oversize_via_content_length_skips_before_download(self):
        seen = []
        f = ScriptedFetcher(
            {"http://ex.org/big": StubResponse(200, {"Content-Length": "999999"}, b"x" * 50)}
        )
        r = run("http://ex.org/big", fetcher=f, resolver=resolver_for({}),
                on_content=lambda res, b: seen.append(b))
        self.assertEqual(r.access_barrier, "oversize")
        self.assertEqual(seen, [])  # no hand-off

    def test_oversize_via_streamed_abort_drops_partial_buffer(self):
        seen = []
        big = b"x" * (POLICY.max_bytes + 500)
        f = ScriptedFetcher({"http://ex.org/big": StubResponse(200, {}, big)})
        r = run("http://ex.org/big", fetcher=f, resolver=resolver_for({}),
                on_content=lambda res, b: seen.append(b))
        self.assertEqual(r.access_barrier, "oversize")
        self.assertGreater(r.bytes_fetched, POLICY.max_bytes)
        self.assertEqual(seen, [])  # partial body dropped, not handed off


# --- redirects --------------------------------------------------------------


class TestRedirects(unittest.TestCase):
    def test_same_domain_redirect_not_flagged_offdomain(self):
        f = ScriptedFetcher(
            {
                "http://ex.org/a": StubResponse(302, {"Location": "http://ex.org/b"}),
                "http://ex.org/b": StubResponse(200, {}, b"ok"),
            }
        )
        r = run("http://ex.org/a", fetcher=f, resolver=resolver_for({}))
        self.assertFalse(r.redirect_offdomain)
        self.assertTrue(r.resolved)
        self.assertEqual(r.final_url, "http://ex.org/b")
        self.assertEqual(len(r.redirect_chain), 1)

    def test_offdomain_redirect_recorded_as_finding(self):
        f = ScriptedFetcher(
            {
                "http://ex.org/a": StubResponse(302, {"Location": "http://other.com/x"}),
                "http://other.com/x": StubResponse(200, {}, b"ok"),
            }
        )
        r = run("http://ex.org/a", fetcher=f, resolver=resolver_for({}))
        self.assertTrue(r.redirect_offdomain)
        self.assertTrue(r.redirect_chain[0]["offdomain"])

    def test_too_many_redirects_recorded_not_crash(self):
        f = ScriptedFetcher(
            {
                "http://ex.org/a": StubResponse(302, {"Location": "http://ex.org/b"}),
                "http://ex.org/b": StubResponse(302, {"Location": "http://ex.org/a"}),
            }
        )
        r = run("http://ex.org/a", fetcher=f, resolver=resolver_for({}))
        self.assertEqual(r.error_category, "too_many_redirects")


# --- non-public host: initial AND on a redirect hop (distinct fixtures) -----


class TestNonPublicHost(unittest.TestCase):
    def test_non_public_initial_host_never_fetched(self):
        f = ScriptedFetcher({})  # nothing should be fetched
        r = run(
            "http://internal/secret",
            fetcher=f,
            resolver=resolver_for({"internal": "127.0.0.1"}),
        )
        self.assertEqual(r.access_barrier, "non_public_host")
        self.assertEqual(f.calls, [])  # no egress at all

    def test_non_public_on_redirect_hop_caught_and_not_followed(self):
        """The per-hop re-application IS the SSRF rule. A public URL that
        redirects to a private address must be caught — a suite that only
        tested the initial host would pass a crawler still vulnerable here."""
        f = ScriptedFetcher(
            {
                "http://pub.example/a": StubResponse(
                    302, {"Location": "http://intranet/x"}
                ),
                "http://intranet/x": StubResponse(200, {}, b"SHOULD-NOT-FETCH"),
            }
        )
        r = run(
            "http://pub.example/a",
            fetcher=f,
            resolver=resolver_for({"intranet": "10.0.0.5"}),
        )
        self.assertEqual(r.access_barrier, "non_public_host")
        self.assertEqual(f.calls, ["http://pub.example/a"])  # hop NOT followed
        self.assertEqual(len(r.redirect_chain), 1)  # the hop was recorded


# --- auth -------------------------------------------------------------------


class TestAuth(unittest.TestCase):
    def test_401_is_auth_required(self):
        f = ScriptedFetcher({"http://ex.org/a": StubResponse(401, {}, b"")})
        r = run("http://ex.org/a", fetcher=f, resolver=resolver_for({}))
        self.assertEqual(r.access_barrier, "auth_required")

    def test_www_authenticate_header_is_auth_required(self):
        f = ScriptedFetcher(
            {"http://ex.org/a": StubResponse(200, {"WWW-Authenticate": "Basic"}, b"x")}
        )
        r = run("http://ex.org/a", fetcher=f, resolver=resolver_for({}))
        self.assertEqual(r.access_barrier, "auth_required")


# --- robots: disallow AND unavailable-is-not-disallow (distinct fixtures) ---


class TestRobots(unittest.TestCase):
    def test_robots_disallow_blocks_and_does_not_fetch(self):
        robots = RobotsCache(lambda u: (200, "User-agent: *\nDisallow: /"))
        f = ScriptedFetcher({})  # resource must never be fetched
        r = run("http://ex.org/a", fetcher=f, resolver=resolver_for({}), robots=robots)
        self.assertEqual(r.access_barrier, "robots_disallowed")
        self.assertEqual(f.calls, [])

    def test_robots_unavailable_is_not_disallowed(self):
        """A 5xx on robots.txt must NOT be treated as a deliberate disallow —
        that would silently shrink the crawl. RobotsCache records the host as
        'unavailable' and the resource fetch proceeds."""
        robots = RobotsCache(lambda u: (503, ""))
        f = ScriptedFetcher({"http://ex.org/a": StubResponse(200, {}, b"ok")})
        r = run("http://ex.org/a", fetcher=f, resolver=resolver_for({}), robots=robots)
        self.assertNotEqual(r.access_barrier, "robots_disallowed")
        self.assertTrue(r.resolved)
        self.assertEqual(robots.robots_status["http://ex.org"], "unavailable")

    def test_robots_fetch_is_paced_with_the_resource_fetch(self):
        """Item 4: polite per-host pacing applies to EVERY request to a host,
        the robots.txt fetch included. With a shared limiter, the robots hit
        and the subsequent resource hit are paced as two hits to one host —
        so a sleep of one interval is recorded between them, not zero."""
        sleeps = []
        limiter = HostRateLimiter(
            5.0, clock=lambda: 0.0, sleep=lambda s: sleeps.append(s)
        )
        robots = RobotsCache(lambda u: (404, ""), rate_limiter=limiter)
        f = ScriptedFetcher({"http://ex.org/a": StubResponse(200, {}, b"ok")})
        run("http://ex.org/a", fetcher=f, resolver=resolver_for({}),
            robots=robots, rate_limiter=limiter)
        # wait #1 (robots) no sleep; wait #2 (resource) sleeps the interval.
        self.assertEqual(sleeps, [5.0])


# --- fault isolation: every failure is a recorded row, never a crash --------


class TestFaultIsolation(unittest.TestCase):
    def _err(self, exc):
        f = ScriptedFetcher({"http://ex.org/a": exc})
        return run("http://ex.org/a", fetcher=f, resolver=resolver_for({}))

    def test_dns_failure(self):
        f = ScriptedFetcher({})
        r = run("http://ex.org/a", fetcher=f,
                resolver=resolver_for({}, dns_fail={"ex.org"}))
        self.assertEqual(r.error_category, "dns_failure")
        self.assertEqual(f.calls, [])

    def test_timeout(self):
        self.assertEqual(self._err(CrawlTimeout("t")).error_category, "timeout")

    def test_tls_error(self):
        self.assertEqual(self._err(CrawlTLSError("t")).error_category, "tls_error")

    def test_connection_error(self):
        self.assertEqual(
            self._err(CrawlConnectionError("c")).error_category, "connection_error"
        )

    def test_read_error_mid_stream(self):
        f = ScriptedFetcher(
            {"http://ex.org/a": StubResponse(200, {}, b"abc", raise_in_iter=RuntimeError("boom"))}
        )
        r = run("http://ex.org/a", fetcher=f, resolver=resolver_for({}))
        self.assertEqual(r.error_category, "read_error")

    def test_timeout_mid_stream_is_timeout_not_read_error(self):
        f = ScriptedFetcher(
            {"http://ex.org/a": StubResponse(200, {}, b"abc", raise_in_iter=CrawlTimeout("t"))}
        )
        r = run("http://ex.org/a", fetcher=f, resolver=resolver_for({}))
        self.assertEqual(r.error_category, "timeout")

    def test_unexpected_exception_is_isolated(self):
        r = self._err(ValueError("totally unexpected"))
        self.assertEqual(r.error_category, "connection_error")
        self.assertEqual(
            r.redirect_chain[-1], {"unexpected_error": "ValueError"}
        )


# --- resumability -----------------------------------------------------------


def _durl(url):
    return DistinctDocumentURL(
        url=url,
        primary_category="A01",
        primary_format="application/pdf",
        occurrence_count=1,
        category_counts={"A01": 1},
        format_counts={"application/pdf": 1},
        iati_identifiers=("XX-1",),
    )


class TestResumability(unittest.TestCase):
    def test_resume_skips_done_urls_and_tolerates_torn_line(self):
        with tempfile.TemporaryDirectory() as d:
            cache = Path(d)
            mpath = cache / "metrics" / "FJ.jsonl"
            mpath.parent.mkdir(parents=True)
            # url1 already recorded; plus a torn final line from an
            # interrupted run — load_done_urls must tolerate it.
            mpath.write_text(
                json.dumps({"url": "http://ex.org/1"}) + "\n{ torn\n",
                encoding="utf-8",
            )
            sample = CountrySample(
                country="FJ", seed="s", requested_n=2, frame_size=2,
                is_census=True,
                sampled=(_durl("http://ex.org/1"), _durl("http://ex.org/2")),
            )
            f = ScriptedFetcher({"http://ex.org/2": StubResponse(200, {}, b"ok")})
            crawl_country(
                sample,
                policy=POLICY,
                fetcher=f,
                resolver=resolver_for({}),
                robots=robots_allowing(),
                rate_limiter=no_pace(),
                cache_dir=cache,
                now=lambda: "2026-05-19T00:00:00+00:00",
                monotonic=lambda: 0.0,
            )
            # url1 skipped (already done), only url2 fetched.
            self.assertEqual(f.calls, ["http://ex.org/2"])
            done = load_done_urls(mpath)
            self.assertIn("http://ex.org/1", done)
            self.assertIn("http://ex.org/2", done)

    def test_load_done_urls_absent_file_is_empty(self):
        self.assertEqual(load_done_urls(Path("does-not-exist.jsonl")), set())


if __name__ == "__main__":
    unittest.main()
