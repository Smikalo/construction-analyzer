/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  reactStrictMode: true,
  experimental: {
    optimizePackageImports: ["framer-motion", "react-markdown"],
  },
};

export default nextConfig;
