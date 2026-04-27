import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  // Backend URL is consumed server-side only (proxy route).
  // Set FPL_BACKEND_URL in .env.local for local dev.
  // Default: http://localhost:8000 (matches fpl_server.py default)
};

export default nextConfig;
