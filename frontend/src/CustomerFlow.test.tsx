import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import { App } from "./App";
import { analysisFixture } from "./test/fixtures";

const auth = { enabled: true, authenticated: true, require_for_analysis: true, analysis_limit_per_24h: 0, payments_enabled: true, user: { id: "user-own", display_name: "自己的微信昵称", avatar_url: null } };
const item = { job_id: analysisFixture.job_id, chart_id: analysisFixture.chart_id, name: "我的历史报告", birth_local_datetime: "1988-07-10T12:30", pillars: ["戊辰", "己未", "丙寅", "甲午"], status: "completed", completed_sections: 8, total_sections: 8, created_at: "2026-10-28T01:00:00Z" };

test("兑换成功后重新读取卡券，返回我的显示新余额，不创建支付订单", async () => {
  window.history.replaceState(null, "", "/#/redeem");
  let balance = 0, accountCalls = 0;
  const writes: string[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (init?.method === "POST") writes.push(url);
    if (url.endsWith("/auth/me")) return new Response(JSON.stringify(auth));
    if (url.endsWith("/payments/account")) {
      accountCalls++;
      return new Response(JSON.stringify({ balance, mode: "mock", coupon: null, coupons: [], products: [], orders: [] }));
    }
    if (url.endsWith("/redemptions")) {
      balance = 2;
      return new Response(JSON.stringify({ kind: "cards", value: 2, already_redeemed: false, redeemed_at: "2026-11-02T00:00:00Z", coupon_expires_at: null }));
    }
    return new Response("[]");
  });
  const user = userEvent.setup(); render(<App />);
  await user.type(await screen.findByLabelText("兑换码", { exact: true }), "ABCDE-FGHJK-LMNPQ-RSTUV");
  await user.click(screen.getByRole("button", { name: "确认兑换" }));
  await screen.findByText("兑换成功");
  await waitFor(() => expect(accountCalls).toBeGreaterThanOrEqual(2));
  await user.click(screen.getByRole("button", { name: "我的" }));
  expect(await screen.findByRole("button", { name: "2张解读卡" })).toBeVisible();
  expect(writes).toEqual(["/api/v1/redemptions"]);
});

test.each([false, true])("报告首次加载后切回时保留列表或空状态，后台刷新不闪提示（空列表：%s）", async empty => {
  window.history.replaceState(null, "", "/#/reports");
  let resolve!: (value: Response) => void;
  let nextResponse = new Promise<Response>(done => { resolve = done; });
  let historyCalls = 0;
  vi.spyOn(globalThis, "fetch").mockImplementation(async input => {
    const url = String(input);
    if (url.endsWith("/me/reports")) { historyCalls++; return nextResponse; }
    return new Response(JSON.stringify(url.endsWith("/auth/me") ? auth : []));
  });
  const user = userEvent.setup(); render(<App />);
  expect(await screen.findByText("正在读取报告…")).toBeVisible();
  expect(screen.queryByText("还没有解读报告")).not.toBeInTheDocument();
  resolve(new Response(JSON.stringify(empty ? [] : [item])));
  expect(await screen.findByText(empty ? "还没有解读报告" : "我的历史报告")).toBeVisible();
  await user.click(screen.getByRole("button", { name: "测算" }));
  nextResponse = new Promise<Response>(done => { resolve = done; });
  await user.click(screen.getByRole("button", { name: "报告" }));
  await waitFor(() => expect(historyCalls).toBe(2));
  expect(screen.getByText(empty ? "还没有解读报告" : "我的历史报告")).toBeVisible();
  expect(screen.queryByText("正在读取报告…")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "搜索" })).toBeDisabled();
  resolve(new Response(JSON.stringify([{ ...item, name: "刷新后的报告" }])));
  expect(await screen.findByText("刷新后的报告")).toBeVisible();
  expect(screen.getByRole("button", { name: "搜索" })).toBeEnabled();
});

