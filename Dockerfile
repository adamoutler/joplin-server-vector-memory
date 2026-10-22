# ==========================================
# Stage 1: Base Python (Heavy Dependencies)
# These change rarely and are huge.
# ==========================================
FROM node:22-bookworm-slim AS python-base

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install massive ML libraries separately for caching
RUN pip install --no-cache-dir --upgrade pip "setuptools>=84.0.0" wheel && \
    pip install --no-cache-dir \
      torch==2.13.0 \
      sentence-transformers==5.6.0 \
      transformers==5.10.0 \
      fsspec==2026.6.0 \
      einops==0.8.2 \
      --extra-index-url https://download.pytorch.org/whl/cpu

# Pre-download the model into the image to avoid runtime downloads
# This caches the small fallback model
ENV HF_HOME="/opt/hf_cache"
RUN python3 -c "from sentence_transformers import SentenceTransformer; \
    SentenceTransformer('all-MiniLM-L6-v2')"

# ==========================================
# Stage 2: Builder (Node & Remaining Python)
# ==========================================
FROM node:22-bookworm-slim AS builder

# Install build dependencies for native modules (sqlite3)
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the venv with heavy ML libraries from stage 1
COPY --from=python-base /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install remaining Python dependencies from requirements.txt
COPY server/requirements.txt ./server/
RUN pip install --no-cache-dir -r server/requirements.txt --extra-index-url https://download.pytorch.org/whl/cpu

# Install Node dependencies and compile sqlite3
COPY client/package*.json ./client/
COPY client/vendor ./client/vendor
RUN cd client && \
    npm ci --build-from-source=sqlite3 --omit=dev && \
    find . -type f -name "Cargo.lock" -delete && \
    npm cache clean --force

# ==========================================
# Stage 3: Testing (Optional, dev dependencies)
# ==========================================
FROM builder AS tester

USER root
COPY server/requirements-dev.txt ./server/
RUN pip install --no-cache-dir -r server/requirements-dev.txt
USER node

# ==========================================
# Stage 4: Final Runtime (Lightweight Production)
# ==========================================
FROM node:22-bookworm-slim AS runtime

# Install runtime essentials and upgrade OS packages for security
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
    python3 \
    sqlite3 \
    curl \
    ca-certificates \
    gosu \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the fully populated python virtual environment
COPY --chown=node:node --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Hardening: Remove unused package managers (npm, corepack, pip, wheel) from production runtime
# Eliminates attack surface and vendored package manager CVEs in the final image
RUN rm -rf /usr/local/lib/node_modules/npm \
           /usr/local/lib/node_modules/corepack \
           /usr/local/bin/npm \
           /usr/local/bin/npx \
           /usr/local/bin/corepack \
           /opt/venv/lib/python3.11/site-packages/pip* \
           /opt/venv/lib/python3.11/site-packages/wheel* \
           /opt/venv/bin/pip* \
           /opt/venv/bin/wheel*

# Copy the Hugging Face cache containing pre-downloaded models
COPY --chown=node:node --from=python-base /opt/hf_cache /opt/hf_cache
ENV HF_HOME="/opt/hf_cache"
ENV HF_HUB_OFFLINE=1

# Copy the node modules
COPY --chown=node:node --from=builder /app/client/node_modules ./client/node_modules

# Copy full application code
COPY --chown=node:node . .

# Environment setup
ENV PYTHONUNBUFFERED=1
ENV BACKEND_URL="http://127.0.0.1:8000"
ENV DATA_DIR="/app/data"
ENV SQLITE_DB_PATH="/app/data/vector_memory.sqlite"

# Expose Node (3000) and FastMCP (8000) ports
EXPOSE 3000
EXPOSE 8000

RUN chmod +x entrypoint.sh && mkdir -p /app/data && chown -R node:node /app/data

# Note: We start as root so the entrypoint can fix ownership of
# volume-mounted /app/data, then drop to 'node' via gosu/exec.
ENTRYPOINT ["./entrypoint.sh"]
