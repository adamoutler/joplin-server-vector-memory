# ==========================================
# Stage 1: Base Python (Heavy Dependencies)
# These change rarely and are huge.
# ==========================================
FROM node:20-bookworm-slim AS python-base

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    build-essential \
    && rm -rf /var/lib/apt/lists/* && \
    npm install -g npm@latest

RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install massive ML libraries separately for caching
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir torch sentence-transformers einops

# Pre-download the models into the image to avoid runtime downloads
# This caches both the small fallback and the high-quality Nomic model
ENV HF_HOME="/opt/hf_cache"
RUN python3 -c "from sentence_transformers import SentenceTransformer; \
    SentenceTransformer('all-MiniLM-L6-v2'); \
    SentenceTransformer('nomic-ai/nomic-embed-text-v1.5', trust_remote_code=True)"

# ==========================================
# Stage 2: Builder (Node & Remaining Python)
# ==========================================
FROM node:20-bookworm AS builder

# Install build dependencies for native modules (sqlite3)
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    build-essential \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the venv with heavy ML libraries from stage 1
COPY --from=python-base /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install remaining Python dependencies from requirements.txt
COPY server/requirements.txt ./server/
RUN pip install --no-cache-dir -r server/requirements.txt

# Install Node dependencies and compile sqlite3
COPY client/package*.json ./client/
RUN cd client && \
    npm ci --build-from-source=sqlite3 && \
    find . -type f -name "Cargo.lock" -delete && \
    npm cache clean --force

# ==========================================
# Stage 3: Final Runtime (Lightweight)
# ==========================================
FROM node:20-bookworm-slim

# Install runtime essentials and upgrade OS packages for security
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
    python3 \
    sqlite3 \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/* && \
    npm install -g npm@latest

WORKDIR /app

# Copy the fully populated python virtual environment
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy the Hugging Face cache containing pre-downloaded models
COPY --from=python-base /opt/hf_cache /opt/hf_cache
ENV HF_HOME="/opt/hf_cache"
ENV HF_HUB_OFFLINE=1

# Copy the node modules
COPY --from=builder /app/client/node_modules ./client/node_modules

# Copy full application code
COPY . .

# Environment setup
ENV PYTHONUNBUFFERED=1
ENV BACKEND_URL="http://127.0.0.1:8000"
ENV DATA_DIR="/app/data"
ENV SQLITE_DB_PATH="/app/data/vector_memory.sqlite"

# Expose Node (3000) and FastMCP (8000) ports
EXPOSE 3000
EXPOSE 8000

RUN chmod +x entrypoint.sh

ENTRYPOINT ["./entrypoint.sh"]
