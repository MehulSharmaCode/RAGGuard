# RAGGuard — Docker deployment (Stage 6)

A local, single-machine deployment of the whole application with Docker Compose: the web UI, the API, and a Qdrant vector-store server, with persistent named volumes. **It is a practical local/demo deployment, not production infrastructure:** no TLS, no login, one node, no failover, no CI/CD (Stage 7).

Verified on 2026-10-25/26 with Docker Engine 29.8.0 and Docker Compose 5.5.1 on Docker Desktop for macOS, Apple Silicon (linux/arm64), using the Ollama app on the host. The evidence is in [`docs/PROGRESS_LOG.md`](../docs/PROGRESS_LOG.md) (entry "Stage 6"). The owner's manual acceptance on their Mac passed on 2026-10-26 (containerised AgriSense ingestion and answers, SIH retrieval with citations, AgriSense-only selection not using SIH evidence, documents and query behaviour preserved across a backend restart). **Not tested:** linux/amd64 images, Linux hosts, Windows.

## 1. What runs

```
 browser ──▶ frontend  (Nginx 1.30, 127.0.0.1:8080)  ── serves the production UI
                │                                       └─ proxies /health /ingest /documents /query
                │                                          /evaluations /experiments /system
                ▼
             backend   (FastAPI + uvicorn, port 8000, internal only)
                ├──▶ qdrant (Qdrant 1.19.2 server, port 6333, internal only, volume)
                └──▶ Ollama on the HOST (http://host.docker.internal:11434)
```

| Service | Image | Listens | Published to the host | Runs as |
| --- | --- | --- | --- | --- |
| `frontend` | built from `deployment/frontend.Dockerfile` (`nginxinc/nginx-unprivileged:1.30-alpine`, 93 MB) | 8080 | `127.0.0.1:${WEB_PORT:-8080}` | uid 101 |
| `backend` | built from `deployment/backend.Dockerfile` (`python:3.13-slim-trixie`, 2.6 GB with PyTorch CPU) | 8000 | nothing (reached through the web server) | uid 10001 |
| `qdrant` | `qdrant/qdrant:v1.19.2-unprivileged` | 6333 | nothing | uid 1000 |

**Ollama is not a container.** The model (`qwen3.5:9b`, 7+ GB) and the Mac's GPU live on the host; a Linux container on Docker Desktop cannot use the GPU. **MLflow is not a server either:** the existing local SQLite store + file artifacts are used, in a volume.

The browser talks to `http://127.0.0.1:8080` and, for one read-only list on the Pipeline page (recent GitHub Actions runs), anonymously to `https://api.github.com` (allowed in the Content-Security-Policy `connect-src`; no token, no data from your documents is sent; if GitHub is unreachable that list says so and nothing else changes). Nginx serves the UI and forwards exactly the API route prefixes the UI uses to `backend:8000` (same origin: **no CORS**, no API URL baked into the JavaScript — the bundle is built with an empty `VITE_API_BASE_URL`). Host development (`npm run dev` on 5173, uvicorn on 8000) is unchanged and uses its own `http://localhost:8000` default.

## 2. Files

| File | Purpose |
| --- | --- |
| `compose.yaml` (repository root) | The one canonical Compose file: services, health-gated start order, volumes, hardening |
| `deployment/backend.Dockerfile` | API image (targets `runtime` = default, and `test`) |
| `deployment/frontend.Dockerfile` | Multi-stage: `npm ci` + `npm run build`, then Nginx |
| `deployment/nginx.conf` | Static files, API proxy, timeouts, JSON errors, security headers |
| `.dockerignore` (root) | Allow-list: only the listed source/dataset files enter a build (context: 3 MB backend, 0.5 MB frontend) |
| `deployment/smoke_test.py` | Runtime smoke test (standard library only) |
| `.env.example` | Section "Docker Compose deployment (Stage 6)" lists the variables |

## 3. Prerequisites

- Docker Desktop running (`docker info` must answer) and Compose v2+ (`docker compose version`).
- Ollama running on the host with the model installed: `ollama list` shows `qwen3.5:9b`.
- Internet on the **first** run: base images, Python wheels (PyTorch CPU wheel index), npm packages, and the embedding model (≈ 90 MB, downloaded into a volume once). Afterwards `HF_HUB_OFFLINE=1` works.
- Free host port 8080 (or choose another with `WEB_PORT`).
- Docker Desktop memory: the three containers used ≈ 0.9 GB with the model loaded (backend 573 MiB, Qdrant 335 MiB, web 15 MiB); the VM here has 8 GB. A running evaluation adds the embedding model and a temporary index in a one-off container.
- Disk: images ≈ 2.7 GB plus the volumes.

## 4. Commands

Run everything from the repository root.

