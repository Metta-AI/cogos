import type { NextConfig } from "next";

const isExport = process.env.NEXT_EXPORT === "1";
const bePort = process.env.DASHBOARD_BE_PORT || "8100";

const nextConfig: NextConfig = {
  output: isExport ? "export" : "standalone",
  ...(!isExport && {
    async rewrites() {
      return [
        { source: "/api/:path*", destination: `http://127.0.0.1:${bePort}/api/:path*` },
        { source: "/ws/:path*", destination: `http://127.0.0.1:${bePort}/ws/:path*` },
        { source: "/healthz", destination: `http://127.0.0.1:${bePort}/healthz` },
        { source: "/admin/:path*", destination: `http://127.0.0.1:${bePort}/admin/:path*` },
      ];
    },
    async headers() {
      return [
        {
          // Disable CDN caching for HTML pages — only cache hashed static assets
          source: "/((?!_next/static/).*)",
          headers: [
            { key: "Cache-Control", value: "no-store, must-revalidate" },
            { key: "CDN-Cache-Control", value: "no-store" },
          ],
        },
      ];
    },
  }),
};

export default nextConfig;
