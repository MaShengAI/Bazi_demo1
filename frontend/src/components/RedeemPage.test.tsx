import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import { api } from "../api";
import { RedeemPage } from "./RedeemPage";
import { MyAccount } from "./CustomerPages";

const auth = { enabled: true, authenticated: true, require_for_analysis: false,
  analysis_limit_per_24h: 0, user: { id: "user", display_name: "测试", avatar_url: null } };

test("兑换入口位于优惠券和联系客服之间；未登录须登录", () => {
  const navigate = vi.fn(), onLogin = vi.fn();
  const { unmount } = render(<MyAccount auth={auth} account={null} loading={false} error=""
    navigate={navigate} onLogin={onLogin} onLogout={vi.fn()} onRefresh={vi.fn()} />);
  const buttons = Array.from(document.querySelectorAll(".account-links > button")).map(b => b.querySelectorAll("span")[1].textContent);
  expect(buttons.indexOf("兑换码")).toBeGreaterThan(buttons.indexOf("优惠券"));
  expect(buttons.indexOf("兑换码")).toBeLessThan(buttons.indexOf("联系客服"));
  fireEvent.click(screen.getByRole("button", { name: "兑换码" }));
  expect(navigate).toHaveBeenCalledWith("redeem");
  unmount();
  render(<RedeemPage auth={{ ...auth, authenticated: false, user: null }} onLogin={onLogin} onRedeemed={vi.fn()} />);
  expect(screen.queryByLabelText("兑换码")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "微信登录" }));
  expect(onLogin).toHaveBeenCalledOnce();
});

test("快速重复提交仅发一次请求，成功后刷新账户和清空兑换码", async () => {
  let finish!: (value: Awaited<ReturnType<typeof api.redeemCode>>) => void;
  const redeem = vi.spyOn(api, "redeemCode").mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  const refreshed = vi.fn();
  render(<RedeemPage auth={auth} onLogin={vi.fn()} onRedeemed={refreshed} />);
  fireEvent.change(screen.getByLabelText("兑换码"), { target: { value: "  ABCDE-FGHJK-LMNPQ-RSTUV  " } });
  const form = screen.getByRole("button", { name: "确认兑换" }).closest("form")!;
  fireEvent.submit(form); fireEvent.submit(form);
  expect(redeem).toHaveBeenCalledOnce();
  expect(redeem).toHaveBeenCalledWith("ABCDE-FGHJK-LMNPQ-RSTUV");
  finish({ kind: "cards", value: 2, already_redeemed: false, redeemed_at: "2026-11-02T00:00:00Z", coupon_expires_at: null });
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("兑换成功"));
  expect(screen.getByRole("status")).toHaveTextContent("2 张解读卡");
  expect(refreshed).toHaveBeenCalledOnce();
  expect(screen.getByLabelText("兑换码")).toHaveValue("");
});

test("失败不显示成功或刷新余额，支持再次修改输入", async () => {
  vi.spyOn(api, "redeemCode").mockRejectedValue(new Error("兑换码已过期"));
  const refreshed = vi.fn();
  render(<RedeemPage auth={auth} onLogin={vi.fn()} onRedeemed={refreshed} />);
  fireEvent.change(screen.getByLabelText("兑换码"), { target: { value: "INVALID" } });
  fireEvent.click(screen.getByRole("button", { name: "确认兑换" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("已过期");
  expect(refreshed).not.toHaveBeenCalled();
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});
