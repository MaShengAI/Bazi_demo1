import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import { App } from "./App";
import { analysisFixture } from "./test/fixtures";

test("从省市选择到 HTTP 202、job_id 轮询与结果恢复的完整 API 流程", async () => {
  const calls: Array<{ url: string; method: string; body?: string }> = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    const method = init?.method || "GET";
    calls.push({ url, method, body: typeof init?.body === "string" ? init.body : undefined });
    if (url.endsWith("/auth/me")) return json(authEnabled);
    if (url.endsWith("/payments/account")) return json({ balance: 1, mode: "mock", coupon: { id: "test-c", amount: 5000, status: "used", expires_at: "2099-01-01T00:00:00Z" }, products: [], orders: [] });
    if (url.endsWith("/locations/provinces")) return json([{ code: "31", name: "上海市" }]);
    if (url.includes("/locations/cities")) return json([{ code: 3101, name: "上海市", longitude: 121.47, latitude: 31.23 }]);
    if (url.endsWith("/charts") && method === "POST") return json(analysisFixture.chart);
    if (url.endsWith("/analyses") && method === "POST") {
      return json({ job_id: analysisFixture.job_id, chart_id: analysisFixture.chart_id, status: "pending", deduplicated: false }, 202);
    }
    if (url.endsWith(`/analyses/${analysisFixture.job_id}/status`)) {
      const { chart: _chart, sections: _sections, disclaimer: _disclaimer, ...status } = analysisFixture;
      return json({ ...status, status: "completed", completed_sections: 8, failed_sections: 0 });
    }
    if (url.endsWith(`/analyses/${analysisFixture.job_id}`)) {
      return json({ ...analysisFixture, status: "completed", completed_sections: 8, failed_sections: 0 });
    }
    throw new Error(`unexpected request: ${method} ${url}`);
  });

  const user = userEvent.setup();
  render(<App />);
  await user.click(await screen.findByRole("button", { name: "请选择出生地点" }));
  await screen.findByRole("listbox", { name: "出生城市" });
  await user.click(await screen.findByRole("button", { name: "确定" }));
  await user.click(screen.getByRole("button", { name: "请选择出生日期" }));
  await user.click(screen.getByRole("option", { name: "1988年" }));
  await user.click(screen.getByRole("option", { name: "7月" }));
  await user.click(screen.getByRole("option", { name: "10日" }));
  await user.click(screen.getByRole("option", { name: "30分" }));
  await user.click(screen.getByRole("button", { name: "确定" }));
  await user.click(screen.getByRole("checkbox", { name: /我已阅读并同意/ }));
  await user.click(screen.getByRole("button", { name: "开始排盘" }));
  await screen.findByRole("heading", { name: "详细解读内容介绍" });
  expect(screen.queryByRole("group", { name: "报告内容" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "基础命盘" })).not.toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "详细解读内容介绍" })).toBeInTheDocument();
  expect(screen.getAllByRole("article")).toHaveLength(8);
  expect(screen.getAllByRole("listitem")).toHaveLength(54);
  expect(screen.getByText("原生家庭性格烙印分析")).toBeInTheDocument();
  expect(screen.getByText("晚年福运与人生关键节点把握")).toBeInTheDocument();
  expect(calls.some(call => call.method === "POST" && call.url.endsWith("/analyses"))).toBe(false);
  expect(screen.queryByText("留一份完整解读")).not.toBeInTheDocument();
  await user.click(screen.getAllByRole("button", { name: "解锁完整解读" })[0]);
  expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();

  await screen.findByRole("heading", { name: "详细解读" });
  expect(screen.queryByRole("button", { name: "详细解读" })).not.toBeInTheDocument();
  await waitFor(() => expect(screen.getByRole("heading", { name: "详细解读" })).toBeInTheDocument());
  expect(JSON.parse(localStorage.getItem("bazi.analysis.task.v1") || "{}")).toEqual({
    jobId: analysisFixture.job_id,
    chartId: analysisFixture.chart_id,
  });
  expect(calls.some((call) => call.method === "POST" && call.url.endsWith("/analyses"))).toBe(true);
  expect(calls.some((call) => call.url.endsWith("/status"))).toBe(true);
  expect(calls.some((call) => call.url.endsWith(`/analyses/${analysisFixture.job_id}`))).toBe(true);
  const submitted = JSON.parse(calls.find((call) => call.method === "POST" && call.url.endsWith("/analyses"))?.body || "{}");
  expect(submitted).toEqual({ birth_calendar: "solar", gender: "male", birth_local_datetime: "1988-07-10T12:30", location_id: 3101 });
  expect(JSON.stringify(submitted)).not.toMatch(/api.?key|password|secret/i);
}, 15000);

function json(payload: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  }));
}

const authEnabled = {
  enabled: true,
  authenticated: true,
  payments_enabled: true,
  require_for_analysis: false,
  analysis_limit_per_24h: 0,
  user: { id: "test-user", display_name: "测试用户", avatar_url: null },
};
