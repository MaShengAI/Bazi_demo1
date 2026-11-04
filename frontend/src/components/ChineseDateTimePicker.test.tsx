import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import { ChineseDateTimePicker } from "./ChineseDateTimePicker";

test("不依赖 datetime-local 并输出精确到分钟的后端格式", async () => {
  const change = vi.fn();
  const user = userEvent.setup();
  const { container } = render(<ChineseDateTimePicker value="" onChange={change} />);
  expect(container.querySelector('input[type="datetime-local"]')).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "请选择出生日期" }));
  await user.click(screen.getByRole("option", { name: "2100年" }));
  await user.click(screen.getByRole("option", { name: "12月" }));
  await user.click(screen.getByRole("option", { name: "31日" }));
  await user.click(screen.getByRole("option", { name: "23时" }));
  await user.click(screen.getByRole("option", { name: "59分" }));
  await user.click(screen.getByRole("button", { name: "确定" }));
  expect(change).toHaveBeenCalledWith("2100-12-31T23:59", "solar");
});

test("切换月份时自动修正无效日期", async () => {
  const change = vi.fn();
  const user = userEvent.setup();
  render(<ChineseDateTimePicker value="2000-01-31T12:00" onChange={change} />);
  await user.click(screen.getByRole("button", { name: /2000年1月31日/ }));
  await user.click(screen.getByRole("option", { name: "2月" }));
  await user.click(screen.getByRole("button", { name: "确定" }));
  expect(change).toHaveBeenCalledWith("2000-02-29T12:00", "solar");
});

test("农历闰月输入转换为公历提交，时分保持不变", async () => {
  const change = vi.fn(); const user = userEvent.setup();
  render(<ChineseDateTimePicker value="2023-03-22T09:37" onChange={change} />);
  await user.click(screen.getByRole("button", { name: /2023年3月22日/ }));
  await user.click(screen.getByRole("button", { name: "农历" }));
  expect(screen.getByRole("option", { name: "闰二月" })).toHaveAttribute("aria-selected", "true");
  expect(screen.getByRole("option", { name: "初一" })).toHaveAttribute("aria-selected", "true");
  await user.click(screen.getByRole("option", { name: "初二" }));
  await user.click(screen.getByRole("button", { name: "确定" }));
  expect(change).toHaveBeenCalledWith("2023-03-23T09:37", "lunar");
});

test("换年后不存在的闰月回到普通月份，切换公历保留同一天", async () => {
  const change = vi.fn(); const user = userEvent.setup();
  render(<ChineseDateTimePicker value="2023-03-22T09:37" onChange={change} />);
  await user.click(screen.getByRole("button", { name: /2023年3月22日/ }));
  await user.click(screen.getByRole("button", { name: "农历" }));
  await user.click(screen.getByRole("option", { name: "2024年" }));
  expect(screen.queryByRole("option", { name: "闰二月" })).not.toBeInTheDocument();
  expect(screen.getByRole("option", { name: "二月" })).toHaveAttribute("aria-selected", "true");
  await user.click(screen.getByRole("button", { name: "公历" }));
  await user.click(screen.getByRole("button", { name: "确定" }));
  expect(change).toHaveBeenCalledWith("2024-03-10T09:37", "solar");
});
