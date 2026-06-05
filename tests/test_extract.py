#!/usr/bin/env python3
"""Regression test for the generic extractor.

Runs pdf2json over the bundled 48-page KUCCPS degrees PDF and checks the result
against the committed fixture ``examples/KUCCPSDEGREES.expected.json``.  Spell
correction is disabled so the test does not depend on the optional
``pyspellchecker`` package (on this all-caps document it is a no-op anyway).

Run directly (``python tests/test_extract.py``) or under pytest.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pdf2json  # noqa: E402

PDF = ROOT / "examples" / "KUCCPSDEGREES.pdf"
EXPECTED = ROOT / "examples" / "KUCCPSDEGREES.expected.json"


def _extract():
    sections = pdf2json.extract_sections(PDF, spell=False, quiet=True)
    return {
        "source": PDF.name,
        "section_count": len(sections),
        "total_rows": sum(len(s["rows"]) for s in sections),
        "sections": sections,
    }


def test_matches_fixture():
    got = _extract()
    want = json.loads(EXPECTED.read_text(encoding="utf-8"))
    assert got == want, "extractor output drifted from examples/KUCCPSDEGREES.expected.json"


def test_no_glued_or_truncated_values():
    """Guard the specific bugs this fixture was built to catch."""
    got = _extract()
    first = got["sections"][0]["rows"][0]
    # row-number must not be glued onto the code
    assert first["PROG CODE"] == "1105101", first["PROG CODE"]
    # long institution names must keep their trailing word
    names = {r["INSTITUTION NAME"] for s in got["sections"] for r in s["rows"]}
    assert "JOMO KENYATTA UNIVERSITY OF AGRICULTURE AND TECHNOLOGY" in names
    # no footer chrome leaked in as a row
    assert not any("Rights" in str(r) for s in got["sections"] for r in s["rows"])


if __name__ == "__main__":
    test_matches_fixture()
    test_no_glued_or_truncated_values()
    print("ok: extractor output matches fixture and bug guards pass")
