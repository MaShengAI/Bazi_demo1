import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import { ChineseDateTimePicker } from "./ChineseDateTimePicker";

test("不依赖 datetime-local 并输出精确到分钟的后端格式", async () => {
  const change = vi.fn();
  const user = userEvent.setup();
  const { container } = render(<ChineseDateTimePicker value="" onChange={change} />);
  expect(container.querySelector('input[type="datetime-local"]')).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "请选择出生日期与时间" }));
  await user.selectOptions(screen.getByLabelText("年"), "2100");
  await user.selectOptions(screen.getByLabelText("月"), "12");
  await user.selectOptions(screen.getByLabelText("日"), "31");
  await user.selectOptions(screen.getByLabelText("时"), "23");
  await user.selectOptions(screen.getByLabelText("分"), "59");
  await user.click(screen.getByRole("button", { name: "确定" }));
  expect(change).toHaveBeenCalledWith("2100-12-31T23:59");
});

test("切换月份时自动修正无效日期", async () => {
  const change = vi.fn();
  const user = userEvent.setup();
  render(<ChineseDateTimePicker value="2000-01-31T12:00" onChange={change} />);
  await user.click(screen.getByRole("button", { name: /2000年1月31日/ }));
  await user.selectOptions(screen.getByLabelText("月"), "2");
  await user.click(screen.getByRole("button", { name: "确定" }));
  expect(change).toHaveBeenCalledWith("2000-02-29T12:00");
});
