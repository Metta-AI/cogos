import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  async rewrites() {
    return [
      { source: "/api/:path*", destination: "http://127.0.0.1:8100/api/:path*" },
      { source: "/ws/:path*", destination: "http://127.0.0.1:8100/ws/:path*" },
      { source: "/healthz", destination: "http://127.0.0.1:8100/healthz" },
    ];
  },
};

export default nextConfig;
