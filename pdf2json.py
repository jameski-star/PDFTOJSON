#!/usr/bin/env python3
"""
pdf2json — extract tables from a PDF into structured JSON, grouped into sections.

The extractor understands three kinds of line and keeps them separate:

  * column labels   — the bold header row (e.g. "PROG CODE", "INSTITUTION NAME").
                      Column labels are detected by their **bold font** and are
                      carried forward to later pages that repeat the same columns
                      but don't reprint the header.
  * section heading — a centred title that isn't a row (e.g. "BACHELOR OF ARTS").
                      It becomes its own "heading" field, never mixed into a row.
  * data row        — every other row, emitted as a sub-object mapping each
                      label to the cell beneath it.

Output shape:

  {
    "source": "doc.pdf",
    "section_count": N,
    "total_rows": M,
    "sections": [
      { "heading": "BACHELOR OF ARTS", "page": 1,
        "labels": ["PROG CODE", "INSTITUTION NAME", ...],
        "rows": [ { "PROG CODE": "1105101", "INSTITUTION NAME": "CHUKA UNIVERSITY", ... } ] }
    ]
  }

Words are read in the PDF's character-stream order (use_text_flow=True), which
untangles overlapping headers that would otherwise come out garbled
(e.g. "CODE"+"INSTITUTION" interleaving into "COIDNESTITUTION").

Usage:
    pdf2json                         # no args -> interactively ask for a file
    pdf2json input.pdf               # writes input.json next to the PDF
    pdf2json input.pdf out.json      # explicit output path
    pdf2json a.pdf b.pdf c.pdf       # convert several PDFs in one run
    pdf2json "folder/*.pdf"          # globs are expanded too
    pdf2json -o out_dir *.pdf        # write all outputs into out_dir/

Options:
    -o, --outdir DIR    write every .json into DIR (created if needed)
    --no-spell          disable the dictionary word-correction pass
    -q, --quiet         only print errors
    -h, --help          show this help
"""

import glob
import json
import statistics
import sys
from collections import defaultdict
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

from corrections import apply_corrections


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def clean(value):
    """Normalise a cell: collapse newlines/whitespace, return '' for None."""
    if value is None:
        return ""
    return " ".join(str(value).split())


def make_headings(header_cells):
    """Turn a list of cells into unique, non-empty labels."""
    headings, seen = [], {}
    for index, cell in enumerate(header_cells):
        name = clean(cell) or f"column_{index + 1}"
        if name in seen:
            seen[name] += 1
            name = f"{name} ({seen[name]})"
        else:
            seen[name] = 1
        headings.append(name)
    return headings


def is_bold(word):
    return "bold" in str(word.get("fontname", "")).lower()


def line_text(line):
    return clean(" ".join(w["text"] for w in line))


def line_height(line):
    return statistics.median([w["bottom"] - w["top"] for w in line])


def norm(text):
    return clean(text).upper()


def chrome_key(text):
    """Normalised key for spotting running headers/footers. Digits are collapsed
    so variable-length page numbers ("Page 1", "Page 15") produce the same key."""
    import re
    return re.sub(r"#+", "#", "".join("#" if ch.isdigit() else ch for ch in norm(text)))


# ---------------------------------------------------------------------------
# line grouping
# ---------------------------------------------------------------------------

def group_lines(words):
    """Cluster words into text lines by vertical position; each line is a list
    of words sorted left-to-right."""
    if not words:
        return []
    heights = [w["bottom"] - w["top"] for w in words]
    row_tol = max(2.0, statistics.median(heights) * 0.6)

    words = sorted(words, key=lambda w: (w["top"], w["x0"]))
    lines, current, ref_top = [], [words[0]], words[0]["top"]
    for w in words[1:]:
        if abs(w["top"] - ref_top) <= row_tol:
            current.append(w)
        else:
            lines.append(sorted(current, key=lambda x: x["x0"]))
            current, ref_top = [w], w["top"]
    lines.append(sorted(current, key=lambda x: x["x0"]))
    return lines


