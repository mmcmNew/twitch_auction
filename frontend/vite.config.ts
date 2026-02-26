import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: "autoUpdate",
      includeAssets: ["favicon.svg"],
      manifest: {
        name: "Twitch Auction",
        short_name: "Auction",
        description: "Interactive Twitch voting and auctions",
        theme_color: "#0b1020",
        background_color: "#0b1020",
        display: "standalone",
        start_url: "/",
        icons: [{ src: "/favicon.svg", sizes: "any", type: "image/svg+xml" }]
      }
    })
  ],
  server: {
    port: 5173
  }
});
