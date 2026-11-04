import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, vi } from "vitest";
import { chartFixture } from "../test/fixtures";
import { AdminApp } from "./AdminApp";

const item = { id: "admin-report-one", chart_id: "chart-one", user_id: null,
  name: "后台示例", status: "completed", model: "deepseek-flash", gender: "male",
  birth_local_datetime: "1988-07-10T12:30", created_at: "2026-10-28T00:00:00+00:00",
  completed_sections: 8, total_sections: 8 };
const detail = { ...item, request: chartFixture.request, chart: chartFixture,
  prompt_version: "test-v1", finished_at: "2026-10-28T00:02:00+00:00",
  sections: [{ code: "personality", title: "性格特点与行为模式", status: "completed",
    content: "保存的正文 <img src=x onerror=alert(1)>", char_count: 1690,
    length_status: "short", retry_count: 2, error: null, error_code: null }] };
const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), {
  status, headers: { "Content-Type": "application/json" },
});

beforeEach(() => {
  history.replaceState({}, "", "/admin");
  vi.spyOn(window, "scrollTo").mockImplementation(() => undefined);
});
afterEach(() => { history.replaceState({}, "", "/"); vi.unstubAllGlobals(); });

test("独立登录前不读取报告，密码不保存且提交后清空", async () => {
  let authenticated = false;
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith("/session")) return json({ authenticated: false, username: null });
    if (url.endsWith("/login")) {
      expect(JSON.parse(init!.body as string)).toEqual({ username: "owner", password: "test-admin-password" });
      authenticated = true;
      return json({ authenticated: true, username: "owner" });
    }
    expect(authenticated).toBe(true);
    expect(url).not.toContain("start=");
    expect(url).not.toContain("end=");
    return json({ items: [item], total: 1, page: 1, page_size: 20 });
  });
  vi.stubGlobal("fetch", fetch);
  render(<AdminApp />);
  await screen.findByRole("heading", { name: "管理后台登录" });
  expect(fetch.mock.calls).toHaveLength(1);
  await userEvent.type(screen.getByLabelText("管理员账号"), "owner");
  await userEvent.type(screen.getByLabelText("密码"), "test-admin-password");
  await userEvent.click(screen.getByRole("button", { name: "登录后台" }));
  expect(await screen.findByText("后台示例")).toBeInTheDocument();
  expect(localStorage.length).toBe(0);
  expect(sessionStorage.getItem("password")).toBeNull();
  expect(screen.queryByDisplayValue("test-admin-password")).not.toBeInTheDocument();
  expect(fetch.mock.calls.filter(([url]) => url.includes("/auth/") || url.includes("/payments/"))).toHaveLength(0);
});

test("可查询报告并查看正文与命盘，页面没有写操作且正文按文本显示", async () => {
  const fetch = vi.fn(async (url: string) => {
    if (url.endsWith("/session")) return json({ authenticated: true, username: "owner" });
    if (url.includes("/reports/admin-report-one")) return json(detail);
    return json({ items: [item], total: 21, page: 1, page_size: 20 });
  });
  vi.stubGlobal("fetch", fetch);
  render(<AdminApp />);
  await screen.findByText("后台示例");
  await userEvent.type(screen.getByLabelText("姓名 / 报告编号"), "示例");
  await userEvent.selectOptions(screen.getByLabelText("报告状态"), "completed");
  await userEvent.click(screen.getByRole("button", { name: "查询" }));
  await waitFor(() => expect(fetch.mock.calls.some(([url]) => url.includes("q=%E7%A4%BA%E4%BE%8B") && url.includes("status=completed"))).toBe(true));
  await userEvent.click(screen.getByRole("button", { name: "下一页" }));
  await waitFor(() => expect(fetch.mock.calls.some(([url]) => url.includes("page=2"))).toBe(true));
  await userEvent.click(screen.getByRole("button", { name: "查看报告" }));
  const article = await screen.findByRole("article");
  expect(within(article).getByText("保存的正文 <img src=x onerror=alert(1)>")).toBeVisible();
  expect(article.querySelector("img")).toBeNull();
  expect(screen.getByText(/重试 2 次/)).toBeInTheDocument();
  for (const name of [/删除/, /重新生成/, /取消任务/, /重试此板块/]) {
    expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
  }
  await userEvent.click(screen.getByRole("tab", { name: "命盘资料" }));
  expect(screen.getByRole("tabpanel", { name: "命盘资料" })).toBeInTheDocument();
  expect(screen.getByRole("tabpanel", { name: "命盘资料" }).querySelector("#chart-title")).toHaveTextContent("测试用户");
});

test("管理员会话过期后清除已显示的数据并回到登录", async () => {
  let expired = false;
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url.endsWith("/session")) return json({ authenticated: true, username: "owner" });
    return expired ? json({ error: { message: "请登录管理后台。" } }, 401)
      : json({ items: [item], total: 1, page: 1, page_size: 20 });
  }));
  render(<AdminApp />);
  await screen.findByText("后台示例");
  expired = true;
  await userEvent.click(screen.getByRole("button", { name: "刷新数据" }));
  expect(await screen.findByRole("heading", { name: "管理后台登录" })).toBeInTheDocument();
  expect(screen.queryByText("后台示例")).not.toBeInTheDocument();
  expect(screen.getByRole("alert")).toHaveTextContent("请登录管理后台");
});
