import { api, ApiError } from "./api";
import { vi } from "vitest";

test("HTTP 202 被视为成功响应并保留 job_id", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({
    job_id: "job-1",
    chart_id: "chart-1",
    status: "pending",
    deduplicated: false,
  }), { status: 202 }));

  await expect(api.createAnalysis({ gender: "female", birth_local_datetime: "2000-01-01T12:00", location_id: 3101 }))
    .resolves.toMatchObject({ job_id: "job-1", status: "pending" });
});

test("统一翻译后端结构化错误且不回显敏感细节", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({
    error: { code: "database_not_configured", message: "internal", details: { password: "do-not-show" } },
  }), { status: 503 }));

  await expect(api.getAnalysis("job-1")).rejects.toEqual(
    expect.objectContaining({ message: "AI 分析服务尚未配置数据库，普通排盘仍可正常使用。", status: 503 }),
  );
});
