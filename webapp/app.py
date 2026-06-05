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
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
import pdf2json  # noqa: E402  (path set above)

MAX_MB = 50  # reject uploads larger than this

# Absolute base URL for canonical links, Open Graph tags, and the sitemap.
# Override per-deployment, e.g. SITE_URL=https://pdf2json.example.com.
SITE_URL = os.environ.get("SITE_URL", "https://pdf2json-j5oh.onrender.com/").rstrip("/")

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = MAX_MB * 1024 * 1024


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
        sections = pdf2json.extract_sections(tmp.name, spell=spell, quiet=True)
    except Exception as exc:  # noqa: BLE001 — surface any parse error to the UI
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


@app.route("/download", methods=["POST"])
def download():
    """Return the posted JSON as a downloadable file (so the browser can
    save large results without holding them in a data: URL)."""
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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    print(f"\n  pdf2json web UI  ->  http://127.0.0.1:{port}\n")
    app.run(host="127.0.0.1", port=port, debug=False)
