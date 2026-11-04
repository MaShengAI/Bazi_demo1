import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { analysisFixture } from "../test/fixtures";
import { AnalysisPanel } from "./AnalysisPanel";
import { READING_TOPICS } from "../data/readingTopics";

test("按固定八板块顺序逐段开放，后就绪的内容不会越过前面的缺口", async () => {
  const makeResult = (ready: string[]) => ({
    ...analysisFixture, status: "running" as const, completed_sections: ready.length,
    // Deliberately reverse the API array to verify display does not depend on it.
    sections: READING_TOPICS.map((topic, index) => ({
      ...analysisFixture.sections[0], code: topic.code, title: topic.title,
      status: ready.includes(topic.code) ? "completed" as const : "pending" as const,
      content: ready.includes(topic.code) ? `正文${index + 1}` : null,
    })).reverse(),
  });
  const user = userEvent.setup();
  const later = makeResult(["children", "wealth"]);
  const { rerender, container } = render(<AnalysisPanel status={later} result={later} />);
  expect(screen.queryByRole("button", { name: "查看已就绪内容" })).not.toBeInTheDocument();
  expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "25");
  const first = makeResult(["personality", "children", "wealth"]);
  rerender(<AnalysisPanel status={first} result={first} />);
  await user.click(screen.getByRole("button", { name: "查看已就绪内容" }));
  expect(screen.getByText("正文1")).toBeInTheDocument();
  expect(screen.queryByText("正文3")).not.toBeInTheDocument();
  expect(screen.queryByText("正文6")).not.toBeInTheDocument();
  const next = makeResult(["personality", "relationship", "children", "wealth"]);
  rerender(<AnalysisPanel status={next} result={next} />);
  expect([...container.querySelectorAll("article")].map(node => node.id)).toEqual([
    "reading-personality", "reading-relationship", "reading-children",
  ]);
  expect(screen.queryByText("正文6")).not.toBeInTheDocument();
  const all = { ...makeResult(READING_TOPICS.map(t => t.code)), status: "completed" as const };
  rerender(<AnalysisPanel status={all} result={all} />);
  expect([...container.querySelectorAll("article")].map(node => node.id)).toEqual(READING_TOPICS.map(t => `reading-${t.code}`));
  expect([...container.querySelectorAll(".preview-topic-number")].map(node => node.textContent)).toEqual(["01", "02", "03", "04", "05", "06", "07", "08"]);
});

test("任务结束且前序失败时，后续已保存正文仍按顺序可读", () => {
  const terminal = { ...analysisFixture, status: "partial" as const,
    sections: READING_TOPICS.map((topic, index) => ({
      ...analysisFixture.sections[0], code: topic.code, title: topic.title,
      status: index === 0 ? "failed" as const : "completed" as const,
      content: index === 0 ? null : `已保存${index}`,
    })).reverse(),
  };
  const { container } = render(<AnalysisPanel status={terminal} result={terminal} />);
  expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  expect(screen.getByText("已保存1")).toBeInTheDocument();
  expect([...container.querySelectorAll("article")].map(node => node.id)).toEqual(READING_TOPICS.map(t => `reading-${t.code}`));
});

test("呈现报告正文，隐藏内部指标、模型信息和手动重试入口", () => {
  const terminal = { ...analysisFixture, sections: analysisFixture.sections.map(section => section.status === "pending" ? { ...section, status: "failed" as const } : section) };
  render(
    <AnalysisPanel
      status={terminal}
      result={terminal}
    />,
  );

  expect(screen.getAllByText("失败").length).toBeGreaterThan(0);
  expect(screen.getByText("这是一段文化分析正文。")).toBeInTheDocument();
  expect(screen.queryByText("模型响应超时")).not.toBeInTheDocument();
  expect(screen.getAllByText("请稍后查看或联系客服处理。").length).toBeGreaterThan(0);
  for (const text of ["字符数", "重试次数", "篇幅", "偏短", "偏长", "deepseek-chat"]) {
    expect(screen.queryByText(text)).not.toBeInTheDocument();
  }
  expect(screen.getAllByRole("article")).toHaveLength(8);
  expect(screen.queryByText("已完成")).not.toBeInTheDocument();
  expect(screen.queryByText(/八个主题|报告编号|板块完成|\d+%/)).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /重试/ })).not.toBeInTheDocument();
  for (const name of ["取消任务", "删除分析", "删除出生信息与全部结果"]) expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
});

