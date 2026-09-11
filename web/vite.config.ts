import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

export default defineConfig(({ mode }) => {
  const configDirectory = fileURLToPath(new URL(".", import.meta.url));
  const env = loadEnv(mode, configDirectory, "");
  return {
    plugins: [react()],
    server: {
      port: 5173,
      proxy: { "/api": { target: env.VITE_API_PROXY || "http://127.0.0.1:8000", changeOrigin: true } },
    },
  };
});
