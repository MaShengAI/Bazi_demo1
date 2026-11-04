import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { vi } from "vitest";
import { WheelPicker } from "./WheelPicker";
import { LocationPicker, type BirthLocation } from "./LocationPicker";

test("滚动位置和键盘都可以改变选中行", async () => {
  function Example() { const [value, setValue] = useState("1"); return <WheelPicker label="月" options={[1, 2, 3].map(n => ({ value: String(n), label: `${n}月` }))} value={value} onChange={setValue} />; }
  render(<Example />);
  const list = screen.getByRole("listbox", { name: "月" });
  list.scrollTop = 44; fireEvent.scroll(list);
  await waitFor(() => expect(screen.getByRole("option", { name: "2月" })).toHaveAttribute("aria-selected", "true"));
  fireEvent.keyDown(list, { key: "ArrowDown" });
  expect(screen.getByRole("option", { name: "3月" })).toHaveAttribute("aria-selected", "true");
});

test("省份切换期间不提交旧城市，确定后才保存，取消保留上次地点", async () => {
  let resolveCities!: (value: Response) => void;
  vi.spyOn(globalThis, "fetch").mockImplementation(async input => {
    const url = String(input);
    if (url.includes("provinces")) return new Response(JSON.stringify([{ name: "上海市", code: "31" }, { name: "浙江省", code: "33" }]));
    if (url.includes(encodeURIComponent("浙江省"))) return new Promise(resolve => { resolveCities = resolve; });
    return new Response(JSON.stringify([{ name: "上海市", code: 3101 }]));
  });
  function Example() { const [value, setValue] = useState<BirthLocation | null>(null); return <LocationPicker value={value} onChange={setValue} />; }
  const user = userEvent.setup(); render(<Example />);
  await user.click(await screen.findByRole("button", { name: "请选择出生地点" }));
  await screen.findByRole("listbox", { name: "出生城市" });
  await user.click(screen.getByRole("option", { name: "浙江省" }));
  expect(screen.getByRole("button", { name: "确定" })).toBeDisabled();
  await waitFor(() => expect(resolveCities).toBeTypeOf("function"));
  resolveCities(new Response(JSON.stringify([{ name: "杭州市", code: 3301 }])));
  await screen.findByRole("option", { name: "杭州市" });
  await user.click(screen.getByRole("button", { name: "确定" }));
  await user.click(screen.getByRole("button", { name: /浙江省 · 杭州市/ }));
  await user.click(screen.getByRole("option", { name: "上海市" }));
  await user.click(screen.getByRole("button", { name: "取消" }));
  expect(screen.getByRole("button", { name: /浙江省 · 杭州市/ })).toBeInTheDocument();
  expect(document.body.style.overflow).not.toBe("hidden");
});

test("城市滑动和再次打开复用列表，切省时滚轮不被加载文字替换", async () => {
  let resolveCities!: (value: Response) => void;
  const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(async input => {
    const url = String(input);
    if (url.includes("provinces")) return new Response(JSON.stringify([{ name: "上海市", code: "31" }, { name: "浙江省", code: "33" }]));
    if (url.includes(encodeURIComponent("浙江省"))) return new Promise(resolve => { resolveCities = resolve; });
    return new Response(JSON.stringify([{ name: "上海市", code: 3101 }]));
  });
  const user = userEvent.setup();
  render(<LocationPicker value={null} onChange={vi.fn()} />);
  await user.click(await screen.findByRole("button", { name: "请选择出生地点" }));
  const cityWheel = await screen.findByRole("listbox", { name: "出生城市" });
  await waitFor(() => expect(screen.getByRole("button", { name: "确定" })).toBeEnabled());
  await user.click(screen.getByRole("option", { name: "浙江省" }));
  expect(cityWheel).toBeInTheDocument();
  expect(cityWheel.closest("[inert]")).not.toBeNull();
  expect(screen.queryByText(/正在读取城市/)).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "确定" })).toBeDisabled();
  await act(async () => resolveCities(new Response(JSON.stringify([{ name: "杭州市", code: 3301 }, { name: "宁波市", code: 3302 }]))));
  cityWheel.scrollTop = 44;
  fireEvent.scroll(cityWheel);
  await waitFor(() => expect(screen.getByRole("option", { name: "宁波市" })).toHaveAttribute("aria-selected", "true"));
  expect(screen.getByRole("listbox", { name: "出生城市" })).toBe(cityWheel);
  expect(screen.queryByText(/正在读取城市/)).not.toBeInTheDocument();
  await user.click(screen.getByRole("option", { name: "上海市", selected: false }));
  await waitFor(() => expect(screen.getByRole("button", { name: "确定" })).toBeEnabled());
  await user.click(screen.getByRole("button", { name: "取消" }));
  await user.click(screen.getByRole("button", { name: "请选择出生地点" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "确定" })).toBeEnabled());
  expect(fetch.mock.calls.filter(([input]) => String(input).includes("cities"))).toHaveLength(2);
});

test("快速切回已加载省份后，旧请求返回不会覆盖当前城市", async () => {
  let resolveCities!: (value: Response) => void;
  vi.spyOn(globalThis, "fetch").mockImplementation(async input => {
    const url = String(input);
    if (url.includes("provinces")) return new Response(JSON.stringify([{ name: "上海市", code: "31" }, { name: "浙江省", code: "33" }]));
    if (url.includes(encodeURIComponent("浙江省"))) return new Promise(resolve => { resolveCities = resolve; });
    return new Response(JSON.stringify([{ name: "上海市", code: 3101 }]));
  });
  const onChange = vi.fn(); const user = userEvent.setup();
  render(<LocationPicker value={null} onChange={onChange} />);
  await user.click(await screen.findByRole("button", { name: "请选择出生地点" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "确定" })).toBeEnabled());
  await user.click(screen.getByRole("option", { name: "浙江省" }));
  await user.click(screen.getByRole("option", { name: "上海市", selected: false }));
  await waitFor(() => expect(screen.getByRole("button", { name: "确定" })).toBeEnabled());
  await act(async () => resolveCities(new Response(JSON.stringify([{ name: "杭州市", code: 3301 }]))));
  expect(screen.queryByRole("option", { name: "杭州市" })).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "确定" }));
  expect(onChange).toHaveBeenCalledWith({ province: "上海市", city: "上海市", id: 3101 });
});
