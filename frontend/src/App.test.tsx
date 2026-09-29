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
    if (url.endsWith("/auth/me")) return json(authDisabled);
    if (url.endsWith("/locations/provinces")) return json([{ code: "31", name: "上海市" }]);
    if (url.includes("/locations/cities")) return json([{ code: 3101, name: "上海市", longitude: 121.47, latitude: 31.23 }]);
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
  await user.selectOptions(await screen.findByLabelText("出生省份"), "上海市");
  await user.selectOptions(await screen.findByLabelText("出生城市"), "3101");
  await user.click(screen.getByRole("button", { name: "请选择出生日期与时间" }));
  await user.selectOptions(screen.getByLabelText("年"), "1988");
  await user.selectOptions(screen.getByLabelText("月"), "7");
  await user.selectOptions(screen.getByLabelText("日"), "10");
  await user.selectOptions(screen.getByLabelText("分"), "30");
  await user.click(screen.getByRole("button", { name: "确定" }));
  await user.click(screen.getByRole("checkbox", { name: /我已阅读并同意/ }));
  await user.click(screen.getByRole("button", { name: /排盘并生成 AI 分析/ }));

  await waitFor(() => expect(screen.getByText("测试用户的四柱命盘")).toBeInTheDocument());
  expect(JSON.parse(localStorage.getItem("bazi.analysis.task.v1") || "{}")).toEqual({
    jobId: analysisFixture.job_id,
    chartId: analysisFixture.chart_id,
  });
  expect(calls.some((call) => call.method === "POST" && call.url.endsWith("/analyses"))).toBe(true);
  expect(calls.some((call) => call.url.endsWith("/status"))).toBe(true);
  expect(calls.some((call) => call.url.endsWith(`/analyses/${analysisFixture.job_id}`))).toBe(true);
  const submitted = JSON.parse(calls.find((call) => call.method === "POST")?.body || "{}");
  expect(submitted).toEqual({ gender: "male", birth_local_datetime: "1988-07-10T12:30", location_id: 3101 });
  expect(JSON.stringify(submitted)).not.toMatch(/api.?key|password|secret/i);
});

function json(payload: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  }));
}

const authDisabled = {
  enabled: false,
  authenticated: false,
  require_for_analysis: false,
  analysis_limit_per_24h: 0,
  user: null,
};
