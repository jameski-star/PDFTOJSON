#!/usr/bin/env bash
# run-webapp.sh — start the local pdf2json web UI.
# Reuses the project's .venv (created by install.sh) and installs Flask there
# on first run. Open the printed URL in your browser.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$HERE/.venv"

if [ ! -x "$VENV/bin/python" ]; then
  echo "==> No virtualenv found — running install.sh first"
  bash "$HERE/install.sh"
fi

# Ensure Flask is present (pdfplumber comes from install.sh).
if ! "$VENV/bin/python" -c "import flask" 2>/dev/null; then
  echo "==> Installing Flask into the virtualenv"
  "$VENV/bin/pip" install --quiet flask
fi

PORT="${PORT:-5000}"
echo "==> Starting pdf2json web UI on http://127.0.0.1:$PORT  (Ctrl+C to stop)"
PORT="$PORT" exec "$VENV/bin/python" "$HERE/webapp/app.py"
