#!/usr/bin/env python3
"""
pdf2json web UI — a Flask app wrapping the pdf2json converter, plus a full
marketing site (hero, features, how-it-works, use-cases, FAQ) around it.

Drop a PDF in the browser, it runs the same extract_sections() used by the CLI,
and hands back the structured JSON for preview and download.

Run:
    python app.py            # http://127.0.0.1:5000
    PORT=8080 python app.py  # custom port

For a public deployment set SITE_URL so canonical/OG/sitemap links are correct:
    SITE_URL=https://pdf2json.example.com python app.py
"""

import io
import json
import os
import sys
import tempfile
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request, send_file

# Import the converter that lives one directory up (pdf2json.py).
# When gunicorn changes to webapp/ directory, we need to resolve the absolute path.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

print(f"==> PROJECT_ROOT: {PROJECT_ROOT}", flush=True)
print(f"==> sys.path: {sys.path[:3]}", flush=True)

try:
    import pdf2json  # noqa: E402  (path set above)
    print(f"✓ Successfully imported pdf2json from {PROJECT_ROOT}", flush=True)
except ImportError as e:
    print(f"✗ FATAL: Could not import pdf2json: {e}", file=sys.stderr, flush=True)
    print(f"  Repo files:", file=sys.stderr, flush=True)
    try:
        for item in sorted(Path(PROJECT_ROOT).iterdir()):
            if not item.name.startswith('.'):
                size = "(dir)" if item.is_dir() else f"{item.stat().st_size} bytes"
                print(f"    - {item.name} {size}", file=sys.stderr, flush=True)
    except Exception as list_err:
        print(f"    (error listing: {list_err})", file=sys.stderr, flush=True)
    raise

MAX_MB = 50  # reject uploads larger than this

# Absolute base URL for canonical links, Open Graph tags, and the sitemap.
SITE_URL = os.environ.get("SITE_URL", "https://pdf2json-j5oh.onrender.com/").rstrip("/")

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = MAX_MB * 1024 * 1024

print(f"✓ Flask app initialized. SITE_URL={SITE_URL}", flush=True)


@app.route("/")
def index():
    return render_template("index.html", max_mb=MAX_MB, site_url=SITE_URL)


@app.route("/robots.txt")
def robots():
    body = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /convert\n"
        "Disallow: /download\n"
        f"Sitemap: {SITE_URL}/sitemap.xml\n"
    )
    return Response(body, mimetype="text/plain")


@app.route("/sitemap.xml")
def sitemap():
    pages = ["/", "/#features", "/#how", "/#use-cases", "/#app", "/#faq"]
    urls = "".join(
        f"  <url><loc>{SITE_URL}{p}</loc>"
        f"<changefreq>weekly</changefreq>"
        f"<priority>{'1.0' if p == '/' else '0.7'}</priority></url>\n"
        for p in pages
    )
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{urls}"
        "</urlset>\n"
    )
    return Response(body, mimetype="application/xml")


@app.route("/convert", methods=["POST"])
def convert():
    try:
        upload = request.files.get("file")
        if upload is None or upload.filename == "":
            return jsonify(error="No file was uploaded."), 400

        name = upload.filename
        if not name.lower().endswith(".pdf"):
            return jsonify(error="That doesn't look like a PDF. Please upload a .pdf file."), 400

        spell = request.form.get("spell", "1") != "0"

        # Save to a temp file so pdfplumber can open it by path.
        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        try:
            upload.save(tmp.name)
            tmp.close()
            print(f"Processing: {name}", flush=True)
            sections = pdf2json.extract_sections(tmp.name, spell=spell, quiet=True)
            print(f"✓ Processed: {len(sections)} sections, {sum(len(s['rows']) for s in sections)} rows", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"✗ PDF processing error: {exc}", file=sys.stderr, flush=True)
            import traceback
            traceback.print_exc(file=sys.stderr)
            return jsonify(error=f"Could not read this PDF: {exc}"), 422
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass

        row_count = sum(len(s["rows"]) for s in sections)
        page_count = max((s.get("page", 0) for s in sections), default=0)
        result = {
            "source": name,
            "section_count": len(sections),
            "total_rows": row_count,
            "sections": sections,
        }
        return jsonify(
            filename=Path(name).with_suffix(".json").name,
            section_count=len(sections),
            row_count=row_count,
            page_count=page_count,
            result=result,
        )
    except Exception as e:
        print(f"✗ CRITICAL /convert error: {e}", file=sys.stderr, flush=True)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return jsonify(error=f"Internal server error: {e}"), 500


@app.route("/download", methods=["POST"])
def download():
    """Return the posted JSON as a downloadable file."""
    payload = request.get_json(silent=True) or {}
    result = payload.get("result")
    filename = payload.get("filename") or "tables.json"
    if result is None:
        return jsonify(error="Nothing to download."), 400
    blob = json.dumps(result, indent=2, ensure_ascii=False).encode("utf-8")
    return send_file(
        io.BytesIO(blob),
        mimetype="application/json",
        as_attachment=True,
        download_name=filename,
    )


@app.errorhandler(413)
def too_large(_err):
    return jsonify(error=f"File is too large (limit {MAX_MB} MB)."), 413


@app.errorhandler(500)
def internal_error(e):
    print(f"✗ 500 Error: {e}", file=sys.stderr, flush=True)
    import traceback
    traceback.print_exc(file=sys.stderr)
    return jsonify(error="Internal server error. Check logs."), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    print(f"\n  pdf2json web UI  ->  http://127.0.0.1:{port}\n", flush=True)
    app.run(host="127.0.0.1", port=port, debug=False)
