# syntax=docker/dockerfile:1

FROM node:22-bookworm-slim AS web-build
WORKDIR /web
COPY money_graph/web/package.json money_graph/web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY money_graph/web/ ./
RUN npm run build

FROM python:3.12-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MONEY_GRAPH_PROJECTS=/data/projects

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 libstdc++6 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin app \
    && install -d -o app -g app /data /data/projects

WORKDIR /app/money_graph
COPY money_graph/requirements.txt money_graph/requirements-ai.txt ./
# Install the optional SDK so a runtime API key is sufficient to enable AI.
RUN python -m pip install --no-cache-dir -r requirements-ai.txt

COPY money_graph/api/ ./api/
COPY money_graph/mg/ ./mg/
COPY money_graph/data/ ./data/
COPY money_graph/ui/ ./ui/
COPY money_graph/vendor/ ./vendor/
COPY money_graph/config.json money_graph/serve.py money_graph/run.py money_graph/check.py ./
COPY --from=web-build /web/dist/ ./web/dist/

USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import json, urllib.request; response = urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3); assert response.status == 200 and json.load(response)['ok'] is True"]

# The job registry and executor are process-local: run one API worker.
CMD ["python", "-m", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log", "--no-proxy-headers"]
