import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "tests/e2e",
  use: { baseURL: "http://localhost:5192" },
  webServer: {
    command: "npx vite build && npx vite preview --port 5192 --strictPort",
    url: "http://localhost:5192",
    reuseExistingServer: true,
    timeout: 120_000,
  },
});
