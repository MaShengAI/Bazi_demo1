import { render, screen } from "@testing-library/react";
import { vi } from "vitest";
import type { CardAccount, DiscountCoupon } from "../types";
import { CouponPage, MyAccount } from "./CustomerPages";

const auth = { enabled: true, authenticated: true, require_for_analysis: false,
  payments_enabled: true, analysis_limit_per_24h: 0,
  user: { id: "user", display_name: "测试", avatar_url: null } };
const weekly: DiscountCoupon = { id: "weekly", source: "weekly", amount: 5000,
  status: "available", expires_at: "2099-11-02T00:00:00Z" };
const gift: DiscountCoupon = { id: "gift", source: "refund", amount: 5000,
  status: "available", expires_at: "2099-11-05T12:00:00Z" };
const account: CardAccount = { balance: 2, mode: "mock", coupon: weekly,
  coupons: [weekly, gift], products: [], orders: [] };

test("我的显示每周券和退款赠券的合计张数，卡余额不受影响", () => {
  render(<MyAccount auth={auth} account={account} loading={false} error=""
    navigate={vi.fn()} onLogin={vi.fn()} onLogout={vi.fn()} onRefresh={vi.fn()} />);
  expect(screen.getByRole("button", { name: "2张解读卡" })).toBeVisible();
  expect(screen.getByRole("button", { name: "2张优惠券" })).toBeVisible();
});

test("退款赠券单独展示自己的到期时间，不覆盖每周券", () => {
  render(<CouponPage account={account} auth={auth} onLogin={vi.fn()} />);
  expect(screen.getAllByRole("heading", { name: "解读卡优惠券" })).toHaveLength(2);
  expect(screen.getByText(/11月2日.*08:00.*到期/)).toBeVisible();
  expect(screen.getByText(/11月5日.*20:00.*到期/)).toBeVisible();
});

test("空列表不退回展示已用券；保留对旧接口的兼容", () => {
  const { rerender } = render(<CouponPage account={{ ...account, coupons: [] }} auth={auth} onLogin={vi.fn()} />);
  expect(screen.getByText("暂无可用优惠券")).toBeVisible();
  rerender(<CouponPage account={{ ...account, coupons: undefined, coupon: gift }} auth={auth} onLogin={vi.fn()} />);
  expect(screen.getByRole("heading", { name: "解读卡优惠券" })).toBeVisible();
});