# ---------------------------------------------------------------------------
# column bands (from whitespace corridors in the data rows)
# ---------------------------------------------------------------------------

def _merge_nearby_bands(bands, max_gap=5.0):
    """Merge adjacent bands whose gap ≤ *max_gap* into a single band.

    A gap ≤ 2 pt is always intra-column (adjacent words in the same cell).
    For 2–5 pt gaps the merge only happens when at least one band is a sliver
    — this keeps two full-width columns from collapsing together."""
    if len(bands) <= 1:
        return bands
    merged = [list(bands[0])]
    MIN_W = 12.0
    for left, right in bands[1:]:
        prev_left, prev_right = merged[-1]
        gap = left - prev_right
        prev_w = prev_right - prev_left
        cur_w = right - left
        if gap <= 2.0:
            # sub-character gap — always the same column
            merged[-1][1] = right
        elif gap <= max_gap and (prev_w < MIN_W or cur_w < MIN_W):
            merged[-1][1] = right
        else:
            merged.append([left, right])
    return [(l, r) for l, r in merged]


def detect_columns(lines):
    """Find column bands as x-ranges separated by whitespace corridors that are
    empty in (almost) all lines. Returns a sorted list of (left, right).

    The caller should pre-filter lines that don't represent data rows
    (section titles, headers, footers, etc.)."""
    if not lines:
        return []
    intervals = [[(w["x0"], w["x1"]) for w in ln] for ln in lines]
    all_edges = sorted({x for ln in intervals for box in ln for x in box})
    if len(all_edges) < 2:
        left = min(w["x0"] for ln in lines for w in ln)
        right = max(w["x1"] for ln in lines for w in ln)
        return [(left, right)]

    n_lines = len(lines)
    # Allow up to 25 % of lines to cover a corridor before we consider it
    # "closed".  Long cell values occasionally protrude into the gap
    # between columns (e.g. programme names reaching into the cutoff area).
    corridor_limit = max(0, int(n_lines * 0.25))

    bands = []
    band_start = prev_edge = all_edges[0]
    for edge in all_edges[1:]:
        mid = (prev_edge + edge) / 2.0
        covering = sum(1 for ln in intervals if any(x0 <= mid <= x1 for x0, x1 in ln))
        if covering <= corridor_limit:
            if band_start < prev_edge:
                bands.append((band_start, prev_edge))
            band_start = edge
        prev_edge = edge
    if band_start < prev_edge:
        bands.append((band_start, prev_edge))
    bands = bands or [(all_edges[0], all_edges[-1])]

    # Merge sliver bands that are artefacts of tiny intra-word gaps.
    # A very narrow band (e.g. a lone "-" for a missing cell value) is
    # absorbed by its *closer* neighbour, not always the left one.
    MIN_BAND_WIDTH = 12.0
    merged = []
    i = 0
    while i < len(bands):
        left, right = bands[i]
        width = right - left
        if width < MIN_BAND_WIDTH:
            # find the closer neighbour
            gap_left = left - merged[-1][1] if merged else float("inf")
            gap_right = (bands[i + 1][0] - right) if i + 1 < len(bands) else float("inf")
            if gap_left <= gap_right and merged:
                merged[-1] = (merged[-1][0], right)
            elif i + 1 < len(bands):
                # absorb into the right neighbour
                bands[i + 1] = (left, bands[i + 1][1])
            else:
                merged.append((left, right))
        else:
            merged.append((left, right))
        i += 1
    return _merge_nearby_bands(merged, max_gap=5.0)


def _band_distance(band, x):
    left, right = band
    if x < left:
        return left - x
    if x > right:
        return x - right
    return 0.0


def _band_of(word, bands):
    """Index of the band a word's centre belongs to (nearest if outside all)."""
    center = (word["x0"] + word["x1"]) / 2.0
    return min(range(len(bands)), key=lambda i: _band_distance(bands[i], center))


