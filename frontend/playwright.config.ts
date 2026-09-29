import { defineConfig } from "@playwright/test";

const weChatIOS = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 MicroMessenger/8.0.54";
const weChatAndroid = "Mozilla/5.0 (Linux; Android 15; Pixel 8 Build/AP3A) AppleWebKit/537.36 Chrome/122.0 Mobile Safari/537.36 MicroMessenger/8.0.54";

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  expect: { timeout: 5_000 },
  fullyParallel: true,
  workers: 3,
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:5173",
    launchOptions: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH
      ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH }
      : undefined,
    locale: "zh-CN",
    timezoneId: "Asia/Shanghai",
    hasTouch: true,
    isMobile: true,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  projects: [
    { name: "wechat-iphone", use: { viewport: { width: 390, height: 844 }, deviceScaleFactor: 3, userAgent: weChatIOS } },
    { name: "wechat-android", use: { viewport: { width: 393, height: 851 }, deviceScaleFactor: 2.75, userAgent: weChatAndroid } },
    { name: "wechat-small", use: { viewport: { width: 320, height: 568 }, deviceScaleFactor: 2, userAgent: weChatAndroid } },
  ],
  webServer: {
    command: "pnpm dev",
    url: "http://127.0.0.1:5173",
    reuseExistingServer: true,
    timeout: 60_000,
  },
});
