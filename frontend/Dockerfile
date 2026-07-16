# ── Stage 1: Build Next.js application ────────────────────────────────────────
FROM node:20-alpine AS builder
WORKDIR /app

# Copy dependency configs
COPY package*.json ./
RUN npm ci

# Copy source files
COPY . .

# Set environment for production build
ENV NEXT_PUBLIC_API_URL=http://localhost:8000
RUN npm run build

# ── Stage 2: Production runner ────────────────────────────────────────────────
FROM node:20-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV PORT=3000

# Copy necessary files from build stage
COPY --from=builder /app/package*.json ./
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/node_modules ./node_modules

EXPOSE 3000

CMD ["npm", "start"]
