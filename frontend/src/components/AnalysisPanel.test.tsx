import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import { analysisFixture } from "../test/fixtures";
import { AnalysisPanel } from "./AnalysisPanel";

test("完整呈现六种任务状态及八板块指标，并允许单板块重试", async () => {
  const retry = vi.fn();
  render(
    <AnalysisPanel
      status={analysisFixture}
      result={analysisFixture}
      actionBusy={null}
      onRetry={retry}
      onCancel={vi.fn()}
      onDeleteAnalysis={vi.fn()}
      onDeleteChart={vi.fn()}
    />,
  );

  for (const label of ["等待中", "分析中", "部分完成", "已完成", "失败", "已取消"]) {
    expect(screen.getAllByText(label).length).toBeGreaterThan(0);
  }
  expect(screen.getByText("这是一段文化分析正文。")).toBeInTheDocument();
  expect(screen.getByText("1,500")).toBeInTheDocument();
  expect(screen.getByText("模型响应超时")).toBeInTheDocument();
  expect(screen.getAllByText("2").length).toBeGreaterThan(0);
  expect(screen.getAllByRole("article")).toHaveLength(8);

  await userEvent.click(screen.getByRole("button", { name: /重试此板块/ }));
  expect(retry).toHaveBeenCalledWith("wealth");
});
