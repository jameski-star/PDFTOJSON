#!/usr/bin/env python3
"""
pdf2json — extract every table from a PDF into a structured .json file.

For each table found:
  - the first row is treated as the column headings;
  - every following row becomes a JSON sub-object where each heading is a key
    and the cell beneath it is the value
    (e.g. heading "Universities" + a later row "Kenyatta University"
     -> "Universities": "Kenyatta University");
  - the headings are therefore repeated for every row sub-object;
  - any text sitting just above the table is captured as the table "title".

Two detection paths are used automatically per page:
  - ruled tables (with drawn grid lines) are read directly and accurately;
  - borderless tables are reconstructed by clustering word positions into
    rows and columns using whitespace corridors.

Usage:
    pdf2json                         # no args -> interactively ask for a file
    pdf2json input.pdf               # writes input.json next to the PDF
    pdf2json input.pdf out.json      # explicit output path
    pdf2json a.pdf b.pdf c.pdf       # convert several PDFs in one run
    pdf2json "folder/*.pdf"          # globs are expanded too
    pdf2json -o out_dir *.pdf        # write all outputs into out_dir/

Options:
    -o, --outdir DIR    write every .json into DIR (created if needed)
    -q, --quiet         only print errors
    -h, --help          show this help
"""

import glob
import json
import statistics
import sys
from pathlib import Path

try:
    import pdfplumber
except ImportError:
    sys.stderr.write(
        "error: pdfplumber is not installed.\n"
        "       Install it with:  pip install pdfplumber\n"
        "       (or run ./install.sh to set up the bundled virtualenv)\n"
    )
    sys.exit(2)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def clean(value):
    """Normalise a cell: collapse newlines/whitespace, return '' for None."""
    if value is None:
        return ""
    return " ".join(str(value).split())


def make_headings(header_cells):
    """Turn the first table row into a list of unique, non-empty headings."""
    headings = []
    seen = {}
    for index, cell in enumerate(header_cells):
        name = clean(cell) or f"column_{index + 1}"
        if name in seen:
            seen[name] += 1
            name = f"{name} ({seen[name]})"
        else:
            seen[name] = 1
        headings.append(name)
    return headings


def rows_from_grid(grid):
    """grid[0] = headings, grid[1:] = data rows -> (headings, [row dicts])."""
    headings = make_headings(grid[0])
    rows = []
    for raw in grid[1:]:
        obj = {}
        for i, heading in enumerate(headings):
            obj[heading] = clean(raw[i]) if i < len(raw) else ""
        rows.append(obj)
    return headings, rows


# ---------------------------------------------------------------------------
# ruled tables (drawn grid lines) — pdfplumber reads these accurately
# ---------------------------------------------------------------------------

def ruled_tables(page):
    settings = {"vertical_strategy": "lines", "horizontal_strategy": "lines"}
    results = []
    for table in page.find_tables(table_settings=settings):
        data = [r for r in table.extract() if any(clean(c) for c in r)]
        if len(data) < 2:
            continue
        results.append({"bbox": table.bbox, "grid": data})
    return results


# ---------------------------------------------------------------------------
# borderless tables — reconstruct rows/columns from word positions
# ---------------------------------------------------------------------------

def group_lines(words):
    """Cluster words into text lines by vertical position. Returns list of
    lines, each a list of words sorted left-to-right."""
    if not words:
        return []
    heights = [w["bottom"] - w["top"] for w in words]
    row_tol = max(2.0, statistics.median(heights) * 0.6)

    words = sorted(words, key=lambda w: (w["top"], w["x0"]))
    lines = []
    current = [words[0]]
    ref_top = words[0]["top"]
    for w in words[1:]:
        if abs(w["top"] - ref_top) <= row_tol:
            current.append(w)
        else:
            lines.append(sorted(current, key=lambda x: x["x0"]))
            current = [w]
            ref_top = w["top"]
    lines.append(sorted(current, key=lambda x: x["x0"]))
    return lines


def split_blocks(lines):
    """Split lines into blocks separated by unusually large vertical gaps."""
    if len(lines) <= 1:
        return [lines] if lines else []

    tops = [min(w["top"] for w in ln) for ln in lines]
    gaps = [tops[i + 1] - tops[i] for i in range(len(tops) - 1)]
    typical = statistics.median(gaps) if gaps else 0
    threshold = max(typical * 1.8, typical + 6)

    blocks = []
    current = [lines[0]]
    for i, gap in enumerate(gaps):
        if gap > threshold:
            blocks.append(current)
            current = [lines[i + 1]]
        else:
            current.append(lines[i + 1])
    blocks.append(current)
    return blocks


