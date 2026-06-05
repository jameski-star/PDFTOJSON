# pdf2json

Extract **every table from a PDF** into a clean, structured JSON file.

Output is grouped into **sections**. Each section has its own `heading` (a
section title like *"BACHELOR OF ARTS"*), the column `labels`, and the `rows`.
Every row is a sub-object mapping each label to the cell beneath it:

```json
{
  "source": "report.pdf",
  "section_count": 2,
  "total_rows": 1,
  "sections": [
    {
      "heading": "BACHELOR OF ARTS",
      "page": 1,
      "labels": ["PROG CODE", "INSTITUTION NAME", "CUTOFF"],
      "rows": [
        { "PROG CODE": "1105101", "INSTITUTION NAME": "CHUKA UNIVERSITY", "CUTOFF": "24.8" }
      ]
    }
  ]
}
```

Use it from the **command line** or a small **local web UI** (drag in a PDF,
preview and download the JSON).

### How it reads a page

- **Column labels** are found by their **bold font**, and are **carried forward**
  to later pages that repeat the same columns but don't reprint the header — so a
  48-page table whose header only appears on page 1 stays fully labelled.
- **Section titles** (centred lines that aren't rows) become their own `heading`
  field — never folded into a row.
- **Data rows** become `label: value` sub-objects.
- Words are read in the PDF's character-stream order, which **untangles
  overlapping headers** (e.g. `CODE`+`INSTITUTION` interleaving into the garbled
  `COIDNESTITUTION`) instead of scrambling them.
- A **dictionary-correction pass** fixes genuine misspellings (e.g.
  `Univrsity` → `University`) while protecting codes, numbers, and proper nouns.
  Disable it with `--no-spell`.
- **Ruled tables** (with drawn grid lines) are read directly and emitted as
  sections too.

---

## Quick start

```bash
cd pdf2json
./install.sh            # creates .venv, installs deps, makes a ./pdf2json launcher
./pdf2json report.pdf   # -> writes report.json next to the PDF
```

Run with **no arguments** and it asks you for a file:

```bash
$ ./pdf2json
Enter the path to a PDF file (or blank to cancel): /home/me/report.pdf
report.pdf: 4 table(s), 112 row(s) -> /home/me/report.json
```

---

## Usage

```
pdf2json                         # no args -> interactively ask for a file
pdf2json input.pdf               # writes input.json next to the PDF
pdf2json input.pdf out.json      # explicit output path
pdf2json a.pdf b.pdf c.pdf       # convert several PDFs in one run
pdf2json "folder/*.pdf"          # globs are expanded too
pdf2json -o out_dir *.pdf        # write all outputs into out_dir/
```

Options:

| Option            | Meaning                                   |
|-------------------|-------------------------------------------|
| `-o, --outdir DIR`| Write every `.json` into `DIR`.           |
| `--no-spell`      | Disable the dictionary word-correction pass.|
| `-q, --quiet`     | Only print errors (good for scripts/cron).|
| `-h, --help`      | Show help.                                |

---

## Web UI (local)

Prefer dragging a file into a browser? There's a tiny Flask app that wraps the
exact same converter.

```bash
./run-webapp.sh                 # installs Flask in .venv on first run
# -> open http://127.0.0.1:5000
PORT=8080 ./run-webapp.sh        # custom port
```

Then drop a PDF, hit **Convert**, and preview/download the JSON. It binds to
`127.0.0.1` only — it's meant for **local use**, not public hosting. Lives in
`webapp/` (`app.py` + `templates/index.html`).

---

## Deployment

### Option A — bundled virtualenv (simplest, no system changes)

```bash
./install.sh
sudo ln -sf "$(pwd)/pdf2json" /usr/local/bin/pdf2json   # optional: PATH-wide
pdf2json mydoc.pdf
```

`install.sh` is safe to re-run and pins everything inside `./.venv`, so it never
touches your system Python.

### Option B — pip install (gives a real `pdf2json` command)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install .
pdf2json mydoc.pdf
```

This uses `pyproject.toml` and exposes the `pdf2json` console command via its
entry point.

### Option C — Docker

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY pdf2json.py corrections.py ./
ENTRYPOINT ["python", "pdf2json.py"]
```

```bash
docker build -t pdf2json .
docker run --rm -v "$PWD:/data" pdf2json /data/report.pdf /data/report.json
```

### Requirements

- Python 3.8+
- [`pdfplumber`](https://github.com/jsvine/pdfplumber) and
  [`pyspellchecker`](https://github.com/barrust/pyspellchecker) (both pulled in
  automatically). If `pyspellchecker` is missing the converter still runs — it
  just skips the word-correction pass.

---

## When the generic extractor isn't enough

The header-aware logic above handles most recurring documents (bold headers
carried across pages, overlapping headers untangled) without tuning. If a
specific document still needs hand-tuned column positions, `kuccps_extract.py`
is a worked example of that approach for the 48-page Kenyan KUCCPS degree
cut-offs document (`examples/KUCCPSDEGREES.pdf`) — use it as a template:

```bash
.venv/bin/python kuccps_extract.py examples/KUCCPSDEGREES.pdf out.json
```

---

## Project layout

```
pdf2json/
├── pdf2json.py          # the general converter (CLI)
├── corrections.py       # optional dictionary word-correction pass
├── kuccps_extract.py    # example tuned extractor for one specific PDF
├── requirements.txt
├── pyproject.toml       # pip-installable, exposes the `pdf2json` command
├── install.sh           # one-shot venv + launcher setup
├── run-webapp.sh        # start the local web UI
├── webapp/              # local Flask web UI
│   ├── app.py
│   ├── requirements.txt
│   └── templates/index.html
├── README.md
└── examples/
    ├── KUCCPSDEGREES.pdf
    └── KUCCPSDEGREES.expected.json
```
