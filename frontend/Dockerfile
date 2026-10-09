# ── Stage 1: Build Next.js application ────────────────────────────────────────
# Node stays the base because next's bin runs under node (same as CI, which
# pins node 20 alongside bun). Bun is copied in at the version package.json
# pins in packageManager, and installs from the committed bun.lock.
FROM node:20-alpine AS builder
COPY --from=oven/bun:1.4.2-alpine /usr/local/bin/bun /usr/local/bin/bun
WORKDIR /app

# Copy dependency configs
COPY package.json bun.lock ./
RUN bun install --frozen-lockfile

# Copy source files
COPY . .

# The browser calls same-origin /api/* and Next.js proxies it to the backend.
# Rewrites are fixed at build time, so the backend address is a build arg
# (docker-compose passes the backend service's address).
ARG ATLAS_BACKEND_URL=http://127.0.0.1:8000
ENV ATLAS_BACKEND_URL=${ATLAS_BACKEND_URL}
RUN bun run build

# ── Stage 2: Production runner ────────────────────────────────────────────────
FROM node:20-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV PORT=3000

# Copy necessary files from build stage
COPY --from=builder /app/package.json ./
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/node_modules ./node_modules

EXPOSE 3000

# Same flags as the "start" script, run by node directly so SIGTERM reaches
# the server without a package manager in between.
CMD ["node", "node_modules/next/dist/bin/next", "start", "--hostname", "0.0.0.0", "--port", "3000"]