def detect_columns(lines):
    """Find column bands as x-ranges separated by whitespace corridors that
    are empty in (almost) all lines. Returns a sorted list of (left, right)."""
    intervals = []  # per-line list of (x0, x1) word boxes
    for ln in lines:
        intervals.append([(w["x0"], w["x1"]) for w in ln])

    all_edges = sorted({x for ln in intervals for box in ln for x in box})
    if len(all_edges) < 2:
        left = min(w["x0"] for ln in lines for w in ln)
        right = max(w["x1"] for ln in lines for w in ln)
        return [(left, right)]

    n_lines = len(lines)
    # a slab between two adjacent edges is a corridor if almost no line has
    # content crossing its midpoint
    corridor_limit = max(0, int(n_lines * 0.15))

    bands = []
    band_start = all_edges[0]
    prev_edge = all_edges[0]
    for edge in all_edges[1:]:
        mid = (prev_edge + edge) / 2.0
        covering = sum(
            1 for ln in intervals if any(x0 <= mid <= x1 for x0, x1 in ln)
        )
        if covering <= corridor_limit:
            # corridor: close the current band (if it held content)
            if band_start < prev_edge:
                bands.append((band_start, prev_edge))
            band_start = edge
        prev_edge = edge
    if band_start < prev_edge:
        bands.append((band_start, prev_edge))

    return bands or [(all_edges[0], all_edges[-1])]


def line_spans_columns(line, bands):
    """True if any single word in the line crosses a column corridor — the
    mark of a title/caption rather than a data row."""
    if len(bands) < 2:
        return False
    separators = [(bands[i][1] + bands[i + 1][0]) / 2.0 for i in range(len(bands) - 1)]
    for w in line:
        for sep in separators:
            if w["x0"] < sep < w["x1"]:
                return True
    return False


def line_to_cells(line, bands):
    """Distribute a line's words into column bands by word center."""
    cells = [[] for _ in bands]
    for w in line:
        center = (w["x0"] + w["x1"]) / 2.0
        idx = min(range(len(bands)), key=lambda i: _band_distance(bands[i], center))
        cells[idx].append(w["text"])
    return [clean(" ".join(c)) for c in cells]


def _band_distance(band, x):
    left, right = band
    if x < left:
        return left - x
    if x > right:
        return x - right
    return 0.0


def line_text(line):
    return clean(" ".join(w["text"] for w in line))


def line_height(line):
    return statistics.median([w["bottom"] - w["top"] for w in line])


def borderless_tables(page):
    """Reconstruct borderless tables from word clustering."""
    words = page.extract_words(use_text_flow=False)
    if not words:
        return []

    lines = group_lines(words)
    blocks = split_blocks(lines)

    # typical body font height across the page — titles tend to be larger
    body_height = statistics.median([line_height(ln) for ln in lines])

    results = []
    pending_title = ""  # a single-line text block becomes the next table's title

    for block in blocks:
        bands = detect_columns(block)

        # peel leading title/caption lines. A line is a title when it is set in
        # a noticeably larger font, spans a column corridor, or lands entirely
        # in one column while the table has several.
        title_parts = []
        body = list(block)
        while body and len(bands) >= 2:
            first = body[0]
            occupied = sum(1 for cell in line_to_cells(first, bands) if cell)
            bigger_font = line_height(first) > body_height * 1.15
            if bigger_font or line_spans_columns(first, bands) or occupied <= 1:
                title_parts.append(line_text(first))
                body = body[1:]
            else:
                break

        is_table = len(bands) >= 2 and len(body) >= 2

        if not is_table:
            # remember short text (likely a heading sitting above a table)
            text = " ".join(title_parts + [line_text(ln) for ln in body]).strip()
            pending_title = text
            continue

        # re-detect columns on the body alone: a peeled title that was spread
        # across the page width would otherwise distort the column bands.
        bands = detect_columns(body)
        grid = [line_to_cells(ln, bands) for ln in body]
        headings, rows = rows_from_grid(grid)

        title = " ".join(p for p in [pending_title] + title_parts if p).strip()
        pending_title = ""

        top = min(w["top"] for ln in block for w in ln)
        bottom = max(w["bottom"] for ln in block for w in ln)
        results.append(
            {
                "bbox": (0, top, page.width, bottom),
                "grid": None,
                "title": title,
                "headings": headings,
                "rows": rows,
            }
        )
    return results


# ---------------------------------------------------------------------------
# title for ruled tables — nearest text line above the table
# ---------------------------------------------------------------------------

def find_title_above(page, table_bbox, used_bands):
    _, top, _, _ = table_bbox
    candidates = []
    for word in page.extract_words(use_text_flow=True):
        if word["bottom"] > top:
            continue
        if any(bt <= word["top"] <= bb for bt, bb in used_bands):
            continue
        candidates.append(word)
    if not candidates:
        return ""
    nearest = max(w["bottom"] for w in candidates)
    line = [w for w in candidates if nearest - w["bottom"] <= 3]
    line.sort(key=lambda w: w["x0"])
    return clean(" ".join(w["text"] for w in line))


