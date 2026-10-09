import { hostname } from "node:os";
import type { NextConfig } from "next";

/**
 * Where the Next.js server forwards the browser's same-origin /api/* calls.
 * Server-side only: the browser never sees it, so the page works from any
 * device that can reach this server (e.g. over Tailscale) while the backend
 * stays on 127.0.0.1. Read when the dev server starts or `next build` runs.
 */
const backendUrl = (
  process.env.ATLAS_BACKEND_URL || "http://127.0.0.1:8000"
).replace(/\/+$/, "");

/**
 * Hosts allowed to use dev-only resources (HMR socket, /_next in dev) when
 * the dev server is opened from another device: Tailscale MagicDNS names,
 * tailnet IPs and this machine's name, plus ATLAS_DEV_ORIGINS
 * (comma-separated). No effect on `next start`.
 */
const allowedDevOrigins = [
  "**.ts.net",
  "100.*.*.*",
  hostname().toLowerCase(),
  ...(process.env.ATLAS_DEV_ORIGINS || "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean),
];

const nextConfig: NextConfig = {
  allowedDevOrigins,
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${backendUrl}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