```bash
docker compose config -q                 # validate the configuration (prints nothing when valid)
docker compose up -d --build --wait      # build the images, start the stack, wait until all are healthy
docker compose ps                        # service state and health
docker compose logs -f backend           # logs (also: frontend, qdrant)
open http://127.0.0.1:8080               # the application
python3 deployment/smoke_test.py         # runtime smoke test (section 6)
docker compose down                      # stop and remove the containers; the VOLUMES (your data) stay
docker compose up -d                     # start again; the data is still there
```

**Never run `docker compose down -v`, `docker volume prune` or `docker system prune --volumes`**: they delete the volumes, i.e. all documents, the model cache, the tracking store, and the reports. To free *build* space only, `docker builder prune` is safe.

Health checks: `docker compose ps` shows `healthy` for each service. For the backend this means **the API process answers `GET /health` with HTTP 200** — not that Ollama or Qdrant are reachable (the response body says that: `status: ok|degraded`, `generation_ready`, per-component state; the same data is in the UI top bar and Pipeline view). Qdrant is probed on `/readyz`; the web server on `/healthz`.

Start order is enforced: `qdrant` healthy → `backend` healthy → `frontend`.

## 5. Configuration

Compose reads variables from the shell or the repository's `.env` (copy `.env.example`; `.env` is git-ignored). **Only the variables below reach the containers** — host-only values such as `OLLAMA_BASE_URL=http://localhost:11434` or `QDRANT_LOCAL_PATH` are never passed on, so the same `.env` can serve the host setup.

| Variable | Default | Meaning |
| --- | --- | --- |
| `WEB_PORT` | `8080` | Host port of the web UI |
| `WEB_BIND` | `127.0.0.1` | Host address; `0.0.0.0` exposes the app (which has no login) to your network |
| `DOCKER_OLLAMA_BASE_URL` | `http://host.docker.internal:11434` | Where the backend container finds Ollama |
| `GENERATION_PROVIDER` | `ollama` | `ollama` or `gemini` |
| `OLLAMA_MODEL` | `qwen3.5:9b` | Must be installed in the host's Ollama; never substituted silently |
| `OLLAMA_TIMEOUT_SECONDS` | `180` | Nginx waits up to 330 s; the UI itself gives up after 200 s |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | empty / `gemini-2.5-flash` | Only if `GENERATION_PROVIDER=gemini`. The key is passed as a container environment variable (visible to anyone who can run `docker inspect`); it is in no image layer |
| `EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | Changing it changes the vector size: also set a new `QDRANT_COLLECTION_NAME` |
| `QDRANT_COLLECTION_NAME` | `ragguard_chunks` | |
| `HF_HUB_OFFLINE` | `0` | `1` = never contact Hugging Face (needs the model already in the `hf_cache` volume) |
| `LOG_LEVEL` | `INFO` | |

Fixed by the images (container-internal paths; change them only together with `compose.yaml`): `QDRANT_URL=http://qdrant:6333`, `HF_HOME=/data/hf-cache`, `MLFLOW_TRACKING_URI=sqlite:////data/mlflow/mlflow.db`, `MLFLOW_ARTIFACT_ROOT=/data/mlflow/artifacts`, `EVALUATION_RESULTS_DIR=/data/reports`, `RAGGUARD_RUNTIME=docker`. Chunking, the retrieval threshold and the prompt keep the image defaults, which are the accepted Stage 5.7 baseline.

## 6. Smoke test

```bash
python3 deployment/smoke_test.py                       # against http://127.0.0.1:8080
python3 deployment/smoke_test.py --base-url http://127.0.0.1:18080    # other WEB_PORT
```

It uploads a small **synthetic** document it writes itself (your documents are never touched), checks that `/`, `/healthz`, `/health`, `/system/status` answer, that the vector store is a `remote` Qdrant, asks a question stated in the document (answer must contain the fact, with a citation to that document and a cited passage containing it), asks an unrelated question (must give the safe fallback without calling the model), and deletes only that document by the ID the API returned. All queries are scoped to the synthetic document.

Exit code `0` = all passed; `1` = a check failed; `2` = nothing failed but the generation provider was not ready, so answering is reported as **SKIP** (container plumbing verified, model inference not).

Persistence check (documents must survive restarts):

```bash
python3 deployment/smoke_test.py --keep                 # prints: KEPT document <id>
docker compose restart backend && docker compose up -d --wait
python3 deployment/smoke_test.py --verify <id>          # still listed, still answers
docker compose restart qdrant && docker compose up -d --wait
python3 deployment/smoke_test.py --verify <id>
python3 deployment/smoke_test.py --delete <id>          # clean up
```

## 7. Data and persistence