test("报告姓名搜索只在提交时生效，清空后回车恢复全部报告", async () => {
  window.history.replaceState(null, "", "/#/reports");
  let historyCalls = 0;
  vi.spyOn(globalThis, "fetch").mockImplementation(async input => {
    const url = String(input);
    if (url.endsWith("/me/reports")) {
      historyCalls++;
      return new Response(JSON.stringify([
        { ...item, name: "张小甲" },
        { ...item, chart_id: "another-chart", job_id: null, status: "locked", name: "李小乙" },
      ]));
    }
    return new Response(JSON.stringify(url.endsWith("/auth/me") ? auth : []));
  });
  const user = userEvent.setup(); render(<App />);
  expect(await screen.findByText("张小甲")).toBeVisible();
  const input = screen.getByRole("searchbox", { name: "搜索报告" });
  const initialCalls = historyCalls;
  await user.type(input, " 张小甲 ");
  expect(screen.getByText("李小乙")).toBeVisible();
  expect(historyCalls).toBe(initialCalls);
  await user.click(screen.getByRole("button", { name: "搜索" }));
  await waitFor(() => expect(historyCalls).toBe(initialCalls + 1));
  expect(screen.getByText("张小甲")).toBeVisible();
  expect(screen.queryByText("李小乙")).not.toBeInTheDocument();
  await user.clear(input);
  expect(screen.queryByText("李小乙")).not.toBeInTheDocument();
  expect(historyCalls).toBe(initialCalls + 1);
  await user.keyboard("{Enter}");
  expect(await screen.findByText("李小乙")).toBeVisible();
  await waitFor(() => expect(historyCalls).toBe(initialCalls + 2));
});

test("报告静默刷新遇到登录过期时清除旧列表", async () => {
  window.history.replaceState(null, "", "/#/reports");
  let expired = false;
  vi.spyOn(globalThis, "fetch").mockImplementation(async input => {
    const url = String(input);
    if (url.endsWith("/me/reports")) return expired
      ? new Response(JSON.stringify({ error: { code: "authentication_required" } }), { status: 401 })
      : new Response(JSON.stringify([item]));
    return new Response(JSON.stringify(url.endsWith("/auth/me") ? auth : []));
  });
  const user = userEvent.setup(); render(<App />);
  expect(await screen.findByText("我的历史报告")).toBeVisible();
  await user.click(screen.getByRole("button", { name: "测算" }));
  expired = true;
  await user.click(screen.getByRole("button", { name: "报告" }));
  expect(await screen.findByRole("heading", { name: "登录已过期" })).toBeVisible();
  expect(screen.queryByText("我的历史报告")).not.toBeInTheDocument();
});

test("从列表删除指定出生资料，确认前不写入，并保留其他报告和本机任务", async () => {
  window.history.replaceState(null, "", "/#/reports");
  const saved = JSON.stringify({ jobId: analysisFixture.job_id, chartId: analysisFixture.chart_id });
  localStorage.setItem("bazi.analysis.task.v1", saved);
  let removed = false;
  const writes: string[] = [];
  const records = [{ ...item, job_id: "target-job", chart_id: "target-chart", name: "待删除资料" }, { ...item, job_id: "sibling-job", chart_id: "target-chart", name: "关联报告" }, item];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (init?.method === "DELETE") { writes.push(url); removed = true; return new Response(null, { status: 204 }); }
    const value = url.endsWith("/auth/me") ? auth : url.endsWith("/me/reports") ? records.filter(record => !removed || record.chart_id !== "target-chart") : url.includes("/analyses/") ? analysisFixture : [];
    return new Response(JSON.stringify(value));
  });
  const user = userEvent.setup(); render(<App />);
  const article = (await screen.findByText("待删除资料")).closest("article")!;
  const trigger = within(article).getByRole("button", { name: "删除报告" });
  await user.click(trigger);
  expect(screen.getByRole("heading", { name: "删除此报告？" })).toBeVisible();
  expect(screen.getByText("删除后此命盘的八字详细解读需再次使用解读卡，此操作无法撤销")).toBeVisible();
  expect(writes).toEqual([]);
  await user.click(screen.getByRole("button", { name: "返回" }));
  expect(screen.getByText("待删除资料")).toBeVisible(); expect(writes).toEqual([]);
  await user.click(trigger);
  await user.click(screen.getByRole("button", { name: "确认删除" }));
  await waitFor(() => expect(screen.queryByText("待删除资料")).not.toBeInTheDocument());
  expect(screen.queryByText("关联报告")).not.toBeInTheDocument();
  expect(screen.queryByText("出生信息及关联结果已删除。")).not.toBeInTheDocument();
  expect(screen.getByText("我的历史报告")).toBeVisible();
  expect(writes).toEqual(["/api/v1/charts/target-chart"]);
  expect(localStorage.getItem("bazi.analysis.task.v1")).toBe(saved);
});

