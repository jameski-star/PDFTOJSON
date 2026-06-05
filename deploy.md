# Deploying pdf2json Online

This guide covers several ways to make pdf2json accessible on the web — from
quick, free options to production-grade setups.

**Important:** pdf2json reads PDF files uploaded by users. All deployment
options below keep file processing local to the server. No third-party
services ever see the PDF contents.

---

## Quick Deploy (Free / Low Cost)

### Option 1 — Render (easiest)

[Render](https://render.com) offers a free tier for web services.

1. Push your repo to GitHub
2. Log into [dashboard.render.com](https://dashboard.render.com)
3. Click **New +** → **Web Service**
4. Connect your GitHub repo
5. Configure:

   | Field          | Value                             |
   |----------------|-----------------------------------|
   | Runtime        | Python 3                          |
   | Build Command  | `pip install -r requirements.txt && pip install -r webapp/requirements.txt` |
   | Start Command  | `cd webapp && gunicorn -b 0.0.0.0:$PORT app:app` |
   | Instance Type  | Free                             |

6. Click **Create Web Service**

The app will be live at `https://your-app.onrender.com`.

> **Cold-start note:** Free Render instances spin down after 15 min of
> inactivity. The first request after a pause takes ~30–60 s to wake up.
> Upgrade to a paid instance ($7/mo) to keep it always-on.

---

### Option 2 — Railway

[Railway](https://railway.app) has a generous free tier with no cold-start.

1. Push your repo to GitHub
2. Log into [railway.app](https://railway.app)
3. Click **New Project** → **Deploy from GitHub repo**
4. Railway auto-detects the Python app and installs from
   `requirements.txt`. Add a start command override:

   ```
   cd webapp && gunicorn -b 0.0.0.0:$PORT app:app
   ```

5. Deploy.

---

### Option 3 — Fly.io

[Fly.io](https://fly.io) offers 3 free shared VMs. Great for low-latency
global deployment.

1. Install the `flyctl` CLI:

   ```bash
   curl -L https://fly.io/install.sh | sh
   ```

2. Create a `fly.toml` in your project root:

   ```toml
   app = "pdf2json"
   primary_region = "iad"

   [build]
     dockerfile = "Dockerfile"

   [http_service]
     internal_port = 8080
     force_https = true
     auto_stop_machines = true
     auto_start_machines = true
     min_machines_running = 0
   ```

3. Create a `Dockerfile`:

   ```dockerfile
   FROM python:3.12-slim
   WORKDIR /app
   COPY requirements.txt webapp/requirements.txt ./
   RUN pip install --no-cache-dir -r requirements.txt -r webapp/requirements.txt
   COPY pdf2json.py corrections.py ./
   COPY webapp/ ./webapp/
   WORKDIR /app/webapp
   CMD ["gunicorn", "-b", "0.0.0.0:8080", "app:app"]
   ```

4. Deploy:

   ```bash
   fly launch   # first time
   fly deploy   # subsequent updates
   ```

---

## Production Deploy

### Option 4 — VPS with Docker (DigitalOcean, Hetzner, Linode)

Best for full control, custom domains, and higher traffic.

**1. Get a VPS**

Any $4–6/mo VPS works. Recommended:
- [Hetzner CX22](https://www.hetzner.com/cloud) (~€4/mo)
- [DigitalOcean Droplet](https://www.digitalocean.com) ($6/mo)

**2. SSH in and install Docker:**

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# log out and back in
```

**3. Create a `Dockerfile` (same as Fly.io above):**

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt webapp/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r webapp/requirements.txt
COPY pdf2json.py corrections.py ./
COPY webapp/ ./webapp/
WORKDIR /app/webapp
EXPOSE 8080
CMD ["gunicorn", "-b", "0.0.0.0:8080", "-w", "4", "--timeout", "120", "app:app"]
```

**4. Build and run:**

```bash
docker build -t pdf2json .
docker run -d --name pdf2json --restart unless-stopped -p 8080:8080 pdf2json
```

**5. Optional — reverse proxy with Caddy (automatic HTTPS):**

```bash
sudo apt install -y caddy
```

Edit `/etc/caddy/Caddyfile`:

```
pdf2json.yourdomain.com {
    reverse_proxy localhost:8080
}
```

```bash
sudo systemctl reload caddy
```

---

### Option 5 — Docker Compose with Traefik

Multi-service setup with automatic Let's Encrypt certificates.

**`docker-compose.yml`:**

```yaml
version: "3.8"

services:
  pdf2json:
    build: .
    restart: unless-stopped
    environment:
      - PORT=8080
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.pdf2json.rule=Host(`pdf2json.yourdomain.com`)"
      - "traefik.http.routers.pdf2json.tls.certresolver=letsencrypt"

  traefik:
    image: traefik:v3
    command:
      - "--providers.docker=true"
      - "--providers.docker.exposedbydefault=false"
      - "--entrypoints.websecure.address=:443"
      - "--certificatesresolvers.letsencrypt.acme.tlschallenge=true"
      - "--certificatesresolvers.letsencrypt.acme.email=you@example.com"
      - "--certificatesresolvers.letsencrypt.acme.storage=/letsencrypt/acme.json"
    ports:
      - "443:443"
    volumes:
      - "/var/run/docker.sock:/var/run/docker.sock:ro"
      - "./letsencrypt:/letsencrypt"
```

```bash
docker compose up -d
```

---

## Environment Variables

| Variable | Default | Description                     |
|----------|---------|---------------------------------|
| `PORT`   | `5000`  | Port the Flask app listens on   |

Set in the shell, `.env` file, or your deployment platform.

---

## Sizing & Limits

| Concern            | Guideline                                        |
|--------------------|--------------------------------------------------|
| Max upload size    | 50 MB (set in `app.py` — `MAX_MB`)               |
| Per-request memory | ~2× the PDF file size (worst case, large tables) |
| Recommended RAM    | 512 MB minimum, 1 GB for production              |
| Workers            | 2–4 gunicorn workers per vCPU                    |
| Timeout            | 120 s (large PDFs with many pages)               |

---

## Security Notes

- The web UI binds to `127.0.0.1` by default. When deploying, gunicorn
  binds to `0.0.0.0` so the reverse proxy can reach it — **always** put a
  reverse proxy (Caddy, Nginx, Traefik) in front, never expose Flask
  directly to the internet.
- Uploaded files are written to a temp file, processed, and immediately
  deleted. They are never persisted to disk beyond the current request.
- The app has no authentication. If you need access control, add HTTP
  Basic Auth at the reverse-proxy layer:

  **Caddy:**
  ```
  pdf2json.yourdomain.com {
      basicauth {
          user $2a$14$...
      }
      reverse_proxy localhost:8080
  }
  ```

  Generate the password hash with: `caddy hash-password`

---

## Monitoring

For production, add a health-check endpoint. The webapp doesn't have one
built in, but you can add it trivially. Add this to `webapp/app.py`:

```python
@app.route("/health")
def health():
    return {"status": "ok"}
```

Then configure your platform's health check to hit `/health`.

---

## Troubleshooting

| Symptom                              | Likely Fix                                   |
|--------------------------------------|----------------------------------------------|
| 413 Request Entity Too Large         | Increase `MAX_MB` in `app.py`, rebuild       |
| 502 Bad Gateway (behind proxy)       | Increase proxy timeout to 120 s              |
| Slow conversions                     | Disable spell check (`--no-spell` / toggle)  |
| App spins down (Render free tier)    | Use Railway or Fly.io instead, or upgrade    |
| `pdfplumber` import error            | Run `pip install -r requirements.txt` again  |
