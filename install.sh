#!/usr/bin/env bash
# install.sh — set up a virtualenv for pdf2json and (optionally) a `pdf2json`
# command on your PATH. Safe to re-run.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$HERE/.venv"

echo "==> Creating virtualenv at $VENV"
python3 -m venv "$VENV"

echo "==> Installing dependencies"
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r "$HERE/requirements.txt"

# A tiny launcher that always uses the venv's Python, runnable from anywhere.
LAUNCHER="$HERE/pdf2json"
cat > "$LAUNCHER" <<EOF
#!/usr/bin/env bash
exec "$VENV/bin/python" "$HERE/pdf2json.py" "\$@"
EOF
chmod +x "$LAUNCHER"

echo "==> Done."
echo
echo "Run it directly:"
echo "    $LAUNCHER mydoc.pdf"
echo
echo "Or put it on your PATH (so you can type 'pdf2json' anywhere):"
echo "    sudo ln -sf \"$LAUNCHER\" /usr/local/bin/pdf2json"
echo
echo "Then:"
echo "    pdf2json                 # asks you for a file"
echo "    pdf2json report.pdf      # writes report.json next to it"