test("后台补充时可展开已有正文，补充失败仍保留正文", async () => {
  const result = {
    ...analysisFixture,
    sections: [{
      ...analysisFixture.sections[0], status: "running" as const,
      content: "已保存的解读正文。", length_status: "short" as const,
      error: "AI模型没有返回分析内容", retry_count: 2,
    }],
  };
  const user = userEvent.setup();
  const { rerender } = render(<AnalysisPanel status={result} result={result} />);
  await user.click(screen.getByRole("button", { name: "查看已就绪内容" }));
  expect(screen.getByText("已保存的解读正文。")).toBeInTheDocument();
  expect(screen.queryByText("分析中")).not.toBeInTheDocument();
  const failed = { ...result, status: "partial" as const, sections: result.sections.map(section => ({ ...section, status: "failed" as const })) };
  rerender(<AnalysisPanel status={failed} result={failed} />);
  expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  expect(screen.getByText("已保存的解读正文。")).toBeInTheDocument();
  expect(screen.queryByText(/AI模型/)).not.toBeInTheDocument();
  expect(screen.queryByText(/篇幅不足|偏短|重试次数/)).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /重试/ })).not.toBeInTheDocument();
});

test("初次准备仅显示一组罗盘，进度随真实完成数推进，完成后展开正文", () => {
  const pending = { ...analysisFixture, status: "pending" as const, completed_sections: 0, failed_sections: 0, sections: analysisFixture.sections.map(section => ({ ...section, status: "pending" as const, content: null })) };
  const { rerender, container } = render(<AnalysisPanel status={pending} result={pending} />);
  expect(screen.getByRole("region", { name: "正在推演" })).toBeInTheDocument();
  expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "0");
  expect(container.querySelectorAll(".reading-compass")).toHaveLength(1);
  for (const cls of ["compass-taiji", "compass-pillars", "compass-stems", "compass-branches"]) expect(container.querySelector(`.${cls}`)).toBeInTheDocument();
  expect(screen.queryByRole("article")).not.toBeInTheDocument();
  expect(screen.queryByRole("navigation", { name: "解读目录" })).not.toBeInTheDocument();
  expect(screen.queryByText(/正在撰写|等待开始/)).not.toBeInTheDocument();
  const running = { ...pending, status: "running" as const, completed_sections: 4, sections: pending.sections.map((section, index) => index < 4 ? { ...section, status: "completed" as const, content: `就绪正文${index}` } : section) };
  rerender(<AnalysisPanel status={running} result={running} />);
  expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "50");
  // The status endpoint may finish before the matching result fetch returns.
  const complete = { ...running, status: "completed" as const, completed_sections: 8, sections: running.sections.map((section, index) => ({ ...section, status: "completed" as const, content: `就绪正文${index}` })) };
  rerender(<AnalysisPanel status={complete} result={running} />);
  expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "50");
  rerender(<AnalysisPanel status={complete} result={complete} />);
  expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  expect(screen.getAllByRole("article")).toHaveLength(8);
  expect(screen.getByText("就绪正文7")).toBeInTheDocument();
});

test("刷新恢复服务端进度，不用计时伪造百分比，切换任务重置展开状态", async () => {
  const running = { ...analysisFixture, status: "running" as const, completed_sections: 6 };
  const user = userEvent.setup();
  const { rerender } = render(<AnalysisPanel status={running} result={running} />);
  expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "75");
  await user.click(screen.getByRole("button", { name: "查看已就绪内容" }));
  expect(screen.getByText("这是一段文化分析正文。")).toBeVisible();
  const other = { ...running, job_id: "another-job", completed_sections: 0 };
  rerender(<AnalysisPanel status={other} result={other} />);
  expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "0");
  expect(screen.queryByText("这是一段文化分析正文。")).not.toBeInTheDocument();
});

test("活动任务即使收到八部分计数也不提前显示100%，失败后停止动画", () => {
  const running = { ...analysisFixture, status: "running" as const, completed_sections: 8 };
  const { rerender } = render(<AnalysisPanel status={running} result={null} />);
  expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "99");
  const failed = { ...running, status: "failed" as const };
  rerender(<AnalysisPanel status={failed} result={failed} />);
  expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  expect(screen.getByText("这是一段文化分析正文。")).toBeInTheDocument();
  expect(screen.getByText("解读暂未完成，请稍后查看或联系客服处理。")).toBeInTheDocument();
  expect(screen.queryByText(/正在撰写|等待开始/)).not.toBeInTheDocument();
});
