import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import { ReadingNavigation } from "./ReadingNavigation";

const topics = [{ code: "personality", title: "性格特点与行为模式" }, { code: "health", title: "个人健康与灾厄状况预测" }];
function content(active = true) {
  return <><ReadingNavigation sections={topics} active={active} /><article id="reading-health"><h4 tabIndex={-1}>健康正文标题</h4></article></>;
}
function scrollPastDirectory() {
  vi.spyOn(screen.getByRole("navigation", { name: "解读目录" }), "getBoundingClientRect").mockReturnValue({ bottom: -10 } as DOMRect);
  fireEvent.scroll(window);
}

test("目录滚出视口后提供快捷操作，跳转正文不改变报告路由", async () => {
  const user = userEvent.setup();
  const scroll = vi.fn();
  render(content());
  document.getElementById("reading-health")!.scrollIntoView = scroll;
  expect(screen.queryByRole("group", { name: "阅读快捷操作" })).not.toBeInTheDocument();
  scrollPastDirectory();
  await user.click(screen.getByRole("button", { name: "目录" }));
  expect(screen.getByRole("dialog", { name: "阅读目录" })).toBeVisible();
  expect(document.body.style.overflow).toBe("hidden");
  await user.click(screen.getByRole("button", { name: /个人健康与灾厄状况预测/ }));
  await waitFor(() => expect(scroll).toHaveBeenCalledOnce());
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(document.body.style.overflow).not.toBe("hidden");
  expect(screen.getByText("健康正文标题")).toHaveFocus();
  expect(window.location.hash).toBe("");
  await user.click(screen.getByRole("button", { name: "返回顶部" }));
  expect(window.scrollTo).toHaveBeenCalledWith(expect.objectContaining({ top: 0 }));
});

test("目录支持键盘关闭并恢复焦点，离开详细解读后隐藏快捷操作", async () => {
  const user = userEvent.setup();
  const { rerender } = render(content());
  scrollPastDirectory();
  const trigger = screen.getByRole("button", { name: "目录" });
  await user.click(trigger);
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(trigger).toHaveFocus();
  await user.click(trigger);
  rerender(content(false));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.queryByRole("group", { name: "阅读快捷操作" })).not.toBeInTheDocument();
  expect(document.body.style.overflow).not.toBe("hidden");
});

test("随阅读位置高亮板块，顶部目录与弹出目录保持一致", async () => {
  const user = userEvent.setup();
  render(<><ReadingNavigation sections={topics} active /><article id="reading-personality" /><article id="reading-health" /></>);
  const first = document.getElementById("reading-personality")!;
  const second = document.getElementById("reading-health")!;
  let secondTop = 800;
  vi.spyOn(first, "getBoundingClientRect").mockImplementation(() => ({ top: -100 } as DOMRect));
  vi.spyOn(second, "getBoundingClientRect").mockImplementation(() => ({ top: secondTop } as DOMRect));
  scrollPastDirectory();
  const links = screen.getByRole("navigation", { name: "解读目录" });
  expect(links.querySelector('[aria-current="location"]')).toHaveTextContent("性格特点");
  secondTop = 30; fireEvent.scroll(window);
  expect(links.querySelector('[aria-current="location"]')).toHaveTextContent("个人健康");
  await user.click(screen.getByRole("button", { name: "目录" }));
  expect(screen.getByRole("button", { name: /个人健康与灾厄状况预测/ })).toHaveAttribute("aria-current", "location");
  expect(screen.getByRole("button", { name: /性格特点与行为模式/ })).not.toHaveAttribute("aria-current");
});