def line_to_cells(line, bands):
    """Distribute a line's words into column bands by word centre."""
    cells = [[] for _ in bands]
    for w in line:
        cells[_band_of(w, bands)].append(w["text"])
    return [clean(" ".join(c)) for c in cells]


# ---------------------------------------------------------------------------
# classifying a line: label row / heading / data row
# ---------------------------------------------------------------------------

def cluster_count(line, gap=15.0):
    """Number of horizontal word-clusters (columns) in a line."""
    if not line:
        return 0
    clusters, prev_x1 = 1, line[0]["x1"]
    for w in line[1:]:
        if w["x0"] - prev_x1 > gap:
            clusters += 1
        prev_x1 = max(prev_x1, w["x1"])
    return clusters


def is_label_row(line, page_width=None):
    """A column-label row: mostly bold and spread across several columns.

    Uses two complementary signals because overlapping header words (a PDF
    quirk) can collapse the visible cluster count below the natural number of
    columns.  Either:
    - ≥ 4 visible clusters, OR
    - many bold words (≥ 8) with high bold ratio, which is overwhelmingly a
      header row even when words overlap in x-space (e.g. ``PROG CODE`` +
      ``INSTITUTION NAME`` interleaving).

    The line must span a significant portion of the page width — this excludes
    short centred section titles (e.g. "BACHELOR OF SCIENCE IN …") that happen
    to be bold."""
    if len(line) < 2:
        return False
    bold = sum(1 for w in line if is_bold(w))
    bold_ratio = bold / len(line)
    if bold_ratio < 0.6:
        return False

    line_x0 = min(w["x0"] for w in line)
    line_x1 = max(w["x1"] for w in line)
    line_width = line_x1 - line_x0

    # A header row must span most of the page (or we must not know the width).
    if page_width and line_width / page_width < 0.45:
        return False

    # Many bold words → almost certainly a header row.
    if bold >= 8:
        return True
    # Otherwise require the line to be visibly spread across columns.
    clusters = cluster_count(line)
    if clusters >= 4:
        return True
    # Fewer clusters but spread across most of the page width → header.
    if page_width and clusters >= 2:
        if line_width / page_width >= 0.5:
            return True
    return False


def is_heading(line, bands, page_width=None):
    """A section title: centred text that isn't a data row.

    Uses multiple signals:
    1. No word sits in the leftmost column band (data rows always start there).
    2. If the line spans < 40 % of the page width and is bold or starts well
       right of the left margin, it's likely a section title."""
    if not bands or len(bands) < 2:
        return False
    # Primary signal: nothing in the first column band.
    if not any(_band_of(w, bands) == 0 for w in line):
        return True
    # Fallback for long titles that extend into the first band:
    # short, centred, bold lines are section headings.
    if page_width:
        line_x0 = min(w["x0"] for w in line)
        line_x1 = max(w["x1"] for w in line)
        line_width = line_x1 - line_x0
        # Centred short text (≤ 40 % of page) that starts well right of margin.
        if line_width / page_width <= 0.45 and line_x0 > page_width * 0.08:
            bold = sum(1 for w in line if is_bold(w))
            if bold / len(line) >= 0.5:
                return True
    return False


