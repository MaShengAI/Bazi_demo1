import { render } from "@testing-library/react";
import { vi } from "vitest";
import { App } from "./App";
import { analysisFixture } from "./test/fixtures";

test("页面进入后台暂停轮询，回到前台后立即恢复", async () => {
  vi.useFakeTimers();
  let visibility: DocumentVisibilityState = "visible";
  vi.spyOn(document, "visibilityState", "get").mockImplementation(() => visibility);
  localStorage.setItem("bazi.analysis.task.v1", JSON.stringify({ jobId: analysisFixture.job_id, chartId: analysisFixture.chart_id }));
  let statusCalls = 0;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    if (url.includes("version.json")) return response({ version: "0.2.0" });
    if (url.endsWith("/locations/provinces")) return response([]);
    if (url.endsWith("/status")) {
      statusCalls += 1;
      const { chart: _chart, sections: _sections, disclaimer: _disclaimer, ...status } = analysisFixture;
      return response({ ...status, status: "running" });
    }
    if (url.endsWith(`/analyses/${analysisFixture.job_id}`)) {
      return response({ ...analysisFixture, status: "running" });
    }
    throw new Error(`unexpected ${url}`);
  });

  render(<App />);
  await vi.waitFor(() => expect(statusCalls).toBe(1));
  visibility = "hidden";
  document.dispatchEvent(new Event("visibilitychange"));
  await vi.advanceTimersByTimeAsync(5000);
  expect(statusCalls).toBe(1);

  visibility = "visible";
  document.dispatchEvent(new Event("visibilitychange"));
  await vi.advanceTimersByTimeAsync(0);
  await vi.waitFor(() => expect(statusCalls).toBe(2));
  vi.useRealTimers();
});

function response(payload: unknown) {
  return Promise.resolve(new Response(JSON.stringify(payload), { status: 200, headers: { "Content-Type": "application/json" } }));
}
