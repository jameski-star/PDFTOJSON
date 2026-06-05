# pdf2json — container image for the web app (Fly.io, Koyeb, HF Spaces, any host).
FROM python:3.12-slim

# pdfplumber/pdfminer need no system libs for text PDFs; keep the image lean.
WORKDIR /app

# Install deps first for better layer caching.
COPY webapp/requirements.txt /app/webapp/requirements.txt
RUN pip install --no-cache-dir -r webapp/requirements.txt

# Copy the converter (root) and the web app.
COPY pdf2json.py corrections.py /app/
COPY webapp /app/webapp

# Most free hosts inject $PORT; default to 8080 for local `docker run`.
ENV PORT=8080
EXPOSE 8080

# Shell form so $PORT expands at runtime.
CMD gunicorn --chdir webapp app:app -b 0.0.0.0:$PORT --timeout 120 --workers 2