def labels_for_bands(header_words, bands):
    """Map bold header words onto the column bands.

    Uses each word's **left edge** (x0) rather than its centre, so overlapping
    header groups (e.g. ``PROG CODE`` interleaved with ``INSTITUTION NAME``)
    don't cross-assign to the wrong band.

    After x0 assignment, applies a reading-order correction: if a band received
    more words than expected, excess words spill forward to the next band(s).
    This fixes cases where header words (bold, slightly different font metrics)
    don't line up exactly with the data-value column bands."""
    if not bands or not header_words:
        return []
    bands = list(bands)
    buckets = [[] for _ in bands]

    # --- pass 1: assign by left edge ---
    for w in header_words:
        x0 = w["x0"]
        best = min(range(len(bands)), key=lambda i: _band_distance(bands[i], x0))
        buckets[best].append((w["x0"], w["text"]))

    # --- pass 2: intra-bucket split by reading-order gap ---
    # When a bucket contains words from two adjacent columns (header
    # positions drift relative to data-value band edges), find the largest
    # horizontal gap between consecutive words and split the bucket there.
    # e.g.  bucket = [(484,"2018"), (497,"CUTOFF"), (523,"2019")]
    #       largest gap = 523-497 = 26 → split → "2019" moves to next bucket.
    for i in range(len(buckets) - 1):
        if len(buckets[i]) <= 2:
            continue
        buckets[i].sort(key=lambda t: t[0])
        # find the largest gap between consecutive words in this bucket
        best_gap, best_j = 0, 0
        for j in range(len(buckets[i]) - 1):
            gap = buckets[i][j + 1][0] - buckets[i][j][0]
            if gap > best_gap:
                best_gap = gap
                best_j = j
        if best_gap > 20:  # pt — only split between distinct columns
            spill = buckets[i][best_j + 1:]
            buckets[i] = buckets[i][:best_j + 1]
            buckets[i + 1] = spill + buckets[i + 1]
            buckets[i + 1].sort(key=lambda t: t[0])

    cells = []
    for b in buckets:
        b.sort(key=lambda t: t[0])
        cells.append(clean(" ".join(t for _, t in b)))
    return make_headings(cells)


# ---------------------------------------------------------------------------
# ruled tables (drawn grid lines) — pdfplumber reads these accurately
# ---------------------------------------------------------------------------

def ruled_tables(page):
    """Extract tables defined by drawn grid lines.

    Only runs when the page contains explicit vector-line objects (page.lines
    is non-empty).  Many PDFs have zero drawn lines but pdfplumber's ``"lines"``
    strategy still returns tables built from word-edge rectangles — those are
    false positives for *ruled* tables, so we skip them here and let the
    borderless pipeline handle them."""
    if not page.lines:
        return []
    settings = {"vertical_strategy": "lines", "horizontal_strategy": "lines"}
    results = []
    for table in page.find_tables(table_settings=settings):
        data = [r for r in table.extract() if any(clean(c) for c in r)]
        if len(data) < 2:
            continue
        results.append({"bbox": table.bbox, "grid": data})
    return results


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


def section_from_grid(title, page_number, grid):
    """Turn a ruled-table grid into a section (first row = labels)."""
    labels = make_headings(grid[0])
    rows = []
    for raw in grid[1:]:
        rows.append({labels[i]: clean(raw[i]) if i < len(raw) else ""
                     for i in range(len(labels))})
    return {"heading": title, "page": page_number, "labels": labels, "rows": rows}


# ---------------------------------------------------------------------------
# orchestration: read every page, then build sections with cross-page state
# ---------------------------------------------------------------------------

def _read_pages(pdf, on_page=None):
    """First pass: per page, decide ruled vs borderless and cache the content."""
    pages = []
    total = len(pdf.pages)
    for page_number, page in enumerate(pdf.pages, start=1):
        if on_page:
            on_page(page_number, total)
        ruled = ruled_tables(page)
        if ruled:
            bands = [(t["bbox"][1], t["bbox"][3]) for t in ruled]
            pages.append({
                "page": page_number, "kind": "ruled",
                "width": page.width,
                "sections": [section_from_grid(find_title_above(page, t["bbox"], bands),
                                               page_number, t["grid"]) for t in ruled],
            })
        else:
            words = page.extract_words(use_text_flow=True, extra_attrs=["fontname", "size"])
            pages.append({"page": page_number, "kind": "border",
                          "width": page.width,
                          "lines": group_lines(words) if words else []})
    return pages


