"""Offline tests for the live-draw entrypoint (stdlib unittest, no pytest).

No network, no live key. The Datastore transport is stubbed; the tests pin
(1) the env-var binding point — the variable is exactly IATI_API_KEY and a
missing key fails LOUDLY, never a silent empty draw — and (2) the
verify -> iter -> flatten -> seeded draw -> cache wiring.

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "src", ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import draw_sample  # noqa: E402
from draw_sample import ENV_KEY, get_api_key, run_draw  # noqa: E402
from iati_access_probe.datastore import DatastoreClient  # noqa: E402

_DOC = {
    "iati_identifier": "AA-ACT-1",
    "recipient_country_code": ["FJ"],
    "document_link_url": ["http://h/a.pdf", "http://h/b.pdf"],
    "document_link_format": ["application/pdf", "application/pdf"],
    "document_link_category_code": ["A01", "A02"],
}
_PAGE = {"response": {"docs": [_DOC], "numFound": 1}}


class _Resp:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._b = body if body is not None else _PAGE
        self.text = ""

    def json(self):
        return self._b


class _Transport:
    """Returns the same page for every call (verify + every iter page)."""

    def __init__(self):
        self.calls = []

    def __call__(self, url, headers, params):
        self.calls.append({"url": url, "headers": headers, "params": params})
        return _Resp()


def _client():
    return DatastoreClient("test-key", transport=_Transport(), min_interval_s=0)


class TestKeyBinding(unittest.TestCase):
    def test_env_var_name_is_exactly_iati_api_key(self):
        self.assertEqual(ENV_KEY, "IATI_API_KEY")  # must match .env.example

    def test_missing_key_fails_loudly(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.dict(draw_sample.os.environ, {}, clear=True):
                with self.assertRaises(SystemExit) as ctx:
                    get_api_key(Path(d) / ".env.local")  # absent file
        self.assertIn(ENV_KEY, str(ctx.exception))

    def test_reads_from_env_local_and_strips_quotes_and_comments(self):
        with tempfile.TemporaryDirectory() as d:
            envf = Path(d) / ".env.local"
            envf.write_text(
                '# a comment\n\nIATI_API_KEY = "abc123"  \nOTHER=x\n',
                encoding="utf-8",
            )
            with mock.patch.dict(draw_sample.os.environ, {}, clear=True):
                self.assertEqual(get_api_key(envf), "abc123")

    def test_process_env_takes_precedence(self):
        with tempfile.TemporaryDirectory() as d:
            envf = Path(d) / ".env.local"
            envf.write_text("IATI_API_KEY=from-file\n", encoding="utf-8")
            with mock.patch.dict(
                draw_sample.os.environ, {"IATI_API_KEY": "from-env"}, clear=True
            ):
                self.assertEqual(get_api_key(envf), "from-env")


class TestRunDrawWiring(unittest.TestCase):
    def test_verify_only_does_not_draw(self):
        with tempfile.TemporaryDirectory() as d, \
             contextlib.redirect_stdout(io.StringIO()):
            out = run_draw(
                _client(), countries=("FJ",), n=400, seed="s",
                cache_dir=Path(d), verify_only=True,
            )
            self.assertEqual(out, {})
            self.assertEqual(list(Path(d).iterdir()), [])  # nothing written

    def test_full_draw_flattens_and_caches(self):
        with tempfile.TemporaryDirectory() as d, \
             contextlib.redirect_stdout(io.StringIO()):
            out = run_draw(
                _client(), countries=("FJ",), n=400, seed="s",
                cache_dir=Path(d), verify_only=False,
            )
            self.assertEqual(out, {"FJ": 2})  # one activity doc -> 2 occurrences
            written = list(Path(d).rglob("*"))
            self.assertTrue(any(p.is_file() for p in written))  # sample cached


if __name__ == "__main__":
    unittest.main()
