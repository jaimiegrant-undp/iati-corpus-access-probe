"""Host-safety primitives for the crawler (SIGNAL-METHOD §2).

Isolated here so the SSRF / politeness rules are independently testable with
no network: the DNS resolver and the HTTP fetch are injected, so every branch
(private IP, DNS failure, off-domain redirect, robots disallow, rate pacing)
is exercised offline.

These are binding rules, not speed knobs. Nothing here is loosened to make a
run go faster.
"""

from __future__ import annotations

import ipaddress
import socket
import urllib.robotparser
from collections.abc import Callable
from urllib.parse import urlsplit

# resolver(hostname) -> list of IP strings. Default uses the system resolver;
# tests inject a fake (and raise DNSFailure to simulate NXDOMAIN/timeout).
Resolver = Callable[[str], list[str]]


class DNSFailure(Exception):
    """Hostname did not resolve (NXDOMAIN, resolver timeout, etc.)."""


def system_resolver(hostname: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise DNSFailure(str(exc)) from exc
    return sorted({info[4][0] for info in infos})


def is_public_address(ip_str: str) -> bool:
    """True only if `ip_str` is a globally-routable public address.

    Blocks loopback, link-local, private (incl. CGNAT 100.64/10), multicast,
    reserved and unspecified ranges, and unwraps IPv4-mapped IPv6 so an
    attacker cannot smuggle 127.0.0.1 as ::ffff:127.0.0.1. An IATI document
    link should never legitimately point at one of these; where this fires it
    is both an SSRF closure and a small data-quality finding.
    """
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    if getattr(ip, "ipv4_mapped", None) is not None:
        ip = ip.ipv4_mapped
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or not ip.is_global
    )


def host_is_public(hostname: str, resolver: Resolver) -> tuple[bool, list[str]]:
    """Resolve `hostname` and return (all-public?, resolved IPs).

    Conservative: if ANY resolved address is non-public the host is treated
    as non-public (a mixed answer can be a DNS-rebinding attempt). Raises
    DNSFailure if the name does not resolve at all.
    """
    ips = resolver(hostname)
    if not ips:
        raise DNSFailure(f"no addresses for {hostname!r}")
    all_public = all(is_public_address(ip) for ip in ips)
    return all_public, ips


# A small, documented set of common multi-label public suffixes. Full
# correctness needs the Public Suffix List (tldextract) — a package beyond
# the SIGNAL.md stack, hence a stop-and-ask, NOT added here. This heuristic
# is best-effort and stated as a known limit in the verdict (SIGNAL-METHOD
# §6 best-effort framing): off-domain detection may be imperfect for exotic
# multi-part suffixes.
_TWO_LABEL_SUFFIXES = frozenset(
    {
        "co.uk", "org.uk", "gov.uk", "ac.uk", "net.uk",
        "com.au", "org.au", "net.au", "gov.au", "edu.au",
        "co.nz", "org.nz", "govt.nz",
        "co.za", "org.za", "gov.za",
        "com.br", "org.br", "gov.br",
        "co.ke", "or.ke", "go.ke",
        "co.in", "org.in", "gov.in", "nic.in",
        "go.ug", "or.ug", "gov.np", "org.np",
    }
)


def registered_domain(host: str) -> str:
    """Best-effort eTLD+1 of `host`, for off-domain redirect detection."""
    host = (host or "").strip().lower().rstrip(".")
    labels = host.split(".")
    if len(labels) <= 2:
        return host
    if ".".join(labels[-2:]) in _TWO_LABEL_SUFFIXES:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def same_registered_domain(url_a: str, url_b: str) -> bool:
    return registered_domain(urlsplit(url_a).hostname or "") == registered_domain(
        urlsplit(url_b).hostname or ""
    )


class RobotsCache:
    """Fetches and honours robots.txt, once per host.

    The robots.txt fetch goes through the SAME injected fetcher as the crawl
    (so it is offline-testable and counts toward politeness). Policy on the
    robots fetch itself:
      - 2xx  -> parse and honour the rules;
      - 4xx  -> no robots.txt => allowed (standard convention);
      - 5xx / fetch error / timeout -> robots is *unavailable*, NOT
        *disallowed*. We allow the resource fetch but record robots_status so
        the verdict can separate "host said no" from "couldn't check". This
        avoids miscounting a transient host wobble as a deliberate disallow
        (a real bias risk — flagged as a methodology decision).
    """

    def __init__(
        self,
        robots_fetch: Callable[[str], tuple[int, str]],
        *,
        rate_limiter: "HostRateLimiter | None" = None,
    ) -> None:
        self._fetch = robots_fetch
        # Polite per-host pacing applies to EVERY request to a host, the
        # robots.txt fetch included — otherwise first contact is robots +
        # resource back-to-back with no delay (a binding-rule gap, not a
        # nicety). Shared with the crawler's limiter so the robots hit and
        # the subsequent resource hit are paced as two hits to one host.
        self._rate_limiter = rate_limiter
        self._parsers: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self.robots_status: dict[str, str] = {}

    def _key(self, url: str) -> tuple[str, str]:
        parts = urlsplit(url)
        return parts.scheme, parts.netloc

    def can_fetch(self, url: str, user_agent: str) -> bool:
        scheme, netloc = self._key(url)
        host_key = f"{scheme}://{netloc}"
        if host_key not in self._parsers:
            self._load(host_key, scheme, netloc)
        parser = self._parsers[host_key]
        if parser is None:  # unavailable or absent -> allowed (recorded)
            return True
        return parser.can_fetch(user_agent, url)

    def _load(self, host_key: str, scheme: str, netloc: str) -> None:
        robots_url = f"{scheme}://{netloc}/robots.txt"
        if self._rate_limiter is not None:
            host = urlsplit(robots_url).hostname or netloc
            self._rate_limiter.wait(host)
        try:
            status, body = self._fetch(robots_url)
        except Exception:
            self._parsers[host_key] = None
            self.robots_status[host_key] = "unavailable"
            return
        if 200 <= status < 300:
            rp = urllib.robotparser.RobotFileParser()
            rp.parse(body.splitlines())
            self._parsers[host_key] = rp
            self.robots_status[host_key] = "present"
        elif 400 <= status < 500:
            self._parsers[host_key] = None
            self.robots_status[host_key] = "absent"
        else:
            self._parsers[host_key] = None
            self.robots_status[host_key] = "unavailable"


class HostRateLimiter:
    """Polite per-host minimum interval. The crawl is sequential, so this is
    a simple per-host last-seen clock. clock/sleep injected for tests.

    No separate cross-host (global) throttle by design: the crawl runs one
    request at a time and each host is hit at most once per interval, so
    distinct hosts touched once each cannot overload any single host — which
    is exactly what the politeness rule protects. SIGNAL-METHOD §2 "global
    pace" is satisfied by the sequential, concurrency-1 execution itself.
    """

    def __init__(
        self,
        interval_s: float,
        *,
        clock: Callable[[], float],
        sleep: Callable[[float], None],
    ) -> None:
        self._interval = interval_s
        self._clock = clock
        self._sleep = sleep
        self._last: dict[str, float] = {}

    def wait(self, host: str) -> None:
        if self._interval <= 0:
            return
        last = self._last.get(host)
        now = self._clock()
        if last is not None:
            elapsed = now - last
            if elapsed < self._interval:
                self._sleep(self._interval - elapsed)
        self._last[host] = self._clock()
