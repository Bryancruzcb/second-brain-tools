# ── Stage 1: Build the Rust binary ───────────────────────────────────────────
FROM rust:1.78-slim AS rust-builder
WORKDIR /app
COPY core/ ./core/
WORKDIR /app/core
RUN cargo build --release

# ── Stage 2: Python runtime environment ──────────────────────────────────────
FROM python:3.11-slim
WORKDIR /app

# Install system dependencies (build-essential for compiling C/C++ packages like chroma)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy the compiled Rust binary from Stage 1 into the system PATH
COPY --from=rust-builder /app/core/target/release/vault-core /usr/local/bin/vault-core

# Install Python requirements
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend application source code
COPY backend/main.py .
COPY backend/seed_real_structure.py .

# Environment variables
ENV PORT=8000
ENV HOST=0.0.0.0

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
