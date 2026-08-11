import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Evita que o Next confunda a raiz do workspace por causa de um
  // package-lock.json solto em ~/ (de outro projeto, sem relação com este).
  outputFileTracingRoot: path.join(__dirname),
  images: {
    remotePatterns: [
      {
        protocol: "https",
        hostname: "media.pelando.com.br",
      },
    ],
  },
};

export default nextConfig;
