import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./e2e",
  timeout: 180000,
  workers: 1,
  use: {
    baseURL: "http://127.0.0.1:8000",
    headless: true,
    viewport: { width: 1600, height: 1000 },
    launchOptions: {
      executablePath:
        process.env.PLAYWRIGHT_BROWSER ||
        "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    },
  },
  reporter: "list",
});