test("删除失败时列表仍保留原报告", async () => {
  window.history.replaceState(null, "", "/#/reports");
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (init?.method === "DELETE") return new Response(JSON.stringify({ error: { message: "服务暂时不可用" } }), { status: 503 });
    return new Response(JSON.stringify(url.endsWith("/auth/me") ? auth : url.endsWith("/me/reports") ? [item] : []));
  });
  const user = userEvent.setup(); render(<App />);
  await user.click(await screen.findByRole("button", { name: "删除报告" }));
  await user.click(screen.getByRole("button", { name: "确认删除" }));
  await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
  expect(screen.getByRole("alert")).toBeVisible();
  expect(screen.getByText("我的历史报告")).toBeVisible();
});

test("三页切换保留表单；报告与卡券被动读取不会创建订单；退出清除本机任务", async () => {
  const user = userEvent.setup();
  const calls: string[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input); calls.push(`${init?.method || "GET"} ${url}`);
    let value: unknown = {};
    if (url.endsWith("/auth/me")) value = auth;
    else if (url.endsWith("/locations/provinces")) value = [];
    else if (url.endsWith("/me/reports")) value = [item];
    else if (url.endsWith("/payments/account")) value = { balance: 7, mode: "mock", coupon: { id: "c1", amount: 5000, status: "used", expires_at: "2026-11-02T00:00:00Z" }, products: [], orders: [] };
    else if (url.endsWith("/auth/logout")) return new Response(null, { status: 204 });
    else if (url.endsWith("/status") || url.includes("/analyses/")) value = analysisFixture;
    return new Response(JSON.stringify(value), { status: 200 });
  });
  render(<App />);
  await user.type(screen.getByLabelText(/姓名/), "保留的资料");
  await user.click(screen.getByRole("button", { name: "报告" }));
  expect(await screen.findByText("我的历史报告")).toBeInTheDocument();
  expect(screen.getByTitle("日柱 丙寅")).toHaveTextContent("日柱丙寅");
  expect(screen.getByRole("group", { name: "四柱" }).querySelectorAll("b")).toHaveLength(8);
  expect(screen.queryByText("已完成")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "测算" }));
  expect(await screen.findByLabelText(/姓名/)).toHaveValue("保留的资料");
  expect(screen.queryByRole("button", { name: /排盘并生成/ })).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "我的" }));
  expect(await screen.findByText("自己的微信昵称")).toBeInTheDocument();
  expect(await screen.findByText("7张")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "购买记录" })).not.toBeInTheDocument();
  expect(document.querySelectorAll(".account-links > button")).toHaveLength(4);
  expect(screen.queryByText("本周已使用")).not.toBeInTheDocument();
  expect(screen.queryByText(/user-own/)).not.toBeInTheDocument();
  expect(calls.some(call => call.startsWith("POST"))).toBe(false);
  localStorage.setItem("bazi.analysis.task.v1", JSON.stringify({ jobId: "old", chartId: "old-chart" }));
  sessionStorage.setItem("bazi.birth.session-draft.v1", "private draft");
  await user.click(screen.getByRole("button", { name: "退出登录" }));
  await waitFor(() => expect(localStorage.getItem("bazi.analysis.task.v1")).toBeNull());
  expect(sessionStorage.getItem("bazi.birth.session-draft.v1")).toBeNull();
  expect(screen.queryByText("自己的微信昵称")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "微信登录" })).toBeInTheDocument();
});

test("购买页保留测算草稿但不提供开始解读入口，不显示卡余额或自动扣卡", async () => {
  window.history.replaceState(null, "", "/#/cards");
  const draft = JSON.stringify({ payload: analysisFixture.chart.request, at: Date.now() });
  sessionStorage.setItem("bazi.birth.session-draft.v1", draft);
  const writes: string[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (init?.method === "POST") writes.push(url);
    return new Response(JSON.stringify(url.endsWith("/auth/me") ? auth : url.endsWith("/payments/account")
      ? { balance: 1, mode: "mock", coupon: null, products: [], orders: [] } : []));
  });
  render(<App />);
  await screen.findByText(/本地模拟支付/);
  expect(screen.queryByText("继续刚才的测算")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "使用 1 张解读卡开始解读" })).not.toBeInTheDocument();
  expect(screen.queryByText(/剩余.*张/)).not.toBeInTheDocument();
  expect(writes).toEqual([]);
  expect(sessionStorage.getItem("bazi.birth.session-draft.v1")).toBe(draft);
});

