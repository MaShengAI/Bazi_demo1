import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { chartFixture } from "../test/fixtures";
import { ChartResultView } from "./ChartResultView";

test("展示四柱、藏干、纳音、神煞、起运和流年", async () => {
  render(<ChartResultView chart={chartFixture} />);
  expect(screen.getByText("测试用户的四柱命盘")).toBeInTheDocument();
  expect(screen.getByLabelText("年柱戊辰")).toBeInTheDocument();
  expect(screen.getAllByText("纳音 · 大林木")).toHaveLength(1);
  expect(screen.getAllByText("太极贵人").length).toBeGreaterThan(0);
  expect(screen.getByText("9 年 4 月 19 日")).toBeInTheDocument();
  await userEvent.click(screen.getByText("庚申"));
  expect(screen.getByText("1998")).toBeInTheDocument();
  expect(screen.getByText("戊寅")).toBeInTheDocument();
});
