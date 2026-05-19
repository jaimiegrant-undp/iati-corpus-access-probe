"""Offline tests for the readability assessment (stdlib unittest, no pytest).

No network, no live key. Fixtures are synthetic and built in-memory — a
text-layer PDF, a scanned-image PDF, a near-empty PDF, a DOCX, an HTML
document, an HTML error page, an image, and garbage. Nothing is read from
or written to disk; matches the retention boundary the way the production
sink does.

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import io
import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from iati_access_probe.crawler import crawl_url  # noqa: E402
from iati_access_probe.models import CrawlPolicy, CrawlResult  # noqa: E402
from iati_access_probe.readability import (  # noqa: E402
    assess_body,
    mark_no_body,
    readability_sink,
)
from iati_access_probe.safety import HostRateLimiter, RobotsCache  # noqa: E402


# --- synthetic fixtures -----------------------------------------------------


def _make_pdf(objs: list[bytes]) -> bytes:
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, ob in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + ob + b"\nendobj\n"
    xref_pos = len(out)
    n = len(objs) + 1
    out += f"xref\n0 {n}\n".encode() + b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {n} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF".encode()
    return bytes(out)


def _stream(d: str, data: bytes) -> bytes:
    return f"<< {d} /Length {len(data)} >>\nstream\n".encode() + data + b"\nendstream"


_CATALOG = b"<< /Type /Catalog /Pages 2 0 R >>"
_PAGES = b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"

TEXT_PDF = _make_pdf([
    _CATALOG, _PAGES,
    b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
    b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
    _stream("", b"BT /F1 24 Tf 72 700 Td (Readable extracted document text "
                b"for the probe fixture sample paragraph) Tj ET"),
    b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
])

SCANNED_PDF = _make_pdf([
    _CATALOG, _PAGES,
    b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
    b"/Resources << /XObject << /Im1 5 0 R >> >> /Contents 4 0 R >>",
    _stream("", b"q 100 0 0 100 0 0 cm /Im1 Do Q"),
    _stream("/Type /XObject /Subtype /Image /Width 1 /Height 1 "
            "/ColorSpace /DeviceGray /BitsPerComponent 8", b"\x00"),
])

EMPTY_PDF = _make_pdf([
    _CATALOG, _PAGES,
    b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
    b"/Resources << >> /Contents 4 0 R >>",
    _stream("", b""),
])


def _docx_bytes(text: str) -> bytes:
    import docx

    d = docx.Document()
    d.add_paragraph(text)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


DOCX = _docx_bytes(
    "A readable DOCX fixture paragraph with plenty of characters so it "
    "comfortably clears any sane usable-text threshold for the probe."
)

HTML_DOC = (
    b"<!doctype html><html><head><title>t</title>"
    b"<script>var a=1;</script><style>.x{}</style></head><body>"
    b"<h1>Annual Report</h1><p>" + b"Substantive readable narrative. " * 12
    + b"</p></body></html>"
)
HTML_ERROR = b"<!doctype html><html><body>404 Not Found</body></html>"
PNG_1x1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010802000000907705"
    "3a0000000a4944415478da6360000000020001e221bc330000000049454e44ae426082"
)
GARBAGE = b"\x00\x01\x02\x03not a real document\xff\xfe" * 4


def _row(declared=None, status=200, resolved=True, barrier="none") -> CrawlResult:
    r = CrawlResult(url="http://h/x", crawl_ts="2026-05-19T00:00:00+00:00",
                     declared_format=declared)
    r.http_status = status
    r.resolved = resolved
    r.access_barrier = barrier
    return r


# --- format truth -----------------------------------------------------------


class TestFormatTruth(unittest.TestCase):
    def test_declared_pdf_truly_pdf_matches(self):
        r = _row(declared="application/pdf")
        assess_body(r, TEXT_PDF, usable_text_threshold=10)
        self.assertEqual(r.detected_format, "application/pdf")
        self.assertTrue(r.format_match)
        self.assertFalse(r.declared_pdf_actually_html)

    def test_declared_pdf_actually_html_is_flagged(self):
        r = _row(declared="application/pdf")
        assess_body(r, HTML_DOC, usable_text_threshold=10)
        self.assertFalse(r.format_match)
        self.assertTrue(r.declared_pdf_actually_html)

    def test_unknown_declared_format_leaves_match_none(self):
        r = _row(declared=None)
        assess_body(r, TEXT_PDF, usable_text_threshold=10)
        self.assertIsNone(r.format_match)
        self.assertIsNone(r.declared_pdf_actually_html)

    def test_detected_format_does_not_trust_header(self):
        # Server says PDF; bytes are HTML. Detection follows the bytes.
        r = _row(declared="application/pdf")
        r.content_type = "application/pdf"
        assess_body(r, HTML_ERROR, usable_text_threshold=10)
        self.assertEqual(r.detected_format, "text/html")


# --- extraction outcomes per format ----------------------------------------


class TestExtraction(unittest.TestCase):
    def test_text_layer_pdf(self):
        r = _row(declared="application/pdf")
        assess_body(r, TEXT_PDF, usable_text_threshold=10)
        self.assertEqual(r.extraction_outcome, "text_extracted")
        self.assertGreater(r.extracted_char_count, 10)

    def test_scanned_image_pdf_is_ocr_needed(self):
        r = _row(declared="application/pdf")
        assess_body(r, SCANNED_PDF, usable_text_threshold=10)
        self.assertEqual(r.extraction_outcome, "ocr_needed")
        self.assertEqual(r.extracted_char_count, 0)

    def test_near_empty_pdf_extracts_but_is_not_usable(self):
        r = _row(declared="application/pdf")
        assess_body(r, EMPTY_PDF, usable_text_threshold=250)
        self.assertEqual(r.extraction_outcome, "text_extracted")
        self.assertEqual(r.extracted_char_count, 0)
        self.assertFalse(r.usable_text)  # near-empty = a finding

    def test_docx(self):
        r = _row(declared="application/vnd.openxmlformats-officedocument."
                          "wordprocessingml.document")
        assess_body(r, DOCX, usable_text_threshold=10)
        self.assertEqual(r.extraction_outcome, "text_extracted")
        self.assertTrue(r.format_match)
        self.assertGreater(r.extracted_char_count, 10)

    def test_html_document_is_text_extracted(self):
        r = _row(declared="text/html")
        assess_body(r, HTML_DOC, usable_text_threshold=50)
        self.assertEqual(r.extraction_outcome, "text_extracted")

    def test_html_error_page_is_not_a_document(self):
        r = _row(declared="application/pdf", status=404, resolved=False)
        assess_body(r, HTML_ERROR, usable_text_threshold=250)
        self.assertEqual(r.extraction_outcome, "not_a_document")
        self.assertFalse(r.reachable_and_readable)

    def test_short_html_200_is_not_a_document(self):
        r = _row(declared="text/html")
        assess_body(r, HTML_ERROR, usable_text_threshold=250)  # status 200
        self.assertEqual(r.extraction_outcome, "not_a_document")

    def test_image_is_ocr_needed(self):
        r = _row(declared="image/png")
        assess_body(r, PNG_1x1, usable_text_threshold=10)
        self.assertEqual(r.extraction_outcome, "ocr_needed")

    def test_garbage_is_extraction_failed(self):
        r = _row(declared=None)
        assess_body(r, GARBAGE, usable_text_threshold=10)
        self.assertEqual(r.extraction_outcome, "extraction_failed")
        self.assertFalse(r.reachable_and_readable)


# --- the derived composites -------------------------------------------------


class TestComposites(unittest.TestCase):
    def test_usable_text_threshold_is_inclusive_boundary(self):
        r = _row(declared="text/html")
        assess_body(r, HTML_DOC, usable_text_threshold=10_000_000)
        self.assertFalse(r.usable_text)  # huge threshold -> not usable
        n = r.extracted_char_count
        r2 = _row(declared="text/html")
        assess_body(r2, HTML_DOC, usable_text_threshold=n)  # exactly n
        self.assertTrue(r2.usable_text)  # >= is inclusive

    def test_reachable_includes_ocr_needed(self):
        r = _row()
        assess_body(r, SCANNED_PDF, usable_text_threshold=10)
        self.assertTrue(r.reachable_and_readable)  # ocr_needed counts

    def test_reachable_false_when_barrier_present(self):
        r = _row(barrier="auth_required")
        assess_body(r, TEXT_PDF, usable_text_threshold=10)
        self.assertTrue(r.usable_text)
        self.assertFalse(r.reachable_and_readable)  # barrier blocks it

    def test_reachable_false_when_not_resolved(self):
        r = _row(status=404, resolved=False)
        assess_body(r, TEXT_PDF, usable_text_threshold=10)
        self.assertFalse(r.reachable_and_readable)

    def test_mark_no_body_finalises_unreachable(self):
        r = _row(barrier="non_public_host", resolved=False)
        mark_no_body(r)
        self.assertFalse(r.readability_pending)
        self.assertFalse(r.reachable_and_readable)
        self.assertFalse(r.usable_text)
        self.assertIsNone(r.extraction_outcome)


# --- retention boundary & D4 contract --------------------------------------


class TestRetentionAndSinkContract(unittest.TestCase):
    def test_no_document_bytes_or_text_on_the_row(self):
        r = _row(declared="application/pdf")
        assess_body(r, TEXT_PDF, usable_text_threshold=10)
        j = r.to_json()
        self.assertNotIn("body", j)
        # Only counts/booleans/identifiers — no value is the document text.
        for v in j.values():
            self.assertNotIsInstance(v, (bytes, bytearray))
        self.assertIsInstance(j["extracted_char_count"], int)

    def test_readability_sink_wires_through_the_crawler(self):
        """End-to-end of the D4->D5 contract: the sink assesses this URL's
        body in-process and the populated row is what the crawler returns."""

        class Resp:
            status_code = 200
            headers = {"Content-Type": "application/pdf"}

            def iter_bytes(self, n):
                yield TEXT_PDF

            def close(self):
                pass

        r = crawl_url(
            "http://pub.example/doc.pdf",
            policy=CrawlPolicy(per_host_interval_s=0.0),
            fetcher=lambda u, h, t: Resp(),
            resolver=lambda host: ["93.184.216.34"],
            robots=RobotsCache(lambda u: (404, "")),
            rate_limiter=HostRateLimiter(0.0, clock=lambda: 0.0,
                                         sleep=lambda s: None),
            declared_format="application/pdf",
            on_content=readability_sink(usable_text_threshold=10),
            now=lambda: "2026-05-19T00:00:00+00:00",
            monotonic=lambda: 0.0,
        )
        self.assertTrue(r.resolved)
        self.assertFalse(r.readability_pending)
        self.assertEqual(r.extraction_outcome, "text_extracted")
        self.assertTrue(r.reachable_and_readable)


if __name__ == "__main__":
    unittest.main()
