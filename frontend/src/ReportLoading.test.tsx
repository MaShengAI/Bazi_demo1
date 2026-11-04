import { act, render, screen } from "@testing-library/react";
import { vi } from "vitest";
import { App } from "./App";
import { analysisFixture } from "./test/fixtures";

const auth = { enabled: true, authenticated: true, payments_enabled: true, require_for_analysis: true, analysis_limit_per_24h: 0, user: { id: "own", display_name: "自己", avatar_url: null } };
const json = (value: unknown) => new Response(JSON.stringify(value));

test("状态先返回、正文仍未加载时，不闪文字或不完整报告；慢请求显示骨架", async () => {
  window.history.replaceState(null, "", `/#/report/${analysisFixture.job_id}`);
  let finish!: (response: Response) => void;
  const pending = new Promise<Response>(resolve => { finish = resolve; });
  vi.spyOn(globalThis, "fetch").mockImplementation(async input => {
    const url = String(input);
    if (url.endsWith("/auth/me")) return json(auth);
    if (url.endsWith(`/analyses/${analysisFixture.job_id}/status`)) return json(analysisFixture);
    if (url.endsWith(`/analyses/${analysisFixture.job_id}`)) return pending;
    return json([]);
  });
  render(<App />);
  expect(screen.queryByText("正在展开报告…")).not.toBeInTheDocument();
  expect(screen.queryByRole("status", { name: "正在读取报告" })).not.toBeInTheDocument();
  expect(await screen.findByRole("status", { name: "正在读取报告" })).toBeVisible();
  expect(screen.queryByRole("heading", { name: "八字解读" })).not.toBeInTheDocument();
  expect(screen.queryByText("传统文化参考声明")).not.toBeInTheDocument();
  await act(async () => finish(json(analysisFixture)));
  expect(await screen.findByRole("heading", { name: "基础信息" })).toBeVisible();
  expect(screen.queryByRole("status", { name: "正在读取报告" })).not.toBeInTheDocument();
});

test("快速读取免费命盘时不闪加载文字或错误提示，失败时仍给出反馈", async () => {
  window.history.replaceState(null, "", "/#/chart/free-loading-test");
  let finish!: (response: Response) => void;
  const pending = new Promise<Response>(resolve => { finish = resolve; });
  vi.spyOn(globalThis, "fetch").mockImplementation(async input => {
    const url = String(input);
    if (url.endsWith("/auth/me")) return json(auth);
    if (url.endsWith("/charts/free-loading-test")) return pending;
    return json([]);
  });
  render(<App />);
  expect(screen.queryByText("正在展开报告…")).not.toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "当前无法读取命盘" })).not.toBeInTheDocument();
  await act(async () => finish(new Response(JSON.stringify({ error: { code: "not_found", message: "未找到命盘" } }), { status: 404 })));
  expect(await screen.findByRole("heading", { name: "当前无法读取命盘" })).toBeVisible();
  expect(screen.getByRole("button", { name: "返回报告列表" })).toBeInTheDocument();
});
