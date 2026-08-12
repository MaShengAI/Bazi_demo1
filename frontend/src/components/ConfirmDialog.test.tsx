import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import { ConfirmDialog } from "./ConfirmDialog";

test("用中文自定义弹窗确认危险操作", async () => {
  const action = vi.fn();
  render(<ConfirmDialog dialog={{ title: "删除全部出生资料？", description: "此操作无法撤销。", confirmLabel: "全部删除", danger: true, action }} busy={false} onCancel={vi.fn()} />);
  expect(screen.getByRole("alertdialog")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "全部删除" }));
  expect(action).toHaveBeenCalledOnce();
});
