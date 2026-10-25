# RAGGuard web image (Stage 6, D-075): the production build served by Nginx, which also
# proxies the API paths to the backend service (same origin, so no CORS and no API URL
# baked into the browser bundle).
#
# Build context: the repository root (the allow-list in .dockerignore decides what enters it).
#   docker build -f deployment/frontend.Dockerfile -t ragguard-frontend .

# --- build: npm ci from the committed lockfile, then `npm run build` (tsc -b && vite build) ---
FROM node:24-alpine AS build
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci
COPY frontend/ ./
# An EMPTY base URL makes the bundle call the page's own origin (client.ts honours "").
# Pass a full URL only to build a bundle that talks to an API on another origin.
ARG VITE_API_BASE_URL=""
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

# --- runtime: Nginx without root privileges (listens on 8080) ---------------------------
FROM nginxinc/nginx-unprivileged:1.30-alpine AS runtime
COPY deployment/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["wget", "-q", "-O", "/dev/null", "http://127.0.0.1:8080/healthz"]
