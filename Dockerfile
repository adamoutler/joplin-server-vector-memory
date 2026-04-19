# ==========================================
# Stage 1: Builder (Heavy dependencies)
# ==========================================
FROM node:20-bookworm AS builder

# Install Python and SQLite build dependencies
RUN apt-get update && apt-get upgrade -y && apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    build-essential \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Setup Python virtual environment
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Python dependencies first (leverage caching)
COPY server/requirements.txt ./server/
RUN pip install --upgrade setuptools wheel && \
    pip install --no-cache-dir -r server/requirements.txt

# Install Node dependencies
COPY client/package*.json ./client/
RUN cd client && npm ci --build-from-source=sqlite3 && find . -type f -name "Cargo.lock" -delete

# ==========================================
# Stage 2: Final Runtime (Lightweight)
# ==========================================
FROM node:20-bookworm-slim

# Install runtime dependencies for python and sqlite3
RUN apt-get update && apt-get install -y \
    python3 \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the compiled python virtual environment
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy the node modules
COPY --from=builder /app/client/node_modules ./client/node_modules

# Copy full application code
COPY . .

# Environment setup
ENV PYTHONUNBUFFERED=1
ENV BACKEND_URL="http://127.0.0.1:8000"
ENV DATA_DIR="/app/data"
ENV SQLITE_DB_PATH="/app/data/vector_memory.sqlite"

EXPOSE 3000
EXPOSE 8000

RUN chmod +x entrypoint.sh

ENTRYPOINT ["./entrypoint.sh"]
