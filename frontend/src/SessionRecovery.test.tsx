import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import { App } from "./App";
import { api, SESSION_EXPIRED_EVENT } from "./api";

const auth = { enabled: true, authenticated: true, require_for_analysis: true, payments_enabled: true, analysis_limit_per_24h: 0, user: { id: "owner", display_name: "过期前的昵称", avatar_url: null } };
const account = { balance: 7, mode: "mock", coupon: { id: "c", amount: 5000, status: "available", expires_at: "2099-01-01T00:00:00Z" }, products: [], orders: [] };
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

test("切回我的时静默刷新卡券，保留余额且失败仍可重新读取", async () => {
  window.history.replaceState(null, "", "/#/me");
  let refreshed = false;
  let resolve!: (response: Response) => void;
  const pending = new Promise<Response>(done => { resolve = done; });
  vi.spyOn(globalThis, "fetch").mockImplementation(async input => {
    const url = String(input);
    return url.endsWith("/auth/me") ? json(auth) : url.endsWith("/payments/account")
      ? refreshed ? pending : json(account) : json([]);
  });
  const user = userEvent.setup(); render(<App />);
  expect(await screen.findByText("7张")).toBeVisible();
  await user.click(screen.getByRole("button", { name: "测算" }));
  refreshed = true;
  await user.click(screen.getByRole("button", { name: "我的" }));
  await waitFor(() => expect(document.querySelector(".account-assets")).toHaveAttribute("aria-busy", "true"));
  expect(screen.getByText("7张")).toBeVisible();
  expect(screen.queryByText(/正在更新卡券/)).not.toBeInTheDocument();
  expect(document.querySelector(".skeleton-count")).not.toBeInTheDocument();
  resolve(json({ error: { code: "unavailable", message: "卡券读取暂时失败" } }, 503));
  expect(await screen.findByRole("alert")).toBeVisible();
  expect(screen.getByRole("button", { name: "重新读取" })).toBeVisible();
  expect(screen.getByText("7张")).toBeVisible();
});

test("购买页卡券加载显示占位，读取成功后不展示余额或短暂显示服务关闭", async () => {
  window.history.replaceState(null, "", "/#/cards");
  let resolve!: (value: Response) => void;
  const pending = new Promise<Response>(done => { resolve = done; });
  vi.spyOn(globalThis, "fetch").mockImplementation(async input => String(input).endsWith("/auth/me") ? json(auth) : String(input).endsWith("/payments/account") ? (await pending).clone() : json([]));
  render(<App />);
  expect(await screen.findByRole("status", { name: "正在读取套餐与卡券…" })).toBeVisible();
  expect(screen.queryByText("解读卡购买暂未开放")).not.toBeInTheDocument();
  expect(screen.queryByText("剩余 0 张")).not.toBeInTheDocument();
  resolve(json(account));
  expect(await screen.findByText(/本地模拟支付/)).toBeVisible();
  expect(screen.queryByText(/剩余.*张/)).not.toBeInTheDocument();
  expect(screen.queryByRole("status", { name: "正在读取套餐与卡券…" })).not.toBeInTheDocument();
});

test("401 清理旧昵称和卡余额，保留本次测算草稿且不自动发起购买", async () => {
  window.history.replaceState(null, "", "/#/me");
  const draft = JSON.stringify({ payload: { name: "保留资料", gender: "male", birth_local_datetime: "1990-01-01T12:00", location_id: 1101 }, at: Date.now() });
  sessionStorage.setItem("bazi.birth.session-draft.v1", draft);
  let expired = false;
  const writes: string[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (init?.method && init.method !== "GET") writes.push(url);
    return url.endsWith("/auth/me") ? json(auth) : url.endsWith("/payments/account") ? expired ? json({ error: { code: "authentication_required" } }, 401) : json(account) : json([]);
  });
  const user = userEvent.setup(); render(<App />);
  expect(await screen.findByText("7张")).toBeVisible();
  expired = true; fireEvent(document, new Event("visibilitychange"));
  expect(await screen.findByRole("heading", { name: "登录已过期" })).toBeVisible();
  expect(screen.getByRole("button", { name: "重新登录" })).toBeVisible();
  expect(screen.queryByText("过期前的昵称")).not.toBeInTheDocument();
  expect(screen.queryByText("7张")).not.toBeInTheDocument();
  expect(sessionStorage.getItem("bazi.birth.session-draft.v1")).toBe(draft);
  await user.click(screen.getByRole("button", { name: "测算" }));
  expect(screen.getByRole("button", { name: "开始排盘" })).toBeVisible();
  expect(screen.getByText("登录已过期")).toBeVisible();
  expect(writes).toEqual([]);
});

test("登录失效后迟到的身份响应不能恢复旧登录状态", async () => {
  window.history.replaceState(null, "", "/#/me");
  let resolve!: (value: Response) => void;
  const pending = new Promise<Response>(done => { resolve = done; });
  vi.spyOn(globalThis, "fetch").mockImplementation(async input => String(input).endsWith("/auth/me") ? pending : json([]));
  render(<App />);
  fireEvent(window, new Event(SESSION_EXPIRED_EVENT));
  resolve(json(auth));
  await waitFor(() => expect(screen.getByText("登录已过期")).toBeVisible());
  expect(screen.queryByText("过期前的昵称")).not.toBeInTheDocument();
});

test("只有 401 通知登录失效，403 和暂时性服务错误不误退出", async () => {
  const expired = vi.fn();
  window.addEventListener(SESSION_EXPIRED_EVENT, expired);
  try {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(json({}, 403)).mockResolvedValueOnce(json({}, 503)).mockResolvedValueOnce(json({}, 401));
    await expect(api.cardAccount()).rejects.toMatchObject({ status: 403 });
    await expect(api.cardAccount()).rejects.toMatchObject({ status: 503 });
    expect(expired).not.toHaveBeenCalled();
    await expect(api.cardAccount()).rejects.toMatchObject({ status: 401 });
    expect(expired).toHaveBeenCalledOnce();
  } finally { window.removeEventListener(SESSION_EXPIRED_EVENT, expired); }
});
