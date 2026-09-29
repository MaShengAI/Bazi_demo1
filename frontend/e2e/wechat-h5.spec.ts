import { expect, test, type Page } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.route("**/version.json*", (route) => route.fulfill({ json: { version: "0.2.0" } }));
  await page.route("**/api/v1/auth/me", (route) => route.fulfill({
    json: {
      enabled: false,
      authenticated: false,
      require_for_analysis: false,
      analysis_limit_per_24h: 0,
      user: null,
    },
  }));
  await page.route("**/api/v1/locations/provinces", (route) => route.fulfill({ json: [{ code: "31", name: "上海市" }] }));
  await page.route("**/api/v1/locations/cities?*", (route) => route.fulfill({ json: [{ code: 3101, name: "上海市", longitude: 121.47, latitude: 31.23 }] }));
});

test("微信尺寸下使用中文时间选择器且没有横向溢出", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator('input[type="datetime-local"]')).toHaveCount(0);
  const trigger = page.getByRole("button", { name: "请选择出生日期与时间" });
  await expect(trigger).toBeVisible();
  expect((await trigger.boundingBox())?.height).toBeGreaterThanOrEqual(44);

  await trigger.click();
  await page.getByLabel("年").selectOption("1988");
  await page.getByLabel("月").selectOption("7");
  await page.getByLabel("日").selectOption("10");
  await page.getByLabel("时", { exact: true }).selectOption("12");
  await page.getByLabel("分", { exact: true }).selectOption("30");
  await page.getByRole("button", { name: "确定" }).click({ force: true });
  await expect(page.getByRole("button", { name: /1988年7月10日 12:30/ })).toBeVisible();

  const layout = await page.evaluate(() => ({
    overflow: document.body.scrollWidth - document.documentElement.clientWidth,
    innerWidth: window.innerWidth,
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
    bodyWidth: document.body.scrollWidth,
    offenders: [...document.querySelectorAll<HTMLElement>("body *")]
      .map((element) => ({ element: `${element.tagName}.${element.className}`, rect: element.getBoundingClientRect().toJSON() }))
      .filter(({ rect }) => rect.right > window.innerWidth + 1 || rect.left < -1)
      .slice(0, 8),
  }));
  expect(layout.overflow, JSON.stringify(layout)).toBeLessThanOrEqual(1);
});

test("HTTP 202 后轮询并在刷新后恢复任务", async ({ page }) => {
  let statusRequests = 0;
  await mockCompletedAnalysis(page, () => statusRequests += 1);
  await page.goto("/");
  await fillBirthForm(page);
  await page.getByRole("button", { name: /排盘并生成 AI 分析/ }).click();
  await expect(page.getByText("八个主题，逐项生成")).toBeVisible();
  await expect(page.getByTestId("status-completed").first()).toBeVisible();
  const beforeReload = statusRequests;
  await page.reload();
  await expect(page.getByText("测试用户的四柱命盘")).toBeVisible();
  expect(statusRequests).toBeGreaterThan(beforeReload);
});

test("离线与弱网状态提供中文恢复提示", async ({ page, context }) => {
  await page.route("**/api/v1/locations/provinces", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 650));
    await route.fulfill({ json: [{ code: "31", name: "上海市" }] });
  });
  await page.goto("/");
  await expect(page.getByLabel("出生省份")).toBeDisabled();
  await expect(page.getByLabel("出生省份")).toBeEnabled();
  await context.setOffline(true);
  await page.evaluate(() => window.dispatchEvent(new Event("offline")));
  await expect(page.getByText(/网络已断开/)).toBeVisible();
  await context.setOffline(false);
  await page.evaluate(() => window.dispatchEvent(new Event("online")));
  await expect(page.getByText(/网络已断开/)).toHaveCount(0);
});

async function fillBirthForm(page: Page) {
  await page.getByLabel("姓名 选填").fill("测试用户");
  await page.getByRole("button", { name: "请选择出生日期与时间" }).click();
  await page.getByLabel("年").selectOption("1988");
  await page.getByLabel("月").selectOption("7");
  await page.getByLabel("日").selectOption("10");
  await page.getByLabel("时", { exact: true }).selectOption("12");
  await page.getByLabel("分", { exact: true }).selectOption("30");
  await page.getByRole("button", { name: "确定" }).click({ force: true });
  await page.getByLabel("出生省份").selectOption("上海市");
  await page.getByLabel("出生城市").selectOption("3101");
  await page.getByRole("checkbox", { name: /我已阅读并同意/ }).check();
}

async function mockCompletedAnalysis(page: Page, onStatus: () => void) {
  await page.route("**/api/v1/analyses", async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    await route.fulfill({ status: 202, json: { job_id: "job-e2e", chart_id: "chart-e2e", status: "pending", deduplicated: false } });
  });
  await page.route("**/api/v1/analyses/job-e2e/status", async (route) => {
    onStatus();
    await route.fulfill({ json: { ...analysisStatus, status: "completed", completed_sections: 8 } });
  });
  await page.route("**/api/v1/analyses/job-e2e", (route) => route.fulfill({ json: analysisResult }));
}

const pillar = {
  pillar: "戊辰", main_star: "食神", heavenly_stem: "戊", earthly_branch: "辰",
  hidden_stems: [{ stem: "戊", role: "本气", secondary_star: "食神" }], secondary_stars: ["食神"],
  na_yin: "大林木", star_fortune: "冠带", self_seat: "冠带", void: ["戌", "亥"], shen_sha: [],
};
const chart = {
  request: { name: "测试用户", gender: "male", birth_local_datetime: "1988-07-10T12:30", location_id: 3101 },
  location: { location_id: 3101, province: "上海市", city: "上海市", name: "上海市", longitude: 121.47, latitude: 31.23, timezone_id: "Asia/Shanghai" },
  time_normalization: { input_wall_time: "1988-07-10T12:30", standard_local_time: "1988-07-10T12:30:00+08:00", true_solar_datetime: "1988-07-10T12:30:00+08:00", longitude_correction_seconds: 0, equation_of_time_seconds: 0 },
  pillars: { year: pillar, month: { ...pillar, pillar: "己未" }, day: { ...pillar, pillar: "丙寅", main_star: "日主" }, hour: { ...pillar, pillar: "甲午" } },
  luck_direction: { direction: "forward", direction_reason: "阳年生男，顺行" },
  luck_start: { reference_jie: "立秋", start_age: { years: 9, months: 4, days: 19, hours: 0, minutes: 0, seconds: 0 }, start_datetime: "1997-11-29T12:30:00+08:00" },
  major_luck_cycles: [], ruleset_versions: { service: "0.3.0" },
};
const analysisStatus = {
  job_id: "job-e2e", chart_id: "chart-e2e", status: "pending", model_id: "deepseek-chat", prompt_version: "v1", request_hash: "hash", cancel_requested: false,
  completed_sections: 0, failed_sections: 0, total_sections: 8, created_at: "2026-08-04T00:00:00Z", started_at: null, finished_at: null,
};
const sections = ["性格特点", "恋爱情感", "子女关系", "学业发展", "事业发展", "财运建议", "健康提醒", "大运流年"].map((title, index) => ({
  code: `section-${index}`, title, status: "completed", content: "文化参考分析内容。", char_count: 1500, length_status: "ok", retry_count: 0, error: null, started_at: null, finished_at: null,
}));
const analysisResult = { ...analysisStatus, status: "completed", completed_sections: 8, finished_at: "2026-08-04T00:01:00Z", chart, sections, disclaimer: "传统文化参考，不构成专业建议。" };
