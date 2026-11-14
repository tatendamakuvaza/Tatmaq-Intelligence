import type { NextConfig } from "next";

// Where the Next.js server forwards API calls. The browser only ever talks to this
// web app's own origin (/api/...), so in development there is no CORS to configure
// and the API does not need to be reachable from the user's machine.
const apiTarget = (process.env.API_PROXY_TARGET ?? "http://127.0.0.1:8000").replace(/\/$/, "");

// Uploads to local file storage pass through the /api proxy. Next.js holds a proxied
// request body in memory and by default cuts it off at 10 MB, which makes a larger upload
// hang and then fail. Allow the API's own limit plus headroom, and give slow connections
// time to finish. (In production, uploads go straight to Supabase Storage or to the API's
// own origin, not through this proxy: see NEXT_PUBLIC_API_BASE_URL.)
const maxUploadMb = Number(process.env.MAX_UPLOAD_MB ?? 50);

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  experimental: {
    proxyClientMaxBodySize: `${maxUploadMb + 4}mb`,
    proxyTimeout: 15 * 60 * 1000,
  },
  // Lets the development server be opened through a tunnel or preview host.
  allowedDevOrigins: (process.env.ALLOWED_DEV_ORIGINS ?? "*.e2b.app").split(",").map((origin) => origin.trim()),
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiTarget}/:path*` }];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
        ],
      },
    ];
  },
};

export default nextConfig;
