import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import { App } from "./App";
import { analysisFixture } from "./test/fixtures";

const auth = { enabled: true, authenticated: true, payments_enabled: true, require_for_analysis: true, analysis_limit_per_24h: 0, user: { id: "own", display_name: "自己", avatar_url: null } };
const json = (value: unknown) => new Response(JSON.stringify(value));

test.each([false, true])("报告完成状态 %s 控制底部写评价入口，并绑定当前报告", async completed => {
  const jobId = "report-review-123";
  const result = { ...analysisFixture, job_id: jobId, status: completed ? "completed" : "partial", completed_sections: completed ? 8 : 1,
    sections: analysisFixture.sections.map(s => completed ? { ...s, status: "completed", content: "完整内容" } : s) };
  const profile = { nickname: "自", avatar_url: null, gender: "male", cohort: "90后", day_master: "甲木", zodiac: "蛇", pillars: ["甲子", "乙丑", "丙寅", "丁卯"], province: "湖北省" };
  window.history.replaceState(null, "", `/#/report/${jobId}`);
  vi.spyOn(globalThis, "fetch").mockImplementation(async input => {
    const url = String(input);
    return json(url.endsWith("/auth/me") ? auth : url.endsWith("/reviews/mine")
      ? { items: [{ job_id: jobId, name: "本报告", profile, review: null }, { job_id: "other", name: "别的报告", profile, review: null }], consent_version: "review-public-v1" }
      : url.includes(`/analyses/${jobId}`) ? result : []);
  });
  render(<App />);
  await screen.findByRole("heading", { name: "八字解读" });
  if (!completed) { expect(screen.queryByRole("button", { name: "写评价" })).not.toBeInTheDocument(); return; }
  await userEvent.setup().click(await screen.findByRole("button", { name: "写评价" }));
  expect(window.location.hash).toBe(`#/review/${jobId}`);
  await screen.findByLabelText("评价内容");
  expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  expect(screen.queryByText("别的报告")).not.toBeInTheDocument();
});
