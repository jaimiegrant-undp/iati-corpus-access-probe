"""Live transport adapters (requests-backed).

Isolated from crawler.py so the crawler pipeline and all its fault paths are
tested offline with a stub Fetcher — `requests` is never imported by the test
suite. This module is only exercised during the live crawl run.

It maps `requests` exceptions onto the crawler's error taxonomy so the
fault-isolation guarantees hold for real network failures exactly as they do
for the stubbed ones.
"""

from __future__ import annotations

from collections.abc import Iterator

from .crawler import (
    CrawlConnectionError,
    CrawlReadError,
    CrawlTimeout,
    CrawlTLSError,
    Fetcher,
)


class _RequestsResponse:
    """Adapts a streaming requests.Response to the FetchResponse protocol."""

    def __init__(self, resp) -> None:
        self._resp = resp
        self.status_code = resp.status_code
        self.headers = dict(resp.headers)

    def iter_bytes(self, chunk_size: int) -> Iterator[bytes]:
        import requests

        try:
            yield from self._resp.iter_content(chunk_size=chunk_size)
        except requests.exceptions.SSLError as exc:
            raise CrawlTLSError(str(exc)) from exc
        except (requests.exceptions.Timeout,) as exc:
            raise CrawlTimeout(str(exc)) from exc
        except requests.exceptions.RequestException as exc:
            raise CrawlReadError(str(exc)) from exc

    def close(self) -> None:
        self._resp.close()


def requests_fetcher() -> Fetcher:
    """Default live Fetcher: streaming GET, NO auto-redirects (the crawler
    follows them manually so every hop is re-checked), NO credentials.
    Maps requests exceptions to the crawler error taxonomy."""
    import requests

    session = requests.Session()

    def _fetch(url: str, headers: dict[str, str], timeout: tuple[float, float]):
        try:
            resp = session.get(
                url,
                headers=headers,
                timeout=timeout,
                stream=True,
                allow_redirects=False,
            )
        except requests.exceptions.SSLError as exc:
            raise CrawlTLSError(str(exc)) from exc
        except requests.exceptions.Timeout as exc:
            raise CrawlTimeout(str(exc)) from exc
        except requests.exceptions.ConnectionError as exc:
            raise CrawlConnectionError(str(exc)) from exc
        except requests.exceptions.RequestException as exc:
            raise CrawlConnectionError(str(exc)) from exc
        return _RequestsResponse(resp)

    return _fetch


def robots_fetch_via(
    fetcher: Fetcher,
    user_agent: str,
    *,
    timeout: tuple[float, float],
    cap_bytes: int = 512 * 1024,
):
    """Wrap a Fetcher into the (url) -> (status, body) callable RobotsCache
    needs. The robots.txt fetch goes through the same transport (so it is
    paced and fault-isolated) and its body is read with a small cap.

    `timeout` is (connect, read); the live wiring passes
    (policy.connect_timeout_s, policy.robots_timeout_s) so the robots fetch
    honours the confirmed crawl policy rather than a hardcoded pair."""

    def _get(robots_url: str) -> tuple[int, str]:
        resp = fetcher(robots_url, {"User-Agent": user_agent}, timeout)
        try:
            buf = bytearray()
            for chunk in resp.iter_bytes(32 * 1024):
                buf += chunk
                if len(buf) > cap_bytes:
                    break
            return resp.status_code, buf.decode("utf-8", errors="replace")
        finally:
            resp.close()

    return _get