def _running_chrome(pages):
    """Line texts that repeat on many pages are running headers/footers."""
    seen = defaultdict(set)
    border_pages = 0
    for pd in pages:
        if pd["kind"] != "border":
            continue
        border_pages += 1
        for ln in pd["lines"]:
            seen[chrome_key(line_text(ln))].add(pd["page"])
    threshold = max(3, int((border_pages or 1) * 0.4))
    return {text for text, pgs in seen.items() if len(pgs) >= threshold}


def _border_contexts(pages, chrome):
    """Split borderless lines into contexts.

    A **header-based** context begins at a bold label row and carries its columns
    forward across pages until the next label row (this is what lets a 48-page
    table keep its page-1 header). Consecutive label rows are merged (handles a
    two-line year + CUTOFF header).

    Lines with **no** bold header to carry are kept in **per-page** contexts, so
    a header-less document is never lumped into one giant column detection."""
    contexts, current = [], None

    def start(header_line, page, width):
        ctx = {"header": list(header_line) if header_line else [],
               "lines": [], "header_based": bool(header_line),
               "page": page, "width": width}
        contexts.append(ctx)
        return ctx

    prev_was_label = False
    for pd in pages:
        if pd["kind"] != "border":
            prev_was_label = False
            continue
        pw = pd.get("width")
        for ln in pd["lines"]:
            if chrome_key(line_text(ln)) in chrome:
                continue
            if is_label_row(ln, page_width=pw):
                if prev_was_label and current is not None and current["header_based"]:
                    current["header"].extend(ln)          # merge multi-line header
                else:
                    current = start(ln, pd["page"], pw)
                prev_was_label = True
            else:
                # carry only under a real header; otherwise stay per-page
                if current is None or (not current["header_based"]
                                       and current["page"] != pd["page"]):
                    current = start(None, pd["page"], pw)
                current["lines"].append((pd["page"], ln))
                prev_was_label = False
    return contexts


def _sections_from_context(ctx):
    """Build sections for one header context: compute bands from its data lines,
    name them with the bold header, then split into headings + rows."""
    data_lines = [ln for _, ln in ctx["lines"]]
    if not data_lines:
        return []

    # Column detection sample: exclude short centred lines (section titles
    # like "BACHELOR OF ARTS") that don't have the multi-word column structure
    # of real data rows.  This keeps the column detector from creating phantom
    # bands from centred heading text.
    data_sample = [ln for ln in data_lines if len(ln) > 3]
    if not data_sample:
        data_sample = data_lines

    sample = data_sample
    if len(sample) > 200:
        step = len(sample) // 200
        sample = sample[::step]
    bands = detect_columns(sample)
    labels = labels_for_bands(ctx["header"], bands) if len(bands) >= 2 else \
        make_headings(["column_1"]) if bands else []
    page_width = ctx.get("width")

    sections, section = [], None
    for page, ln in ctx["lines"]:
        if is_heading(ln, bands, page_width=page_width):
            section = {"heading": line_text(ln), "page": page,
                       "labels": labels, "rows": []}
            sections.append(section)
        else:
            if section is None:
                section = {"heading": "", "page": page, "labels": labels, "rows": []}
                sections.append(section)
            cells = line_to_cells(ln, bands)
            row = {}
            for i in range(len(bands)):
                key = labels[i] if i < len(labels) else f"column_{i + 1}"
                row[key] = cells[i] if i < len(cells) else ""
            section["rows"].append(row)
    return sections


def extract_sections(pdf_path, spell=True, quiet=False, on_page=None):
    with pdfplumber.open(pdf_path) as pdf:
        pages = _read_pages(pdf, on_page=on_page)

    chrome = _running_chrome(pages)
    sections = []
    for pd in pages:
        if pd["kind"] == "ruled":
            sections.extend(pd["sections"])
    # borderless sections, in document order, with cross-page header carry-over
    for ctx in _border_contexts(pages, chrome):
        sections.extend(_sections_from_context(ctx))

    # drop empty sections (a heading with no rows is still kept; truly empty ones go)
    sections = [s for s in sections if s["rows"] or s["heading"]]
    _clean_labels(sections)
    apply_corrections(sections, enabled=spell, quiet=quiet)
    return sections


