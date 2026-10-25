# RAGGuard API image (Stage 6, D-075).
#
# Build context: the repository root (the allow-list in .dockerignore decides what enters it).
#   docker build -f deployment/backend.Dockerfile -t ragguard-backend .
# Targets: `runtime` (default, the last stage) and `test` (adds pytest/ruff/mypy and the
#   tests, for `docker build --target test` checks; never used by compose.yaml).
#
# The image contains the API, the evaluation CLI (it needs MLflow, hence requirements-eval.txt;
# the query path still imports MLflow lazily and never on its own) and the evaluation
# datasets. It contains no model weights, no database, no index and no credentials.

FROM python:3.13-slim-trixie AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH

# Non-root user; /data is where the named volumes of compose.yaml are mounted. A new named
# volume inherits the ownership of its mount point from the image, so these folders are
# created here and owned by the runtime user.
RUN groupadd --system --gid 10001 ragguard \
 && useradd --system --uid 10001 --gid ragguard --home-dir /home/ragguard --create-home \
        --shell /usr/sbin/nologin ragguard \
 && mkdir -p /data/hf-cache /data/mlflow/artifacts /data/reports \
 && chown -R ragguard:ragguard /data

# --- dependencies: the same pinned versions as the host development environment ---------
FROM base AS deps
# torch comes from PyTorch's official CPU wheel index. PyPI's Linux wheels (arm64 AND amd64)
# are CUDA builds (torch 2.14.1+cu130 plus ~4 GB of nvidia/triton libraries), which are dead
# weight in a Docker Desktop VM without a GPU: that made the first image 10 GB. The version is
# read from requirements.txt, so it stays the single source of truth. Build with
# --build-arg TORCH_INDEX_URL= (empty) to take torch from PyPI instead, e.g. for a GPU host.
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
COPY backend/requirements.txt backend/requirements-eval.txt /tmp/requirements/
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m venv /opt/venv \
 && TORCH_PIN="$(grep -E '^torch==' /tmp/requirements/requirements.txt)" \
 && pip install ${TORCH_INDEX_URL:+--index-url "$TORCH_INDEX_URL"} "$TORCH_PIN" \
 && pip install -r /tmp/requirements/requirements-eval.txt

# --- application code (owned by root, read-only for the runtime user) -------------------
FROM base AS app
COPY --from=deps /opt/venv /opt/venv
COPY backend/app /app/backend/app
COPY evaluation/datasets /app/evaluation/datasets
# `config.REPO_ROOT` is three levels above config.py, i.e. /app: that is where the
# evaluation datasets are looked up by default.
WORKDIR /app/backend

# --- test: the host checks, run in the container environment ---------------------------
FROM app AS test
# requirements-dev.txt includes requirements-eval.txt, which includes requirements.txt (-r).
COPY backend/requirements.txt backend/requirements-eval.txt backend/requirements-dev.txt /tmp/requirements/
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r /tmp/requirements/requirements-dev.txt
COPY backend/pyproject.toml /app/backend/pyproject.toml
COPY backend/tests /app/backend/tests
USER 10001:10001
CMD ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"]

# --- runtime (default) ---------------------------------------------------------------
FROM app AS runtime
# Container-internal data locations (the volumes of compose.yaml mount here). Deploy-time
# settings (URLs, provider, model, ports) are set by compose.yaml, not here.
ENV RAGGUARD_RUNTIME=docker \
    HF_HOME=/data/hf-cache \
    MLFLOW_TRACKING_URI=sqlite:////data/mlflow/mlflow.db \
    MLFLOW_ARTIFACT_ROOT=/data/mlflow/artifacts \
    EVALUATION_RESULTS_DIR=/data/reports

USER 10001:10001
EXPOSE 8000

# Liveness of the API process: GET /health answers 200 while the app runs, even when Qdrant
# or the generation provider is unreachable (their state is in the response body, not in
# the status code). The probe uses the interpreter, so no extra OS package is needed.
HEALTHCHECK --interval=30s --timeout=15s --start-period=40s --retries=3 \
    CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=12).status == 200 else 1)"]

# Exec form: uvicorn is PID 1 (or the child of compose's init) and receives SIGTERM directly.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