| Data | Location in the container | Persisted by | Survives `down` + `up` / container recreation |
| --- | --- | --- | --- |
| Vector index (documents, chunks) | `/qdrant/storage` (qdrant) | volume `ragguard_qdrant_storage` | yes |
| Embedding-model files | `/data/hf-cache` (backend) | volume `ragguard_hf_cache` | yes — downloaded once (≈ 90 MB), then reused, also with `HF_HUB_OFFLINE=1` |
| MLflow tracking database | `/data/mlflow/mlflow.db` | volume `ragguard_mlflow` | yes |
| MLflow artifacts (reports per run) | `/data/mlflow/artifacts` | same volume, so database and artifact paths stay valid together | yes |
| Saved evaluation reports | `/data/reports` | volume `ragguard_reports` | yes |
| Original uploaded files | not stored (the app indexes text only, D-025) | — | n/a |
| Conversations | browser tab (sessionStorage) | — | not a server concern |
| Evaluation temporary index | `/tmp` of a one-off container | — | deleted after every run |

(With the project name `ragguard`, Compose prefixes the volume names: `ragguard_qdrant_storage`, …)

**This deployment has its own, empty index.** It never mounts your host `qdrant_storage/`, `mlflow.db`, `mlartifacts/` or `evaluation/results/`; the images contain none of them. Documents you indexed on the host must be **uploaded again** in the Docker UI, and the Evaluation/Experiments views start empty until you run an evaluation in the container (section 8). Your host development data is not read or changed.

Inspect a volume without changing it: `docker run --rm -v ragguard_mlflow:/v:ro alpine:3 ls -la /v`.

## 8. Evaluation in Docker

The evaluation CLI is in the backend image, together with the datasets. Run it in a one-off container (it reuses the model cache and writes to the reports and MLflow volumes; Ollama is used for generation and, unless `--skip-judge`, for the judge):

```bash
docker compose run --rm backend python -m app.evaluation.run_evaluation --skip-judge --limit 6 --label "smoke"
docker compose run --rm backend python -m app.evaluation.run_evaluation --label "core"          # full core benchmark, judge on (~4 min)
docker compose run --rm backend python -m app.evaluation.run_evaluation \
    --dataset /app/evaluation/datasets/veil/dataset.json                                          # other datasets: veil, structure, agrisense
```

