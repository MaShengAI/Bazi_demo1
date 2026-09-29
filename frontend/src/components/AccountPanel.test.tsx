import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import type { AnalysisHistoryItem } from "../types";
import { AccountPanel } from "./AccountPanel";

const baseAuth = {
  enabled: true,
  authenticated: false,
  require_for_analysis: true,
  analysis_limit_per_24h: 0,
  user: null,
};

test("未登录时显示微信登录并触发授权", async () => {
  const onLogin = vi.fn();
  render(
    <AccountPanel
      auth={baseAuth}
      open={false}
      busy={false}
      history={[]}
      onToggle={vi.fn()}
      onLogin={onLogin}
      onLogout={vi.fn()}
      onOpenReport={vi.fn()}
    />,
  );
  await userEvent.click(screen.getByRole("button", { name: "微信登录" }));
  expect(onLogin).toHaveBeenCalledOnce();
});

test("登录后显示本人报告并可以打开", async () => {
  const onOpenReport = vi.fn();
  const report: AnalysisHistoryItem = {
    job_id: "job-1",
    chart_id: "chart-1",
    status: "completed",
    name: "我的命盘",
    birth_local_datetime: "1992-08-18T09:30",
    completed_sections: 8,
    total_sections: 8,
    created_at: "2026-09-29T08:00:00Z",
  };
  render(
    <AccountPanel
      auth={{ ...baseAuth, authenticated: true, user: { id: "user-1", display_name: "微信用户", avatar_url: null } }}
      open
      busy={false}
      history={[report]}
      onToggle={vi.fn()}
      onLogin={vi.fn()}
      onLogout={vi.fn()}
      onOpenReport={onOpenReport}
    />,
  );
  await userEvent.click(screen.getByRole("button", { name: /我的命盘/ }));
  expect(onOpenReport).toHaveBeenCalledWith(report);
});
