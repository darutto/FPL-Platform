import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  // Backend URL is consumed server-side only (proxy route).
  // Set FPL_BACKEND_URL in .env.local for local dev.
  // Default: http://localhost:8000 (matches fpl_server.py default)

  // Local dev only: lets a phone on the same LAN load the dev server via its
  // network IP (Next.js 15 otherwise only warns, it doesn't block — but this
  // silences the warning and is required in a future major version).
  allowedDevOrigins: ['10.0.0.177'],
};

export default nextConfig;
