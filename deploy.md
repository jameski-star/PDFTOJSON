# Deploying pdf2json Online

This guide covers several ways to make pdf2json accessible on the web — from
quick, free options to production-grade setups.

**Important:** pdf2json reads PDF files uploaded by users. All deployment
options below keep file processing local to the server. No third-party
services ever see the PDF contents.

---

## Quick Deploy (Free)

The repo already ships everything these hosts need — you don't have to write
any config by hand:

| File             | Used by                                  |
|------------------|------------------------------------------|
| `render.yaml`    | Render (Blueprint)                       |
| `Procfile`       | Railway, Heroku-likes                    |
| `Dockerfile`     | Fly.io, Koyeb, Hugging Face Spaces, any container host |
| `runtime.txt`    | Pins Python 3.12 on buildpack hosts      |

All of them run the same command:

```bash
gunicorn --chdir webapp app:app -b 0.0.0.0:$PORT --timeout 120 --workers 2
```

> **Set `SITE_URL` after your first deploy** (e.g.
> `SITE_URL=https://pdf2json.onrender.com`). It makes the page's canonical
> link, Open Graph / Twitter cards, and `sitemap.xml` use your real domain
> instead of `127.0.0.1`. The site works without it, but SEO/social previews
> won't be correct until it's set.

---

### Option 1 — Render (easiest, no card)

[Render](https://render.com) has a free web-service tier. The repo's
`render.yaml` is a one-click **Blueprint**.

1. Push the repo to GitHub.
2. In [dashboard.render.com](https://dashboard.render.com): **New +** →
   **Blueprint** → pick the repo. Render reads `render.yaml` and fills in the
   build/start commands for you.
3. Click **Apply**. It goes live at `https://<name>.onrender.com`.
4. In the service's **Environment**, set `SITE_URL` to that URL and redeploy.

Prefer doing it manually? **New +** → **Web Service**, then:

| Field         | Value                                                              |
|---------------|-------------------------------------------------------------------|
| Build Command | `pip install -r webapp/requirements.txt`                          |
| Start Command | `gunicorn --chdir webapp app:app -b 0.0.0.0:$PORT --timeout 120`   |
| Instance Type | Free                                                              |

> **Cold-start note:** free Render instances sleep after 15 min idle; the
> first request after a pause takes ~30–60 s to wake. $7/mo keeps it always-on.

---

### Option 2 — Hugging Face Spaces (genuinely free, no card)

[Spaces](https://huggingface.co/spaces) runs the shipped `Dockerfile` for free
with no credit card and no cold-start sleep.

1. **New Space** → SDK: **Docker** → **Blank**.
2. Push this repo into the Space (it's a git remote), or upload the files.
3. Spaces builds the `Dockerfile` and serves on port `8080` automatically.
4. In **Settings → Variables**, add `SITE_URL=https://<user>-<space>.hf.space`.

---

### Option 3 — Railway

[Railway](https://railway.app) gives trial credits (no permanent free tier as
of 2026, but enough to run this cheaply). It auto-detects the `Procfile`.

1. Push to GitHub → [railway.app](https://railway.app) → **New Project** →
   **Deploy from GitHub repo**.
2. It reads the `Procfile` and installs from `webapp/requirements.txt`
   automatically — no start command to type.
3. Add `SITE_URL` under the service's **Variables**.

---

### Option 4 — Fly.io

[Fly.io](https://fly.io) offers a small free allowance and uses the shipped
`Dockerfile`.

```bash
curl -L https://fly.io/install.sh | sh   # install flyctl
fly launch        # detects the Dockerfile; say yes to deploy
fly secrets set SITE_URL=https://<your-app>.fly.dev
fly deploy
```

`fly launch` writes a `fly.toml` for you; set `internal_port = 8080` if it
asks. `auto_stop_machines` scales to zero when idle to stay inside the free
allowance.

---

### Option 5 — Koyeb

[Koyeb](https://koyeb.com) has a free web-service instance and builds the
shipped `Dockerfile`.

1. [app.koyeb.com](https://app.koyeb.com) → **Create Web Service** →
   **GitHub** → pick the repo.
2. Builder: **Dockerfile**. Port: **8080**.
3. Add `SITE_URL` under environment variables → **Deploy**.

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

**3. Build and run the shipped `Dockerfile`:**

The repo already includes a production `Dockerfile`. Clone and run it:

```bash
git clone https://github.com/jameski-star/pdf2json.git && cd pdf2json
docker build -t pdf2json .
docker run -d --name pdf2json --restart unless-stopped \
  -p 8080:8080 \
  -e SITE_URL=https://pdf2json.yourdomain.com \
  pdf2json
```

For a busier box, bump workers at run time:

```bash
docker run -d --name pdf2json --restart unless-stopped -p 8080:8080 \
  -e SITE_URL=https://pdf2json.yourdomain.com pdf2json \
  gunicorn --chdir webapp app:app -b 0.0.0.0:8080 -w 4 --timeout 120
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

| Variable   | Default                 | Description                                                        |
|------------|-------------------------|--------------------------------------------------------------------|
| `PORT`     | `5000`                  | Port the Flask app listens on (most hosts inject this)             |
| `SITE_URL` | `http://127.0.0.1:5000` | Public base URL for canonical, Open Graph, and `sitemap.xml` links |

Set in the shell, `.env` file, or your deployment platform. Always set
`SITE_URL` to your real `https://…` domain in production so search engines and
social-media previews use the correct URLs.

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