The run indexes the corpus into a **temporary embedded Qdrant store inside that one-off container** and deletes it afterwards; it never uses the Qdrant server (verified: the server's collections and point counts are identical before and after). New runs appear in the Evaluation and Experiments views after "Reload". Runs started in the container are tagged `git_commit: unavailable` (no Git in the image). Nothing runs an evaluation automatically.

## 9. Backup and restore (tested)

Qdrant's files are consistent only while Qdrant is not writing, so stop it for the copy (the data stays):

```bash
mkdir -p backups
docker compose stop qdrant
docker run --rm -v ragguard_qdrant_storage:/volume:ro -v "$PWD/backups":/backup alpine:3 \
    tar czf /backup/qdrant_storage.tgz -C /volume .
docker compose start qdrant
```

The other volumes (`ragguard_mlflow`, `ragguard_reports`, `ragguard_hf_cache`) are archived the same way (replace the volume name and archive name). `backups/` is git-ignored because the archives contain your indexed documents; never publish one.

Restore into a **new** volume and check it before relying on it (this does not touch the live volume):

```bash
docker volume create ragguard_restore_check
docker run --rm -v ragguard_restore_check:/volume -v "$PWD/backups":/backup:ro alpine:3 \
    sh -c 'tar xzf /backup/qdrant_storage.tgz -C /volume && ls /volume'
docker run -d --name restore-check -v ragguard_restore_check:/qdrant/storage qdrant/qdrant:v1.19.2-unprivileged
docker exec restore-check bash -c 'exec 3<>/dev/tcp/127.0.0.1/6333 && printf "GET /collections/ragguard_chunks HTTP/1.0\r\n\r\n" >&3 && cat <&3' | grep -o '"points_count":[0-9]*'
docker rm -f restore-check && docker volume rm ragguard_restore_check    # remove only this throwaway pair
```

Replacing the **live** volume with a backup (stop the stack with `docker compose down`, then extract the archive over `ragguard_qdrant_storage`) overwrites its contents. That in-place step was not exercised in this stage: make a fresh backup first and test with a new volume as above.

## 10. Troubleshooting

| Symptom | Cause and what to do |
| --- | --- |
| `failed to connect to the docker API at unix:///…/docker.sock` | Docker Desktop is not running. Start it and wait until `docker info` answers (10–60 s). |
| `ports are not available: exposing port TCP 127.0.0.1:8080 -> …: bind: address already in use` | Another program uses the host port (your dev servers use 5173 and 8000; Docker defaults to 8080). Set another `WEB_PORT` (e.g. `WEB_PORT=18080 docker compose up -d`). Do not kill the other process. |
| `backend` unhealthy or restarting | `docker compose logs backend`. A configuration error (e.g. `CHUNK_OVERLAP_TOKENS must be smaller…`) is printed at startup. The backend waits for a healthy Qdrant first. |
| `qdrant` never healthy | `docker compose logs qdrant`; first start takes a few seconds. A volume that is not writable by uid 1000 (only if you replaced the named volume with a bind mount) must be `chown`ed. |
| Upload fails with `embedding_unavailable` ("The embedding model could not be loaded…") | First use needs internet to download the model into the `hf_cache` volume, or `EMBEDDING_MODEL` is wrong, or `HF_HUB_OFFLINE=1` with an empty cache. Fix the cause and retry; nothing is stored for a failed upload. |
| UI says generation unavailable; `/health` shows `"The Ollama service is not reachable."` | Ollama is not running on the host, or the URL is wrong. Check `ollama list` on the host and `DOCKER_OLLAMA_BASE_URL`. From inside: `docker compose exec backend python -c "import urllib.request; print(urllib.request.urlopen('http://host.docker.internal:11434/api/tags').status)"`. (The message mentions `OLLAMA_BASE_URL`; in Compose the variable is `DOCKER_OLLAMA_BASE_URL`.) On Linux, Ollama must listen on all interfaces (`OLLAMA_HOST=0.0.0.0`) — not tested here. |
| `/health` shows `model_missing` ("Model '…' is not installed.") | `ollama pull qwen3.5:9b` on the host, or set `OLLAMA_MODEL` to an installed model. No other model is used silently. |
| `generation_timeout` (504) | The model took longer than `OLLAMA_TIMEOUT_SECONDS`. Raise it (the UI gives up at 200 s regardless). A cold model load adds ≈ 10–20 s to the first answer. |
| Browser shows `backend_unavailable` / "Cannot reach the RAGGuard API through this web server" | The web server cannot reach the backend: `docker compose ps`, `docker compose logs backend`, `docker compose up -d`. Nginx re-resolves the backend per request and recovers by itself once it is healthy again. |
| CORS or "wrong API URL" errors | Not expected: the UI and API share one origin. If you built the frontend yourself with a non-empty `VITE_API_BASE_URL`, you are no longer in this design. |
| Permission errors on `/data/...` | Compose volumes inherit the image's ownership (uid 10001). Bind mounts must be writable by uid 10001. |
| Experiments view: tracking `no_store` | No evaluation has been tracked in the container yet (section 8). Reading never creates the store. |
| Experiments view cannot read artifacts after you changed paths | An MLflow experiment keeps the artifact location recorded when it was created (`file:///data/mlflow/artifacts`). Do not move the volume contents; keep `MLFLOW_ARTIFACT_ROOT` as is. |
| Ingestion works but questions find nothing | Check the document selection in the UI; `/health` → `vector_store` detail shows the point count. After changing `EMBEDDING_MODEL`: `Qdrant collection … stores N-dimensional vectors…` means a different `QDRANT_COLLECTION_NAME` is needed. |
| Connection errors right after restarting a service | Transient: wait for `docker compose ps` to show `healthy` (the backend reconnects to a restarted Qdrant by itself — verified). |
| Disk or memory pressure | Docker Desktop → Settings → Resources. `docker system df` is read-only. `docker builder prune` frees build cache. Do not prune volumes. |
| A host dev server already runs | No conflict: they use 5173/8000 and a different store. |

## 11. Known limitations

- **Retrieval is not bit-identical across engines and platforms.** Dense scores agree to better than 4·10⁻⁷ and no gate decision differs (checked on all 173 benchmark questions, including 28 scores within ±0.01 of the 0.35 threshold). But the lexical half of the hybrid search orders candidates slightly differently: the Qdrant server vs the embedded store chose different evidence for **1 of 173** questions, and macOS vs Linux (both embedded) for **2 of 173**, always the last evidence slot between chunks that all passed the gate. The accepted Stage 5.7 benchmark results were measured with the embedded store on macOS; the Docker deployment uses the server.
- Images were built and run only on linux/arm64. On x86-64 the build works in principle (the PyTorch CPU wheel index also serves amd64) but is untested.
- `GET /health` health checks mean "process is up", not "model reachable" (section 4).
- The backend image contains the Debian base's setuid binaries; `no-new-privileges` is set so they cannot be used to escalate.
- MLflow's automatic `Default` experiment points at `/app/backend/mlruns/0` (read-only); nothing logs to it.
- No TLS, authentication, rate limiting, or resource limits; bind address defaults to loopback for that reason.