test("无报告、查询失败与未登录是不同状态，不伪造历史报告或评价", async () => {
  const user = userEvent.setup();
  vi.spyOn(globalThis, "fetch").mockImplementation(async input => {
    const url = String(input);
    return new Response(JSON.stringify(url.endsWith("/auth/me") ? { ...auth, payments_enabled: false } : []));
  });
  render(<App />);
  expect(screen.queryByRole("button", { name: "点击评价" })).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "报告" }));
  expect(await screen.findByText("还没有解读报告")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "去测算" })).toBeInTheDocument();
});

test("报告直达刷新同时恢复命盘和解读，切换我的后不残留报告正文", async () => {
  window.history.replaceState(null, "", `/#/report/${analysisFixture.job_id}`);
  vi.spyOn(globalThis, "fetch").mockImplementation(async input => {
    const url = String(input);
    return new Response(JSON.stringify(url.endsWith("/auth/me") ? { ...auth, payments_enabled: false } : url.includes("/analyses/") ? analysisFixture : []));
  });
  const user = userEvent.setup(); render(<App />);
  expect(await screen.findByRole("heading", { name: "测试用户" })).toBeVisible();
  expect(screen.queryByRole("button", { name: "基础命盘" })).not.toBeInTheDocument();
  expect(screen.queryByRole("navigation", { name: "解读目录" })).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "查看已就绪内容" }));
  expect(await screen.findByText("这是一段文化分析正文。")).toBeInTheDocument();
  expect(screen.getByRole("navigation", { name: "解读目录" })).toBeInTheDocument();
  expect(screen.queryByText("deepseek-chat")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "我的" }));
  await screen.findByText("自己的微信昵称");
  expect(screen.queryByText("这是一段文化分析正文。")).not.toBeInTheDocument();
});


test("零卡解锁由后台拒绝后进入购买页；旧报告与新测算资料保持隔离", async () => {
  window.history.replaceState(null, "", "/#/chart");
  localStorage.setItem("bazi.analysis.task.v1", JSON.stringify({ jobId: analysisFixture.job_id, chartId: analysisFixture.chart_id }));
  const newRequest = { ...analysisFixture.chart.request, name: "新测算", birth_local_datetime: "1995-04-10T08:20" };
  sessionStorage.setItem("bazi.birth.session-draft.v1", JSON.stringify({ payload: newRequest, at: Date.now() }));
  const writes: string[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (init?.method === "POST") writes.push(url);
    if (init?.method === "POST" && url.endsWith("/analyses")) return new Response(JSON.stringify({ error: { code: "cards_required", message: "请先购买解读卡" } }), { status: 402 });
    const value = url.endsWith("/auth/me") ? auth
      : url.endsWith("/charts") ? { ...analysisFixture.chart, request: newRequest }
      : url.endsWith("/me/reports") ? [item]
      : url.endsWith("/payments/account") ? { balance: 0, mode: "mock", coupon: { id: "zero-c", amount: 5000, status: "used", expires_at: "2099-01-01T00:00:00Z" }, products: [], orders: [] }
      : url.includes("/analyses/") ? analysisFixture : [];
    return new Response(JSON.stringify(value), { status: 200 });
  });
  const user = userEvent.setup(); render(<App />);
  await user.click(screen.getByRole("button", { name: "恢复本次排盘" }));
  await screen.findByRole("heading", { name: "新测算" });
  expect(screen.queryByText("这是一段文化分析正文。")).not.toBeInTheDocument();
  expect(screen.getAllByRole("listitem")).toHaveLength(54);
  await user.click(screen.getAllByRole("button", { name: "解锁完整解读" })[0]);
  expect(await screen.findByRole("heading", { name: "解读卡" })).toBeInTheDocument();
  expect(window.location.hash).toBe("#/cards");
  expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "使用 1 张解读卡开始解读" })).not.toBeInTheDocument();
  expect(JSON.parse(sessionStorage.getItem("bazi.birth.session-draft.v1") || "{}").payload).toEqual(newRequest);
  await user.click(screen.getByRole("button", { name: "报告" }));
  await user.click(await screen.findByRole("button", { name: "查看解读" }));
  expect(await screen.findByRole("heading", { name: "测试用户" })).toBeVisible();
  expect(screen.queryByRole("button", { name: "基础命盘" })).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "查看已就绪内容" }));
  await screen.findByText("这是一段文化分析正文。");
  expect(screen.queryByRole("heading", { name: "详细解读内容介绍" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "详细解读" })).not.toBeInTheDocument();
  expect(writes).toEqual(["/api/v1/charts", "/api/v1/analyses"]);
}, 15000);
