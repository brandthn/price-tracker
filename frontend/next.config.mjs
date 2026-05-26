/** @type {import("next").NextConfig} */
const nextConfig = {
  // Standalone : `next build` produit `.next/standalone/` autosuffisant
  // (server.js + node_modules minimal) → image Docker légère pour Cloud Run.
  output: "standalone",

  images: {
    qualities: [75, 100],
    // Fiches OFF servies depuis images.openfoodfacts.org. Les remote patterns
    // historiques du template sont supprimés — pas utilisés ici.
    remotePatterns: [
      { protocol: "https", hostname: "images.openfoodfacts.org" },
      { protocol: "https", hostname: "static.openfoodfacts.org" },
    ],
  },
};

export default nextConfig;
