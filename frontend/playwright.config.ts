import { defineConfig } from "@playwright/test";

/**
 * 前端冒烟配置(候选清单落地批 C):
 * - baseURL=本地 8600;服务已在跑则复用(reuseExistingServer),CI 里自动拉起;
 * - 只跑 chromium(冒烟五景);失败截图留 gui-test-screenshots 旁证;
 * - CI 里 continue-on-error 由 workflow 控制(外部环境波动不阻塞主干)。
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  retries: 0,
  workers: 1,   // 串行:共享一份服务端数据
  use: {
    baseURL: "http://127.0.0.1:8600",
    screenshot: "only-on-failure",
  },
  webServer: process.env.E2E_SERVER_RUNNING
    ? undefined
    : {
        command: "cd ../backend && .venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8600",
        url: "http://127.0.0.1:8600/api/settings",
        reuseExistingServer: true,
        timeout: 30_000,
      },
  outputDir: "../gui-test-screenshots/e2e-artifacts",
});
