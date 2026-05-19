"""Offline tests for the OCR yield sub-step (stdlib unittest, no pytest).

No network. Uses the locally-installed tesseract binary (a local
subprocess, not egress). Fixtures are synthetic, built in memory; no text
is retained anywhere — assertions are on counts only, mirroring the
location-safety rule the production path enforces.

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import io
import logging
import sys
import unittest
from pathlib import Path
from unittest import mock

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

logging.getLogger("pypdf").setLevel(logging.CRITICAL)  # silence garbage-input noise

from iati_access_probe import ocr  # noqa: E402
from iati_access_probe.ocr import (  # noqa: E402
    OcrYieldEstimate,
    TesseractUnavailable,
    estimate_yield,
    ocr_char_count,
    select_subsample,
)


def _text_png(text: str) -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (720, 150), "white")
    d = ImageDraw.Draw(img)
    d.text((20, 45), text, fill="black", font=ImageFont.load_default(size=48))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _scanned_pdf(text: str) -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (720, 150), "white")
    ImageDraw.Draw(img).text(
        (20, 45), text, fill="black", font=ImageFont.load_default(size=48)
    )
    jb = io.BytesIO()
    img.save(jb, format="JPEG")
    jpg = jb.getvalue()

    def _st(d, data):
        return f"<< {d} /Length {len(data)} >>\nstream\n".encode() + data + b"\nendstream"

    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 720 150] "
        b"/Resources << /XObject << /Im1 5 0 R >> >> /Contents 4 0 R >>",
        _st("", b"q 720 0 0 150 0 0 cm /Im1 Do Q"),
        _st(f"/Type /XObject /Subtype /Image /Width {img.width} "
            f"/Height {img.height} /ColorSpace /DeviceRGB "
            f"/BitsPerComponent 8 /Filter /DCTDecode", jpg),
    ]
    out = bytearray(b"%PDF-1.4\n")
    offs = []
    for i, ob in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n".encode() + ob + b"\nendobj\n"
    x = len(out)
    n = len(objs) + 1
    out += f"xref\n0 {n}\n".encode() + b"0000000000 65535 f \n"
    for o in offs:
        out += f"{o:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {n} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF".encode()
    return bytes(out)


class TestTesseractResolution(unittest.TestCase):
    def test_missing_binary_fails_loudly_not_silently(self):
        with mock.patch.dict(ocr.os.environ, {}, clear=True), \
             mock.patch.object(ocr.shutil, "which", return_value=None), \
             mock.patch.object(ocr.os.path, "exists", return_value=False):
            with self.assertRaises(TesseractUnavailable):
                ocr.resolve_tesseract_cmd()


class TestOcrCharCount(unittest.TestCase):
    def test_image_recovers_text_as_count_only(self):
        n = ocr_char_count(_text_png("OCRTEST 12345"), "image")
        self.assertIsInstance(n, int)
        self.assertGreater(n, 5)  # lenient — OCR variance tolerated

    def test_scanned_pdf_via_pypdf_image_extraction(self):
        n = ocr_char_count(_scanned_pdf("SCANNED PAGE 6789"), "pdf")
        self.assertGreater(n, 5)

    def test_failure_is_isolated_to_zero(self):
        self.assertEqual(ocr_char_count(b"\x00\x01not a pdf", "pdf"), 0)
        self.assertEqual(ocr_char_count(b"whatever", "text"), 0)  # not a target


class TestSubsample(unittest.TestCase):
    POP = [f"http://h/{i}" for i in range(50)]

    def test_capped_and_deterministic(self):
        a = select_subsample(self.POP, target=10, seed="ocr-2026")
        b = select_subsample(self.POP, target=10, seed="ocr-2026")
        self.assertEqual(len(a.selected_urls), 10)
        self.assertEqual(a.selected_urls, b.selected_urls)  # reproducible
        self.assertTrue(a.is_capped)  # 50 > 10
        self.assertEqual(a.population, 50)

    def test_never_exceeds_target_however_large_population(self):
        big = [f"http://h/{i}" for i in range(9000)]
        s = select_subsample(big, target=150, seed="s")
        self.assertEqual(len(s.selected_urls), 150)  # (b) cannot drift to (c)

    def test_census_when_target_ge_population(self):
        s = select_subsample(self.POP[:30], target=150, seed="s")
        self.assertEqual(len(s.selected_urls), 30)
        self.assertFalse(s.is_capped)

    def test_empty_population(self):
        s = select_subsample([], target=150, seed="s")
        self.assertEqual(s.selected_urls, ())
        self.assertEqual(s.population, 0)


class TestYieldEstimate(unittest.TestCase):
    def test_arithmetic_and_counts_only(self):
        sub = select_subsample(
            ["http://h/a", "http://h/b", "http://h/c", "http://h/d"],
            target=4, seed="s",
        )
        counts = {"http://h/a": 0, "http://h/b": 100,
                  "http://h/c": 300, "http://h/d": 500}
        est = estimate_yield(counts, subsample=sub, usable_text_threshold=250)
        self.assertIsInstance(est, OcrYieldEstimate)
        self.assertEqual(est.n, 4)
        self.assertEqual(est.mean_chars, 225.0)
        self.assertEqual(est.median_chars, 200.0)
        self.assertEqual(est.share_reaching_usable, 0.5)  # c,d >= 250
        # Counts only — every value is numeric, nothing carries text.
        self.assertTrue(
            all(isinstance(v, int) for v in est.per_doc_char_counts.values())
        )

    def test_empty_subsample_is_zeroed_not_crash(self):
        sub = select_subsample([], target=150, seed="s")
        est = estimate_yield({}, subsample=sub, usable_text_threshold=250)
        self.assertEqual(est.n, 0)
        self.assertEqual(est.share_reaching_usable, 0.0)


if __name__ == "__main__":
    unittest.main()
