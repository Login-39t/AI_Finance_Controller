import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  typedRoutes: true,

  // Emits .next/standalone with a minimal server and only the node_modules
  // actually reached. It is what makes the container image ~150MB instead
  // of ~1GB, and it is a no-op for `next dev` and for Vercel, which does
  // its own tracing.
  output: "standalone",

  // The API is the only thing this app talks to, and it talks to it from
  // the server. Nothing here needs to reach a third-party origin, so the
  // policy can be this tight.
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "same-origin" },
          { key: "X-Frame-Options", value: "DENY" },
          {
            key: "Permissions-Policy",
            value: "camera=(), microphone=(), geolocation=(), payment=()",
          },
        ],
      },
    ];
  },
};

export default nextConfig;
