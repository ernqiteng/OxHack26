import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "export",
  // `npm run build` writes the static site to out/, so it never clobbers a running dev server's .next/.
  distDir: process.env.NEXT_DIST_DIR ?? ".next",
  // On the Vultr box the site lives at /app/ (the presentation site has /). Empty locally.
  basePath: process.env.NEXT_PUBLIC_BASE_PATH ?? "",
  images: { unoptimized: true },
  devIndicators: false,
};

export default nextConfig;
