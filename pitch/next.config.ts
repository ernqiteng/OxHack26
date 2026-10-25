import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "export",
  // `npm run build` writes the static site to out/, so it never clobbers a running dev server's .next/.
  distDir: process.env.NEXT_DIST_DIR ?? ".next",
  images: { unoptimized: true },
  devIndicators: false,
};

export default nextConfig;
