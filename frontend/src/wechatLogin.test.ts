import { vi } from "vitest";
import { completeWechatLogin, pauseAutoLogin, shouldAutoLogin } from "./wechatLogin";
import type { AuthState } from "./types";

const guest: AuthState = { enabled: true, authenticated: false, require_for_analysis: true, analysis_limit_per_24h: 0, user: null };

test("仅微信内未登录时自动登录；一次失败不会循环，成功后下次会话可重新登录", () => {
  expect(shouldAutoLogin(guest, "Chrome Mobile")).toBe(false);
  expect(shouldAutoLogin({ ...guest, enabled: false }, "MicroMessenger")).toBe(false);
  expect(shouldAutoLogin({ ...guest, authenticated: true }, "MicroMessenger")).toBe(false);
  expect(shouldAutoLogin(guest, "MicroMessenger")).toBe(true);
  expect(shouldAutoLogin(guest, "MicroMessenger")).toBe(false);
  completeWechatLogin();
  expect(shouldAutoLogin(guest, "MicroMessenger")).toBe(true);
});

test("主动退出后不立即重新自动登录；存储被禁用时也不会陷入跳转循环", () => {
  pauseAutoLogin();
  expect(shouldAutoLogin(guest, "MicroMessenger")).toBe(false);
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked"); });
  expect(shouldAutoLogin(guest, "MicroMessenger")).toBe(false);
});
