import { test, expect, type APIRequestContext } from "@playwright/test";

/**
 * 前端冒烟五景(候选清单落地批 C):跑在已启动的本地服务(8600)上。
 * 零真 AI 依赖——只走 UI 导航与纯算法功能;写操作(景4)在小测试书
 * 「M2关账书」内建删子题,建后即删=零残留,用户创作书零触碰。
 *
 * 书存在性守卫:CI 全新空库无这些书 → test.skip 优雅跳过(本地有书才实跑);
 * 服务由 backend uvicorn 提供(playwright.config reuseExistingServer);
 * CSRF 白名单含 127.0.0.1:8600,页面内 fetch 不受影响。
 */

async function hasBook(request: APIRequestContext, name: string): Promise<boolean> {
  const r = await request.get("/api/overview");
  if (!r.ok()) return false;
  const data = await r.json();
  return (data.projects ?? []).some((p: { name: string }) => p.name === name);
}

test.describe("Soulspring 冒烟", () => {
  test("景1 总览加载:标题与书架可见", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Soulspring" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "书架" })).toBeVisible();
    await expect(page.getByRole("button", { name: "+ 新建书(F0 向导)" })).toBeVisible();
  });

  test("景2 进入书工作区:三栏与大纲树在位", async ({ page, request }) => {
    test.skip(!await hasBook(request, "余期"), "无余期书(CI 空库)");
    await page.goto("/");
    await page.getByRole("button", { name: "余期", exact: true }).click();
    await page.waitForTimeout(1200);
    await expect(page.getByText("层级:总纲 → 卷", { exact: false })).toBeVisible();
    for (const tab of ["大纲树", "档案库", "书籍信息", "构思"]) {
      await expect(page.locator(".col-switch, main").getByRole("button", { name: tab })
        .first()).toBeVisible();
    }
  });

  test("景3 算法体检(纯算法零 LLM):面板可开且八项检查渲染", async ({ page, request }) => {
    test.skip(!await hasBook(request, "余期"), "无余期书(CI 空库)");
    await page.goto("/");
    await page.getByRole("button", { name: "余期", exact: true }).click();
    await page.waitForTimeout(1200);
    await page.getByRole("button", { name: /算法体检/ }).click();
    await page.waitForTimeout(1000);
    await expect(page.locator(".algo-panel")).toBeVisible();
    await expect(page.locator(".algo-panel").getByText("断头章")).toBeVisible();
    await expect(page.locator(".algo-panel").getByText("章密度失衡")).toBeVisible();
  });

  test("景4 大纲建删子题(小测试书内,零残留零真 AI)", async ({ page, request }) => {
    test.skip(!await hasBook(request, "M2关账书"), "无 M2关账书(CI 空库)");
    await page.goto("/");
    await page.getByRole("button", { name: "M2关账书" }).click();
    await page.waitForTimeout(1200);   // 小树全量渲染,无懒挂载/折叠
    const addBtn = page.getByRole("button", { name: /^\+(场景\/)?子题$/ })
      .locator("visible=true").first();
    await addBtn.click();
    const kindSelect = page.locator("select:has(option[value='topic'])")
      .locator("visible=true").first();
    await kindSelect.selectOption("topic");
    const input = page.locator("input[placeholder='新子题标题']")
      .locator("visible=true").first();
    await input.fill("__e2e_topic");
    await page.getByRole("button", { name: "添加", exact: true })
      .locator("visible=true").first().click();
    await expect(page.getByRole("button", { name: "__e2e_topic" })).toBeVisible();
    // 删除(行内删→uiConfirm 行内确认条 .confirm-bar)
    const row = page.locator(".tree-row", { hasText: "__e2e_topic" }).first();
    await row.getByRole("button", { name: "删" }).click();
    await page.waitForTimeout(400);
    await page.locator(".confirm-bar .confirm-actions button").first().click();
    await expect(page.getByRole("button", { name: "__e2e_topic" })).toBeHidden();
  });

  test("景5 导出 md 可下载(零 LLM)", async ({ request }) => {
    const r = await request.get("/api/overview");
    test.skip(!r.ok(), "服务不可达");
    const data = await r.json();
    const target = data.projects?.find((p: { name: string }) => p.name === "余期");
    test.skip(!target, "无余期书(CI 空库)");
    const res = await request.get(`/api/books/${target.id}/export?fmt=md`);
    expect(res.status()).toBe(200);
    const text = await res.text();
    expect(text.startsWith("《余期》")).toBe(true);
  });
});
