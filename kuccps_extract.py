#!/usr/bin/env python3
"""
Tuned extraction for KUCCPSDEGREES.pdf.

This document is a single table continued across 48 pages with a fixed column
layout. The header only appears on page 1 (and overlaps badly), so we hard-map
the known columns by their x-positions. The centred "BACHELOR OF ..." lines are
section titles; the rows beneath each become JSON sub-objects in the requested
"Heading: value" form.
"""

import json
import statistics
import sys
from pathlib import Path

import pdfplumber

HERE = Path(__file__).resolve().parent
# Default to the bundled example; override with: kuccps_extract.py <pdf> [out]
SRC = sys.argv[1] if len(sys.argv) > 1 else str(HERE / "examples" / "KUCCPSDEGREES.pdf")
OUT = sys.argv[2] if len(sys.argv) > 2 else str(Path(SRC).with_suffix(".json"))

# Fixed column boundaries (x0 ranges) measured from the PDF. A word is assigned
# to the column whose range contains its left edge.
COLUMNS = [
    ("PROG CODE",       60,  96),
    ("INSTITUTION NAME", 96, 250),
    ("PROGRAMME NAME",  250, 484),
    ("2018 CUTOFF",     484, 523),
    ("2019 CUTOFF",     523, 562),
    ("2020 CUTOFF",     562, 601),
    ("2021 CUTOFF",     601, 640),
    ("2022 CUTOFF",     640, 679),
    ("2023 CUTOFF",     679, 718),
    ("2024 CUTOFF",     718, 800),
]
HEADINGS = [c[0] for c in COLUMNS]


def clean(s):
    return " ".join(str(s).split()) if s else ""


def column_for(x0):
    for name, lo, hi in COLUMNS:
        if lo <= x0 < hi:
            return name
    return None


def group_lines(words):
    words = sorted(words, key=lambda w: (round(w["top"]), w["x0"]))
    lines, cur, ref = [], [words[0]], words[0]["top"]
    for w in words[1:]:
        if abs(w["top"] - ref) <= 3:
            cur.append(w)
        else:
            lines.append(sorted(cur, key=lambda x: x["x0"]))
            cur, ref = [w], w["top"]
    lines.append(sorted(cur, key=lambda x: x["x0"]))
    return lines


def is_title_line(line):
    """A section title (e.g. 'BACHELOR OF ARTS') has no PROG CODE token — i.e.
    no word starts in the leftmost (code) column band."""
    return not any(w["x0"] < 96 for w in line)


def split_code(token):
    """Leading token glues row-number + 7-digit programme code: split them."""
    digits = token
    if len(digits) > 7 and digits.isdigit():
        return digits[-7:]          # last 7 digits are the programme code
    return digits


def parse_data_line(line):
    """Map a data line's words into the fixed columns."""
    cells = {name: [] for name in HEADINGS}
    for i, w in enumerate(line):
        col = column_for(w["x0"])
        if col is None:
            continue
        text = w["text"]
        # the very first token in the PROG CODE column is row# + code merged
        if col == "PROG CODE" and not cells["PROG CODE"]:
            text = split_code(text)
        cells[col].append(text)
    return {name: clean(" ".join(cells[name])) for name in HEADINGS}


def main():
    tables = []
    section_title = None
    current_rows = None

    def flush():
        if section_title and current_rows:
            tables.append(
                {
                    "table_number": len(tables) + 1,
                    "title": section_title,
                    "headings": HEADINGS,
                    "rows": current_rows,
                }
            )

    with pdfplumber.open(SRC) as pdf:
        for page in pdf.pages:
            words = page.extract_words(use_text_flow=False)
            if not words:
                continue
            for line in group_lines(words):
                text = clean(" ".join(w["text"] for w in line))
                # skip the repeating page title and the page-1 column header
                if "DEGREE PROGRAMME CUT OFFS" in text:
                    continue
                if text.startswith("#") and "PROG" in text:
                    continue
                if is_title_line(line):
                    flush()
                    section_title = text
                    current_rows = []
                else:
                    if current_rows is None:
                        current_rows = []
                        section_title = section_title or "(untitled)"
                    current_rows.append(parse_data_line(line))
        flush()

    result = {
        "source": SRC,
        "table_count": len(tables),
        "total_rows": sum(len(t["rows"]) for t in tables),
        "tables": tables,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"Extracted {len(tables)} sections, {result['total_rows']} rows -> {OUT}")


if __name__ == "__main__":
    main()
