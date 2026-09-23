import { defineConfig } from "@playwright/test";

const externalBaseURL = process.env.PLAYWRIGHT_BASE_URL?.trim();

export default defineConfig({
  testDir: "./e2e",
  timeout: 180000,
  workers: 1,
  use: {
    baseURL: externalBaseURL || "http://127.0.0.1:8000",
    headless: true,
    viewport: { width: 1600, height: 1000 },
    launchOptions: process.env.PLAYWRIGHT_BROWSER
      ? { executablePath: process.env.PLAYWRIGHT_BROWSER }
      : {},
  },
  // An explicit URL targets an already started service, for example Docker.
  webServer: externalBaseURL
    ? undefined
    : {
        command: "python ../serve.py",
        url: "http://127.0.0.1:8000/api/health",
        reuseExistingServer: !process.env.CI,
        timeout: 60000,
      },
  reporter: "list",
});
