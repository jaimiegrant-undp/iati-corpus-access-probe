"""Offline tests for the Datastore wrapper (stdlib unittest, no pytest).

No network, no live key: the HTTP transport is a stub returning canned Solr
JSON. Covers pagination, auth/HTTP/field-error loud failures, polite pacing,
and the activity-doc -> occurrence flattener (incl. ragged-array anomalies).

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from iati_access_probe.datastore import (  # noqa: E402
    DOCLINK_FIELDS,
    DatastoreAuthError,
    DatastoreClient,
    DatastoreFieldError,
    DatastoreHTTPError,
    activity_docs_to_occurrences,
)
from iati_access_probe.models import UNCATEGORISED  # noqa: E402

PAGES = json.loads(
    (Path(__file__).parent / "fixtures" / "datastore_solr_pages.json").read_text(
        "utf-8"
    )
)


class StubResponse:
    def __init__(self, status: int, body, *, text: str = "") -> None:
        self.status_code = status
        self._body = body
        self.text = text

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


class StubTransport:
    """Returns queued responses; records the params of every call."""

    def __init__(self, responses: list[StubResponse]) -> None:
        self._responses = responses
        self.calls: list[dict] = []

    def __call__(self, url, headers, params) -> StubResponse:
        self.calls.append({"url": url, "headers": headers, "params": params})
        return self._responses[min(len(self.calls) - 1, len(self._responses) - 1)]


def make_client(responses, **kw) -> tuple[DatastoreClient, StubTransport]:
    t = StubTransport(responses)
    c = DatastoreClient(
        "test-key", transport=t, min_interval_s=0, **kw
    )
    return c, t


class TestAuthAndHTTP(unittest.TestCase):
    def test_empty_key_fails_at_construction(self) -> None:
        with self.assertRaises(DatastoreAuthError):
            DatastoreClient("", transport=StubTransport([]))

    def test_401_raises_auth_error_without_leaking_key(self) -> None:
        c, _ = make_client([StubResponse(401, {}, text="Access denied")])
        with self.assertRaises(DatastoreAuthError) as ctx:
            list(c.iter_docs("q", DOCLINK_FIELDS))
        self.assertNotIn("test-key", str(ctx.exception))

    def test_500_raises_http_error(self) -> None:
        c, _ = make_client([StubResponse(500, {}, text="boom")])
        with self.assertRaises(DatastoreHTTPError):
            list(c.iter_docs("q", DOCLINK_FIELDS))

    def test_non_json_body_is_loud_not_silent(self) -> None:
        c, _ = make_client([StubResponse(200, ValueError("not json"))])
        with self.assertRaises(DatastoreHTTPError):
            list(c.iter_docs("q", DOCLINK_FIELDS))

    def test_auth_header_is_sent(self) -> None:
        c, t = make_client([StubResponse(200, PAGES["page2"])])
        list(c.iter_docs("q", DOCLINK_FIELDS))
        self.assertEqual(
            t.calls[0]["headers"]["Ocp-Apim-Subscription-Key"], "test-key"
        )


class TestPagination(unittest.TestCase):
    def test_iterates_all_pages_until_numfound(self) -> None:
        c, t = make_client(
            [StubResponse(200, PAGES["page1"]), StubResponse(200, PAGES["page2"])]
        )
        docs = list(c.iter_docs("q", DOCLINK_FIELDS, page_size=2))
        self.assertEqual([d["iati_identifier"] for d in docs],
                         ["AA-ACT-1", "AA-ACT-2", "AA-ACT-3"])
        self.assertEqual(t.calls[0]["params"]["start"], 0)
        self.assertEqual(t.calls[1]["params"]["start"], 2)

    def test_max_docs_bounds_the_run(self) -> None:
        c, _ = make_client([StubResponse(200, PAGES["page1"])])
        docs = list(c.iter_docs("q", DOCLINK_FIELDS, page_size=2, max_docs=1))
        self.assertEqual(len(docs), 1)

    def test_stable_sort_is_requested(self) -> None:
        c, t = make_client([StubResponse(200, PAGES["page2"])])
        list(c.iter_docs("q", DOCLINK_FIELDS))
        self.assertIn("sort", t.calls[0]["params"])


class TestFieldVerification(unittest.TestCase):
    def test_passes_when_all_fields_present(self) -> None:
        c, _ = make_client([StubResponse(200, PAGES["page1"])])
        c.verify_fields()  # must not raise

    def test_raises_naming_misnamed_field(self) -> None:
        # A doc missing 'document_link_category_code' (e.g. typo'd fl).
        body = {"response": {"numFound": 1, "docs": [
            {"iati_identifier": "X", "recipient_country_code": ["AA"],
             "document_link_url": ["u"], "document_link_format": ["f"]}
        ]}}
        c, _ = make_client([StubResponse(200, body)])
        with self.assertRaises(DatastoreFieldError) as ctx:
            c.verify_fields()
        self.assertIn("document_link_category_code", str(ctx.exception))

    def test_zero_doc_probe_is_loud_failure(self) -> None:
        c, _ = make_client([StubResponse(200, {"response": {"numFound": 0, "docs": []}})])
        with self.assertRaises(DatastoreFieldError):
            c.verify_fields()


class TestPacing(unittest.TestCase):
    def test_sleeps_the_remaining_interval_between_requests(self) -> None:
        slept: list[float] = []
        # clock() calls in order: req1 finally, req2 pace, req2 finally.
        # (req1's _pace() does not call clock — last_request_at is None.)
        ticks = iter([100.0, 100.3, 100.3, 100.3])
        c = DatastoreClient(
            "k",
            transport=StubTransport(
                [StubResponse(200, PAGES["page1"]), StubResponse(200, PAGES["page2"])]
            ),
            min_interval_s=1.0,
            sleep=slept.append,
            clock=lambda: next(ticks),
        )
        list(c.iter_docs("q", DOCLINK_FIELDS, page_size=2))
        # Second request paced: 0.3s elapsed of a 1.0s minimum -> sleep 0.7s.
        self.assertEqual(len(slept), 1)
        self.assertAlmostEqual(slept[0], 0.7, places=6)


class TestFlattener(unittest.TestCase):
    def setUp(self) -> None:
        self.docs = (
            PAGES["page1"]["response"]["docs"]
            + PAGES["page2"]["response"]["docs"]
        )

    def test_flattens_index_aligned_arrays(self) -> None:
        occ, _ = activity_docs_to_occurrences(self.docs, "AA")
        # a1: 2 links, a2: 1 link, a3: 2 urls -> 5 occurrences total.
        self.assertEqual(len(occ), 5)
        a1 = [o for o in occ if o.iati_identifier == "AA-ACT-1"]
        self.assertEqual([(o.url.split("/")[-1], o.category) for o in a1],
                         [("a1-d1.pdf", "A01"), ("a1-d2.pdf", "A02")])

    def test_ragged_arrays_counted_not_silently_truncated(self) -> None:
        _, anomalies = activity_docs_to_occurrences(self.docs, "AA")
        # a3 has 2 urls, 1 format, 0 categories -> ragged.
        self.assertEqual(anomalies["ragged_activities"], 1)

    def test_missing_category_becomes_uncategorised(self) -> None:
        occ, _ = activity_docs_to_occurrences(self.docs, "AA")
        a3 = [o for o in occ if o.iati_identifier == "AA-ACT-3"]
        self.assertEqual(len(a3), 2)
        self.assertTrue(all(o.category == UNCATEGORISED for o in a3))
        # Missing format at the 2nd index becomes "" (declared unknown).
        self.assertEqual(a3[1].declared_format, "")

    def test_missing_url_is_counted_and_skipped(self) -> None:
        docs = [{
            "iati_identifier": "Z",
            "document_link_url": ["", "https://example.org/ok.pdf"],
            "document_link_format": ["application/pdf", "application/pdf"],
            "document_link_category_code": ["A01", "A01"],
        }]
        occ, anomalies = activity_docs_to_occurrences(docs, "AA")
        self.assertEqual(len(occ), 1)
        self.assertEqual(anomalies["missing_url"], 1)

    def test_iati_identifier_as_list_is_handled(self) -> None:
        docs = [{
            "iati_identifier": ["LIST-FORM"],
            "document_link_url": ["https://example.org/x.pdf"],
            "document_link_format": ["application/pdf"],
            "document_link_category_code": ["A01"],
        }]
        occ, _ = activity_docs_to_occurrences(docs, "AA")
        self.assertEqual(occ[0].iati_identifier, "LIST-FORM")


if __name__ == "__main__":
    unittest.main()