def _clean_labels(sections):
    """Post-process labels: remove leading ``# `` noise from the first label
    (common in PDFs that print a row-number column) and strip phantom columns
    whose only label is ``#`` with sequential-integer values."""
    if not sections:
        return

    # Strip "# " prefix from labels.
    for sec in sections:
        labels = sec.get("labels") or []
        if not labels:
            continue
        new_labels = []
        changed = {}
        for lbl in labels:
            stripped = lbl
            if stripped.startswith("# "):
                stripped = stripped[2:].strip()
            elif stripped == "#":
                stripped = ""
            new_labels.append(stripped)
            if stripped != lbl:
                changed[lbl] = stripped
        if changed:
            sec["labels"] = new_labels
            for row in sec.get("rows", []):
                for old, new in changed.items():
                    if old in row:
                        row[new] = row.pop(old)

    # Detect and remove a pure row-number column: label is empty or lone "#",
    # and values in the first section are sequential integers 1, 2, 3, …
    if not sections:
        return
    first = sections[0]
    labels = first.get("labels") or []
    for idx, lbl in enumerate(labels):
        if lbl.strip() not in ("#", ""):
            continue
        # Check if this column holds sequential integers across the first section.
        rows = first.get("rows", [])
        if len(rows) < 3:
            continue
        sequential = True
        for i, row in enumerate(rows):
            val = row.get(lbl, "")
            try:
                n = int(val)
            except (ValueError, TypeError):
                sequential = False
                break
            if n != i + 1:
                sequential = False
                break
        if not sequential:
            continue
        # Remove this column from every section.
        for sec in sections:
            if lbl in (sec.get("labels") or []):
                sec["labels"].remove(lbl)
            for row in sec.get("rows", []):
                row.pop(lbl, None)
        break  # only strip one such column


# ---------------------------------------------------------------------------
# per-file driver
# ---------------------------------------------------------------------------

def convert_one(pdf_path, out_path, spell=True, quiet=False):
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
        sections = extract_sections(pdf_path, spell=spell, quiet=quiet, on_page=progress)
    except Exception as exc:  # noqa: BLE001
        if not quiet:
            sys.stderr.write("\n")
        sys.stderr.write(f"error: failed to read {pdf_path.name}: {exc}\n")
        return None

    if not quiet:
        sys.stderr.write("\r" + " " * 60 + "\r")

    rows = sum(len(s["rows"]) for s in sections)
    result = {
        "source": pdf_path.name,
        "section_count": len(sections),
        "total_rows": rows,
        "sections": sections,
    }
    out_path = Path(out_path).expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    if not quiet:
        print(f"{pdf_path.name}: {len(sections)} section(s), {rows} row(s) -> {out_path}")
    return out_path


# ---------------------------------------------------------------------------
# command line
# ---------------------------------------------------------------------------

def expand_inputs(raw_args):
    paths = []
    for arg in raw_args:
        matches = glob.glob(str(Path(arg).expanduser()))
        paths.extend(sorted(matches) if matches else [arg])
    return paths


def prompt_for_file():
    try:
        answer = input("Enter the path to a PDF file (or blank to cancel): ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None
    return answer.strip().strip('"').strip("'") or None


def main(argv):
    args = argv[1:]
    if any(a in ("-h", "--help") for a in args):
        print(__doc__.strip())
        return 0

    quiet = spell = False
    spell = True
    outdir = None
    inputs = []
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-q", "--quiet"):
            quiet = True
        elif a == "--no-spell":
            spell = False
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
    if not inputs:
        picked = prompt_for_file()
        if not picked:
            print("Nothing to do.")
            return 1
        inputs = expand_inputs([picked])

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
        if convert_one(pdf, out_path, spell=spell, quiet=quiet):
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
