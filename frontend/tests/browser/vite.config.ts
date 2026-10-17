import { defineConfig } from "vite";
import path from "node:path";

export default defineConfig({
  resolve: { alias: { "@": path.resolve(__dirname, "../..") } },
  esbuild: { jsx: "automatic", jsxImportSource: "react" },
  define: {
    "process.env.NEXT_PUBLIC_API_URL": JSON.stringify("http://127.0.0.1:4173/api"),
    "process.env.NEXT_PUBLIC_AUTH_ENABLED": JSON.stringify("true"),
  },
});
