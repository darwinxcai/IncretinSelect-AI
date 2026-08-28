import { defineConfig } from "@playwright/test";

const host = "127.0.0.1";
const port = 4173;

export default defineConfig({
  testDir: "tests/browser",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI
    ? [["github"], ["html", { open: "never", outputFolder: "playwright-report" }]]
    : "list",
  use: {
    baseURL: `http://${host}:${port}`,
    browserName: "chromium",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    video: "retain-on-failure",
  },
  webServer: {
    command: `python -m http.server ${port} --bind ${host} --directory docs`,
    url: `http://${host}:${port}`,
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
});