# ---------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------

def extract_tables(pdf_path, on_page=None):
    out = []
    counter = 0
    with pdfplumber.open(pdf_path) as pdf:
        total = len(pdf.pages)
        for page_number, page in enumerate(pdf.pages, start=1):
            if on_page:
                on_page(page_number, total)
            ruled = ruled_tables(page)

            if ruled:
                used_bands = [(t["bbox"][1], t["bbox"][3]) for t in ruled]
                for t in ruled:
                    counter += 1
                    headings, rows = rows_from_grid(t["grid"])
                    out.append(
                        {
                            "table_number": counter,
                            "page": page_number,
                            "title": find_title_above(page, t["bbox"], used_bands),
                            "headings": headings,
                            "rows": rows,
                        }
                    )
            else:
                for t in borderless_tables(page):
                    counter += 1
                    out.append(
                        {
                            "table_number": counter,
                            "page": page_number,
                            "title": t["title"],
                            "headings": t["headings"],
                            "rows": t["rows"],
                        }
                    )
    return out


def convert_one(pdf_path, out_path, quiet=False):
    """Convert a single PDF. Returns the output Path on success, None on error."""
    pdf_path = Path(pdf_path).expanduser()
    if not pdf_path.is_file():
        sys.stderr.write(f"error: file not found: {pdf_path}\n")
        return None
    if pdf_path.suffix.lower() != ".pdf":
        sys.stderr.write(f"warning: {pdf_path.name} does not look like a PDF — trying anyway\n")

    def progress(page_no, total):
        if not quiet:
            sys.stderr.write(f"\r  {pdf_path.name}: page {page_no}/{total}")
            sys.stderr.flush()

    try:
        tables = extract_tables(pdf_path, on_page=progress)
    except Exception as exc:  # pdfplumber raises a variety of errors on bad PDFs
        if not quiet:
            sys.stderr.write("\n")
        sys.stderr.write(f"error: failed to read {pdf_path.name}: {exc}\n")
        return None

    if not quiet:
        sys.stderr.write("\r" + " " * 60 + "\r")  # clear the progress line

    result = {"source": pdf_path.name, "table_count": len(tables), "tables": tables}
    out_path = Path(out_path).expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    if not quiet:
        rows = sum(len(t["rows"]) for t in tables)
        print(f"{pdf_path.name}: {len(tables)} table(s), {rows} row(s) -> {out_path}")
    return out_path


# ---------------------------------------------------------------------------
# command line
# ---------------------------------------------------------------------------

def expand_inputs(raw_args):
    """Expand globs and keep order; the shell usually expands, but quoted
    patterns and Windows reach us unexpanded."""
    paths = []
    for arg in raw_args:
        matches = glob.glob(str(Path(arg).expanduser()))
        if matches:
            paths.extend(sorted(matches))
        else:
            paths.append(arg)
    return paths


def prompt_for_file():
    """No file given: ask for one interactively (supports tab-less typing)."""
    try:
        answer = input("Enter the path to a PDF file (or blank to cancel): ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None
    answer = answer.strip().strip('"').strip("'")
    return answer or None


def main(argv):
    args = argv[1:]
    if any(a in ("-h", "--help") for a in args):
        print(__doc__.strip())
        return 0

    quiet = False
    outdir = None
    inputs = []
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-q", "--quiet"):
            quiet = True
        elif a in ("-o", "--outdir"):
            i += 1
            if i >= len(args):
                sys.stderr.write("error: -o/--outdir needs a directory\n")
                return 1
            outdir = Path(args[i]).expanduser()
        else:
            inputs.append(a)
        i += 1

    inputs = expand_inputs(inputs)

    # No input given -> interactively ask for a file.
    if not inputs:
        picked = prompt_for_file()
        if not picked:
            print("Nothing to do.")
            return 1
        inputs = expand_inputs([picked])

    # Two args with the second being an explicit .json output (and no -o):
    explicit_out = None
    if outdir is None and len(inputs) == 2 and inputs[1].lower().endswith(".json"):
        explicit_out = Path(inputs[1]).expanduser()
        inputs = inputs[:1]

    ok = 0
    for pdf in inputs:
        if explicit_out is not None:
            out_path = explicit_out
        elif outdir is not None:
            out_path = outdir / (Path(pdf).stem + ".json")
        else:
            out_path = Path(pdf).expanduser().with_suffix(".json")
        if convert_one(pdf, out_path, quiet=quiet):
            ok += 1

    failed = len(inputs) - ok
    if len(inputs) > 1:
        print(f"\nDone: {ok} succeeded, {failed} failed.")
    return 0 if failed == 0 else 1


def main_cli():
    """Zero-argument entry point used by the installed `pdf2json` command."""
    sys.exit(main(sys.argv))


if __name__ == "__main__":
    main_cli()
