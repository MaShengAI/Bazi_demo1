import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import { App } from "./App";
import { analysisFixture } from "./test/fixtures";
import { beginWechatLogin } from "./wechatLogin";

vi.mock("./wechatLogin", async importOriginal => ({
  ...await importOriginal<typeof import("./wechatLogin")>(), beginWechatLogin: vi.fn(),
}));

const auth = { enabled: true, authenticated: true, payments_enabled: true, require_for_analysis: true, analysis_limit_per_24h: 0, user: { id: "own", display_name: "自己", avatar_url: null } };
const chartId = "saved-free-chart";
const draftKey = "bazi.birth.session-draft.v1";
const report = { chart_id: chartId, job_id: null, status: "locked", name: "免费资料", birth_local_datetime: "1988-07-10T12:30", pillars: ["戊辰", "己未", "丙寅", "甲午"], completed_sections: 0, total_sections: 0, created_at: "2026-11-01T00:00:00Z" };
const request = { ...analysisFixture.chart.request, name: "免费资料", birth_calendar: "lunar" };
const chart = { ...analysisFixture.chart, request };
const json = (value: unknown) => new Response(JSON.stringify(value));

test("免费排盘立即进入账户列表；刷新同时显示命盘及锁定预览且没有付费写入", async () => {
  window.history.replaceState(null, "", "/#/chart");
  sessionStorage.setItem(draftKey, JSON.stringify({ payload: request, at: Date.now() }));
  const writes: string[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (init?.method === "POST") writes.push(url);
    return json(url.endsWith("/auth/me") ? auth
      : url.endsWith("/charts") ? { ...chart, saved_chart_id: chartId, analysis_job_id: null }
      : url.endsWith(`/charts/${chartId}`) ? { chart_id: chartId, job_id: null, request, chart }
      : url.endsWith("/me/reports") ? [report] : []);
  });
  const user = userEvent.setup(); const first = render(<App />);
  await user.click(screen.getByRole("button", { name: "恢复本次排盘" }));
  await screen.findByRole("heading", { name: "免费资料" });
  expect(window.location.hash).toBe(`#/chart/${chartId}`);
  await user.click(screen.getByRole("button", { name: "报告" }));
  expect(await screen.findByText("免费资料")).toBeVisible();
  expect(screen.queryByText("未解锁")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "查看解读" }));
  await screen.findByRole("heading", { name: "免费资料" });
  first.unmount(); render(<App />);
  await screen.findByRole("heading", { name: "免费资料" });
  expect(screen.queryByRole("button", { name: "基础命盘" })).not.toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "免费资料" })).toBeVisible();
  const preview = screen.getByRole("heading", { name: "详细解读内容介绍" });
  expect(preview).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "免费资料" }).compareDocumentPosition(preview) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(screen.getAllByRole("article")).toHaveLength(8);
  expect(screen.getAllByRole("button", { name: "解锁完整解读" })).toHaveLength(8);
  expect(writes).toEqual(["/api/v1/charts"]);
});

test("购买页不提供解读入口，返回免费报告后在详细解读解锁原命盘", async () => {
  window.history.replaceState(null, "", "/#/cards");
  sessionStorage.setItem(draftKey, JSON.stringify({ payload: request, chartId, at: Date.now() }));
  const writes: string[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (init?.method === "POST") writes.push(url);
    return json(url.endsWith("/auth/me") ? auth
      : url.endsWith("/payments/account") ? { balance: 1, mode: "mock", coupon: null, products: [], orders: [] }
      : url.endsWith(`/charts/${chartId}`) ? { chart_id: chartId, job_id: null, request, chart }
      : url.endsWith("/me/reports") ? [report]
      : url.endsWith(`/charts/${chartId}/analyses`) ? { job_id: analysisFixture.job_id, chart_id: chartId, status: "pending", deduplicated: false }
      : url.includes("/analyses/") ? analysisFixture : []);
  });
  const user = userEvent.setup(); render(<App />);
  await screen.findByText(/本地模拟支付/);
  expect(screen.queryByText("继续刚才的测算")).not.toBeInTheDocument();
  expect(screen.queryByText(/剩余.*张/)).not.toBeInTheDocument();
  expect(writes).toEqual([]);
  await user.click(screen.getByRole("button", { name: "报告" }));
  await user.click(await screen.findByRole("button", { name: "查看解读" }));
  await screen.findByRole("heading", { name: "免费资料" });
  expect(screen.queryByText("留一份完整解读")).not.toBeInTheDocument();
  await user.click(screen.getAllByRole("button", { name: "解锁完整解读" })[0]);
  await waitFor(() => expect(writes).toEqual([`/api/v1/charts/${chartId}/analyses`]));
  expect(sessionStorage.getItem(draftKey)).toBeNull();
});

test("微信内打开网站自动发起基础登录；登录返回后待处理的免费排盘只提交一次", async () => {
  vi.mocked(beginWechatLogin).mockClear();
  vi.spyOn(navigator, "userAgent", "get").mockReturnValue("Mobile MicroMessenger");
  vi.spyOn(globalThis, "fetch").mockImplementation(async () => json({ ...auth, authenticated: false, user: null }));
  const first = render(<App />);
  await waitFor(() => expect(beginWechatLogin).toHaveBeenCalledWith(true));
  first.unmount();
  sessionStorage.setItem("bazi.chart.pending-login.v1", JSON.stringify(request));
  const writes: string[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (init?.method === "POST") writes.push(url);
    return json(url.endsWith("/auth/me") ? auth
      : url.endsWith("/charts") ? { ...chart, saved_chart_id: chartId }
      : url.endsWith(`/charts/${chartId}`) ? { chart_id: chartId, job_id: null, request, chart } : []);
  });
  render(<App />);
  await screen.findByRole("heading", { name: "免费资料" });
  expect(writes).toEqual(["/api/v1/charts"]);
  expect(sessionStorage.getItem("bazi.chart.pending-login.v1")).toBeNull();
});

test("免费排盘保存时会话过期，保留资料并提示重新登录，不伪装成已保存", async () => {
  window.history.replaceState(null, "", "/#/chart");
  sessionStorage.setItem(draftKey, JSON.stringify({ payload: request, at: Date.now() }));
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.endsWith("/charts") && init?.method === "POST") return new Response(
      JSON.stringify({ error: { code: "authentication_required" } }), { status: 401 },
    );
    return json(url.endsWith("/auth/me") ? auth : []);
  });
  const user = userEvent.setup(); render(<App />);
  await user.click(screen.getByRole("button", { name: "恢复本次排盘" }));
  expect(await screen.findByRole("heading", { name: "登录已过期" })).toBeVisible();
  expect(screen.queryByRole("heading", { name: "免费资料" })).not.toBeInTheDocument();
  expect(JSON.parse(sessionStorage.getItem("bazi.chart.pending-login.v1") || "{}")).toEqual(request);
  await user.click(screen.getByRole("button", { name: "测算" }));
  expect(screen.getByRole("button", { name: "重新登录" })).toBeVisible();
});
