# Build with: docker build -f containers/harnesses.Dockerfile -t doc-intell-harnesses:pi-0.85.1_tau-0.4.3_codex-0.145.0 containers
# Only this directory is the build context: dataset, evaluators and credentials
# are deliberately absent from every image layer.
FROM node:24.13.0-bookworm-slim AS node
FROM python:3.12.12-slim-bookworm

ARG PI_VERSION=0.85.1
ARG TAU_VERSION=0.4.3
ARG CODEX_VERSION=0.145.0

COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && apt-get update \
    && apt-get install -y --no-install-recommends bash ca-certificates git poppler-utils ripgrep \
    && rm -rf /var/lib/apt/lists/* \
    && npm install --global "@earendil-works/pi-coding-agent@${PI_VERSION}" "@openai/codex@${CODEX_VERSION}" \
    && npm cache clean --force \
    && pip install --no-cache-dir "tau-ai==${TAU_VERSION}" "pypdf==6.0.0" "pdfplumber==0.11.7" \
    && pi --version && tau --version && codex --version \
    && mkdir -p /workspace/inputs /home/agent /run

LABEL org.doc-intell.pi.version="${PI_VERSION}" \
      org.doc-intell.tau.version="${TAU_VERSION}" \
      org.doc-intell.codex.version="${CODEX_VERSION}"

COPY entrypoint.py /opt/harness-entrypoint.py
COPY egress_proxy.py /opt/doc-intell/egress_proxy.py
ENV HOME=/home/agent PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /workspace
ENTRYPOINT ["python3", "/opt/harness-entrypoint.py"]
