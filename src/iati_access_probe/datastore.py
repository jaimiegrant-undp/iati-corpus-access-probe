"""Thin, documented IATI Datastore v3 wrapper.

Built fresh for this probe — it does NOT import from the Phase 0.5 repo. It
carries the Phase 0.5 *lesson*, not its code: **a wrong field name is a
silent-zero hazard**. Solr silently drops an unknown `fl` field rather than
erroring, so a typo'd field name yields empty results that look like "this
country has no documents" instead of "the query is wrong". This wrapper
therefore fails *loudly* on an unrecognised field rather than returning a
silent zero.

Scope of this module (deliverable 3): auth, polite pacing, pagination, loud
field verification, and the documented activity-doc -> document-link
occurrence flattener. No network is performed in tests: the HTTP transport is
injected, so the whole wrapper is exercised offline against canned Solr JSON.
The live field verification and the seeded draw are gated on the IATI key.

Datastore v3 shape (per docs.datastore.iatistandard.org, confirmed live
before the draw):
  endpoint   https://api.iatistandard.org/datastore/activity/select
  auth       header `Ocp-Apim-Subscription-Key` (free key; never logged)
  params     Solr q, fl, rows, start, wt=json, sort
  fields     iati_identifier (single), recipient_country_code (multi),
             document_link_url / document_link_format /
             document_link_category_code (multi, index-aligned per link)
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from typing import Any, Protocol

from .models import UNCATEGORISED, DocumentLinkOccurrence

ACTIVITY_SELECT = "https://api.iatistandard.org/datastore/activity/select"
AUTH_HEADER = "Ocp-Apim-Subscription-Key"

# The document-link fields the probe needs, with the documented Solr names.
DOCLINK_FIELDS: tuple[str, ...] = (
    "iati_identifier",
    "recipient_country_code",
    "document_link_url",
    "document_link_format",
    "document_link_category_code",
)


class DatastoreError(RuntimeError):
    """Base for all Datastore wrapper failures."""


class DatastoreAuthError(DatastoreError):
    """401/403 — missing or rejected API key."""


class DatastoreHTTPError(DatastoreError):
    """Any other non-2xx response from the Datastore."""


class DatastoreFieldError(DatastoreError):
    """A requested field was not present in returned docs (the Phase 0.5
    silent-zero hazard) — raised loudly instead of returning empty results."""


class _Response(Protocol):
    status_code: int
    text: str

    def json(self) -> Any: ...


# transport(url, headers, params) -> response-like. The default wraps
# `requests`; tests inject a stub returning canned Solr JSON. No live key,
# no network, in tests.
Transport = Callable[[str, dict[str, str], dict[str, Any]], _Response]


def _requests_transport(timeout: tuple[float, float]) -> Transport:
    """Default transport: a `requests` session with a real (connect, read)
    timeout so a hung Datastore cannot stall the build."""
    import requests  # local import: tests never need requests installed

    session = requests.Session()

    def _send(url: str, headers: dict[str, str], params: dict[str, Any]) -> _Response:
        return session.get(url, headers=headers, params=params, timeout=timeout)

    return _send


class DatastoreClient:
    """Minimal Solr-over-HTTP client for the activity collection.

    Politeness: a minimum interval between requests (this is IATI's own API,
    but it is still paced). `sleep` is injectable so tests do not really
    sleep. `min_interval_s=0` disables pacing in tests.
    """

    def __init__(
        self,
        api_key: str,
        *,
        endpoint: str = ACTIVITY_SELECT,
        transport: Transport | None = None,
        timeout: tuple[float, float] = (10.0, 60.0),
        min_interval_s: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not api_key:
            # Fail before any request — an empty key is an auth error, not a
            # mysterious 401 later.
            raise DatastoreAuthError("no IATI API key supplied")
        self._key = api_key
        self._endpoint = endpoint
        self._transport = transport or _requests_transport(timeout)
        self._min_interval = min_interval_s
        self._sleep = sleep
        self._clock = clock
        self._last_request_at: float | None = None

    # --- low-level request ---------------------------------------------------

    def _pace(self) -> None:
        if self._last_request_at is None or self._min_interval <= 0:
            return
        elapsed = self._clock() - self._last_request_at
        if elapsed < self._min_interval:
            self._sleep(self._min_interval - elapsed)

    def _get(self, params: dict[str, Any]) -> dict[str, Any]:
        self._pace()
        headers = {
            AUTH_HEADER: self._key,
            "Accept": "application/json",
            "User-Agent": "iati-corpus-access-probe (IATI research tooling)",
        }
        try:
            resp = self._transport(self._endpoint, headers, params)
        finally:
            self._last_request_at = self._clock()

        status = resp.status_code
        if status in (401, 403):
            # Never echo the key or the headers in the message.
            raise DatastoreAuthError(
                f"Datastore rejected the API key (HTTP {status})"
            )
        if not 200 <= status < 300:
            snippet = (resp.text or "")[:300]
            raise DatastoreHTTPError(f"Datastore HTTP {status}: {snippet}")
        try:
            return resp.json()
        except Exception as exc:  # malformed body is a loud failure, not zero
            raise DatastoreHTTPError(f"Datastore returned non-JSON body: {exc}")

    # --- field verification (the Phase 0.5 lesson) ---------------------------

    def verify_fields(
        self,
        fields: tuple[str, ...] = DOCLINK_FIELDS,
        *,
        probe_q: str = "document_link_url:[* TO *]",
        probe_rows: int = 25,
    ) -> None:
        """Loudly confirm every field name is real before the draw.

        Solr drops an unknown `fl` field silently, so we cannot trust an
        echo. Instead: fetch a small probe of docs that *should* carry these
        fields and assert each requested field actually appears on at least
        one doc. A field never seen, or an empty probe, is a loud failure —
        the exact opposite of a silent zero.
        """
        data = self._get(
            {
                "q": probe_q,
                "fl": ",".join(fields),
                "rows": probe_rows,
                "wt": "json",
            }
        )
        docs = data.get("response", {}).get("docs", [])
        if not docs:
            raise DatastoreFieldError(
                "field verification probe returned zero docs — cannot "
                f"confirm fields {fields!r}; refusing to proceed (a silent "
                "zero here would corrupt every per-country figure)"
            )
        seen: set[str] = set()
        for d in docs:
            seen.update(d.keys())
        missing = [f for f in fields if f not in seen]
        if missing:
            raise DatastoreFieldError(
                f"these requested fields never appeared in a {len(docs)}-doc "
                f"probe and are likely misnamed: {missing}. Seen field "
                f"names: {sorted(seen)}"
            )

    # --- pagination ----------------------------------------------------------

    def iter_docs(
        self,
        q: str,
        fields: tuple[str, ...],
        *,
        page_size: int = 200,
        max_docs: int | None = None,
        sort: str = "iati_identifier asc",
    ) -> Iterator[dict[str, Any]]:
        """Yield activity docs for `q`, paginating on Solr start/rows.

        A stable `sort` is required: Solr deep paging without a deterministic
        sort can repeat or skip docs. `max_docs` bounds a probe run.
        """
        start = 0
        yielded = 0
        while True:
            data = self._get(
                {
                    "q": q,
                    "fl": ",".join(fields),
                    "rows": page_size,
                    "start": start,
                    "sort": sort,
                    "wt": "json",
                }
            )
            response = data.get("response", {})
            docs = response.get("docs", [])
            num_found = response.get("numFound", 0)
            if not docs:
                break
            for d in docs:
                yield d
                yielded += 1
                if max_docs is not None and yielded >= max_docs:
                    return
            start += len(docs)
            if start >= num_found:
                break


# --- activity-doc -> document-link occurrence flattener ----------------------
# document_link_url / _format / _category_code are multivalued and
# index-aligned per document-link. Ragged arrays (differing lengths) are a
# real Datastore data-quality hazard; they are handled explicitly and
# COUNTED, never silently zip-truncated (silent truncation would
# under-report the frame and look like clean data).


def _as_list(v: Any) -> list[Any]:
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def activity_docs_to_occurrences(
    docs: list[dict[str, Any]],
    recipient_country: str,
) -> tuple[list[DocumentLinkOccurrence], dict[str, int]]:
    """Flatten activity docs into per-document-link occurrence records.

    Occurrences are attributed to `recipient_country` — the country whose
    frame this query represents (an activity may list several recipient
    countries; the frame is defined per queried country, SIGNAL-METHOD §1.3).

    Returns (occurrences, anomalies) where anomalies counts:
      ragged_activities  doc whose doclink arrays had differing lengths
      missing_url        a doclink index with no URL (cannot be crawled)
    Both are surfaced, not hidden, so the verdict can state them honestly.
    """
    occurrences: list[DocumentLinkOccurrence] = []
    anomalies = {"ragged_activities": 0, "missing_url": 0}

    for d in docs:
        iid_raw = d.get("iati_identifier", "")
        iid = iid_raw[0] if isinstance(iid_raw, list) else iid_raw
        urls = _as_list(d.get("document_link_url"))
        fmts = _as_list(d.get("document_link_format"))
        cats = _as_list(d.get("document_link_category_code"))

        n = max(len(urls), len(fmts), len(cats))
        if len({len(urls), len(fmts), len(cats)} - {0}) > 1:
            anomalies["ragged_activities"] += 1

        for i in range(n):
            url = urls[i] if i < len(urls) else None
            if not url:
                anomalies["missing_url"] += 1
                continue  # a missing URL is not a crawl target; count it
            occurrences.append(
                DocumentLinkOccurrence(
                    iati_identifier=str(iid),
                    recipient_country=recipient_country,
                    url=str(url),
                    declared_format=str(fmts[i]) if i < len(fmts) and fmts[i] else "",
                    category=str(cats[i]) if i < len(cats) and cats[i] else UNCATEGORISED,
                )
            )
    return occurrences, anomalies
