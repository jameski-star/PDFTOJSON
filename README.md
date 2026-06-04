# pdf2json

Extract **every table from a PDF** into a clean, structured JSON file.

Each table becomes an object with a `title`, a list of `headings`, and a list of
`rows`. Every row is a sub-object mapping each heading to the cell beneath it:

```json
{
  "source": "report.pdf",
  "table_count": 2,
  "tables": [
    {
      "table_number": 1,
      "page": 3,
      "title": "Universities and Cut-off Points",
      "headings": ["Institution", "Programme", "Cutoff"],
      "rows": [
        { "Institution": "Kenyatta University", "Programme": "BA", "Cutoff": "28.4" }
      ]
    }
  ]
}
```

It handles two kinds of tables automatically, per page:

- **Ruled tables** (with drawn grid lines) — read directly and accurately.
- **Borderless tables** — reconstructed by clustering word positions into rows
  and columns using whitespace corridors. The line just above a table is picked
  up as its title.

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
| `-q, --quiet`     | Only print errors (good for scripts/cron).|
| `-h, --help`      | Show help.                                |

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
COPY pdf2json.py .
ENTRYPOINT ["python", "pdf2json.py"]
```

```bash
docker build -t pdf2json .
docker run --rm -v "$PWD:/data" pdf2json /data/report.pdf /data/report.json
```

### Requirements

- Python 3.8+
- [`pdfplumber`](https://github.com/jsvine/pdfplumber) (pulled in automatically)

---

## When the generic extractor isn't enough

Some PDFs have overlapping headers or a single table spanning dozens of pages
with no repeated header. For those, a small **tuned** extractor with hard-coded
column positions is far more reliable than generic detection.

`kuccps_extract.py` is a worked example: it converts the 48-page Kenyan KUCCPS
degree cut-offs document (`examples/KUCCPSDEGREES.pdf`) into
**534 sections / 2170 rows**. Use it as a template when you need to tune for a
specific recurring document:

```bash
.venv/bin/python kuccps_extract.py
# -> KUCCPSDEGREES.json
```

The expected output is checked in at `examples/KUCCPSDEGREES.expected.json`.

---

## Project layout

```
pdf2json/
├── pdf2json.py          # the general converter (CLI)
├── kuccps_extract.py    # example tuned extractor for one specific PDF
├── requirements.txt
├── pyproject.toml       # pip-installable, exposes the `pdf2json` command
├── install.sh           # one-shot venv + launcher setup
├── README.md
└── examples/
    ├── KUCCPSDEGREES.pdf
    └── KUCCPSDEGREES.expected.json
```
