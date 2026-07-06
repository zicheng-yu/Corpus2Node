# Deploy

Production stack for Corpus2Node: a **private** FastAPI/uvicorn backend behind a **public**
nginx that serves the built React SPA and reverse-proxies `/api/*` to the backend. One public
port (**80**), Docker Compose, auto-restart on reboot.

```
browser ── http://<server-ip>/ ───────────► nginx :80 ──► static SPA (frontend/dist)
        └─ http://<server-ip>/api/* ───────► nginx :80 ──► backend:8000 (private)
```

## Layout

| File | Purpose |
|------|---------|
| `Dockerfile.backend`  | uv-managed FastAPI image, core deps only (hashing embeddings, **no torch**). |
| `Dockerfile.frontend` | Multi-stage: Vite build (`VITE_API_BASE_URL=/api`) → nginx serving `dist/`. |
| `nginx.conf`          | `:80` static + `/api/` proxy; SSE-safe (`proxy_buffering off`), 600 MB uploads. |
| `docker-compose.yml`  | `backend` (private) + `nginx` (`80:80`); non-secret env inlined; volumes for data + whisper cache. |

## Prerequisites

- Docker Engine + Compose plugin on the server.
- **Cloud firewall / security group must allow inbound TCP 80** (and 22 for SSH). On Tencent
  Cloud this is set in the console security group — it is *not* controllable over SSH.

## First deploy

From the repo root **on the server** (e.g. `~/Corpus2Node`):

```bash
mkdir -p artifacts                  # holds JSON data + llm_settings.json (model credentials)
# (copy your artifacts/llm_settings.json here so models work out of the box)
docker compose -f deploy/docker-compose.yml up -d --build
```

Verify:

```bash
docker compose -f deploy/docker-compose.yml ps          # both services Up
curl -fsS localhost/api/health                          # {"status":"ok",...}
```

Then open `http://<server-ip>/` in a browser.

## Update to a new version

```bash
# sync new code to the server, then:
docker compose -f deploy/docker-compose.yml up -d --build
```

## Operate

```bash
docker compose -f deploy/docker-compose.yml logs -f backend   # follow backend logs
docker compose -f deploy/docker-compose.yml restart           # restart
docker compose -f deploy/docker-compose.yml down              # stop & remove (data/credentials in ./artifacts survive)
```

## Notes

- **Model credentials** live in `artifacts/llm_settings.json` (mounted volume), configurable in
  the app at **Settings → Models** — never baked into the image.
- **Embeddings** default to `hashing` (zero-dep). For higher-quality semantic search switch
  `EMBED_PROVIDER` in `docker-compose.yml` to `openai_compatible` (bind an `embedding` credential
  in the UI) or `bge_m3` (rebuild the backend image with the `ml` extra — pulls torch, multi-GB).
- **No auth / no TLS.** Anyone who can reach port 80 can use the app (and spend the configured
  API credits). For HTTPS you need a domain + a TLS terminator (Caddy/Traefik/certbot) — not
  included here since access is by raw IP.
- First audio ingestion downloads the faster-whisper `base` model (~140 MB) via `HF_ENDPOINT`
  into the `whisper-cache` volume.
