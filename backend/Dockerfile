# ── Stage 1: Build the Rust binary ───────────────────────────────────────────
# 1.83, not 1.78: core/Cargo.lock pins rayon 1.12.0 / rayon-core 1.13.0, whose
# declared MSRV is 1.80. On 1.78 cargo refuses the lockfile and the build dies
# here, before Python is ever reached.
FROM rust:1.83-slim AS rust-builder
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

# CPU-only torch, installed before requirements.txt so sentence-transformers
# finds its torch dependency already satisfied and never resolves its own.
#
# The default PyPI wheel drags the CUDA stack in: ~2.5 GB of nvidia-* packages
# that cannot run in this container. The pin carries the +cpu local version
# deliberately -- only the PyTorch index serves it, so a wrong resolution fails
# the build loudly instead of silently shipping CUDA. --extra-index-url is
# there for torch's own dependencies (sympy, networkx, filelock), which the
# PyTorch index does not host.
RUN pip install --no-cache-dir \
    --index-url https://download.pytorch.org/whl/cpu \
    --extra-index-url https://pypi.org/simple \
    torch==2.13.0+cpu

# Install Python requirements
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend application source code.
#
# main.py imports config, indexer, lexical and retrieval at module scope. All
# four have to be here or the container dies on first import. seed_real_structure.py
# moved to backend/scripts/ and is not a runtime dependency, so it is gone.
COPY backend/main.py .
COPY backend/config.py .
COPY backend/indexer.py .
COPY backend/lexical.py .
COPY backend/retrieval.py .

# Environment variables
ENV PORT=8000
ENV HOST=0.0.0.0

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
