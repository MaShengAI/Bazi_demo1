import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, vi } from "vitest";
import { api, SESSION_EXPIRED_EVENT } from "../api";
import type { CardAccount, PaymentOrder } from "../types";
import { CardShop } from "./CardShop";
import { invokeWeChatPay } from "../wechatPay";

vi.mock("../wechatPay", () => ({ invokeWeChatPay: vi.fn(), paymentAttemptKey: () => "test-idempotency-key" }));
const auth = { enabled: true, authenticated: true, require_for_analysis: false,
  payments_enabled: true, analysis_limit_per_24h: 0,
  user: { id: "user-1", display_name: "测试", avatar_url: null } };
const order: PaymentOrder = { id: "test-order", product_code: "single", product_name: "单次八字精批卡",
  cards: 1, original_amount: 8800, discount_amount: 5000, total_amount: 3800, status: "pending",
  created_at: "2026-10-20T00:00:00Z", expires_at: "2099-10-20T00:15:00Z" };
const base: CardAccount = { balance: 0, mode: "mock", coupon: {
  id: "coupon", amount: 5000, status: "available", expires_at: "2099-10-26T00:00:00Z" },
  products: [{ code: "single", name: "单次八字精批卡", cards: 1, price: 8800 },
    { code: "double", name: "双人八字精批套餐", cards: 2, price: 15800 },
    { code: "family", name: "全家福八字精批卡", cards: 5, price: 22800 }], orders: [] };

beforeEach(() => { vi.clearAllMocks(); });

test("未登录仅提示登录，禁用时不展示购买", async () => {
  const onLogin = vi.fn();
  const load = vi.spyOn(api, "cardAccount");
  const { rerender } = render(<CardShop auth={{ ...auth, authenticated: false, user: null }} revision={0} onLogin={onLogin} />);
  expect(screen.queryByRole("complementary", { name: "人工退款渠道" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /微信登录/ }));
  expect(onLogin).toHaveBeenCalledOnce(); expect(load).not.toHaveBeenCalled();
  rerender(<CardShop auth={{ ...auth, authenticated: false, payments_enabled: false }} revision={0} onLogin={onLogin} />);
  expect(screen.queryByText("八字解读卡")).not.toBeInTheDocument();
  expect(screen.queryByRole("complementary", { name: "人工退款渠道" })).not.toBeInTheDocument();
});

test("购买页不展示已支付或关闭订单的历史记录及操作", async () => {
  vi.spyOn(api, "cardAccount").mockResolvedValue({ ...base, orders: [{ ...order, status: "paid" }, { ...order, id: "closed-history", status: "closed" }] });
  render(<CardShop auth={auth} revision={0} onLogin={vi.fn()} />);
  await screen.findByText("¥38");
  expect(screen.queryByText("最近购买记录")).not.toBeInTheDocument();
  expect(screen.queryByText(order.id)).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /复制订单号|刷新卡余额与优惠券/ })).not.toBeInTheDocument();
});

test("待支付订单先于套餐显示，保留原订单且不自动唤起支付", async () => {
  vi.spyOn(api, "cardAccount").mockResolvedValue({ ...base, orders: [order] });
  const pay = vi.spyOn(api, "prepay");
  const create = vi.spyOn(api, "createOrder");
  render(<CardShop auth={auth} revision={0} onLogin={vi.fn()} />);
  const pending = await screen.findByRole("heading", { name: "待支付：单次八字精批卡" });
  expect(pending).toBeVisible();
  expect(screen.queryByRole("heading", { name: "单次八字精批卡" })).not.toBeInTheDocument();
  expect(screen.getByText("订单金额已确定，如需更换优惠券或套餐，请先关闭此订单。")).toBeVisible();
  expect(screen.getByRole("button", { name: "模拟支付（不扣款）" })).toBeEnabled();
  expect(screen.queryByRole("button", { name: "选择此套餐" })).not.toBeInTheDocument();
  expect(pay).not.toHaveBeenCalled(); expect(create).not.toHaveBeenCalled();
});


test("可用券自动抵扣三档金额，没有优惠券勾选项且创建订单仍需支付", async () => {
  vi.spyOn(api, "cardAccount").mockResolvedValueOnce(base).mockResolvedValue({ ...base, coupon: { ...base.coupon, status: "reserved" }, orders: [order] });
  const create = vi.spyOn(api, "createOrder").mockResolvedValue(order);
  const pay = vi.spyOn(api, "prepay");
  render(<CardShop auth={auth} revision={0} onLogin={vi.fn()} />);
  expect(await screen.findByText("¥38")).toBeInTheDocument();
  expect(screen.getByText("¥108")).toBeInTheDocument(); expect(screen.getByText("¥178")).toBeInTheDocument();
  expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  await userEvent.click(screen.getAllByRole("button", { name: "选择此套餐" })[0]);
  expect(create).toHaveBeenCalledWith("single", true, expect.any(String), "coupon");
  expect(await screen.findByRole("button", { name: "模拟支付（不扣款）" })).toBeInTheDocument();
  expect(pay).not.toHaveBeenCalled();
});

test("收银台返回成功但后台仍待支付时不显示成功、不增加余额", async () => {
  vi.spyOn(api, "cardAccount").mockResolvedValue({ ...base, mode: "live", orders: [order] });
  vi.spyOn(api, "prepay").mockResolvedValue({ mode: "live", parameters: { package: "prepay_id=test" } });
  const refresh = vi.spyOn(api, "refreshOrder").mockResolvedValue(order);
  vi.mocked(invokeWeChatPay).mockResolvedValue();
  const onPaid = vi.fn();
  render(<CardShop auth={auth} revision={0} onLogin={vi.fn()} onPaid={onPaid} />);
  await userEvent.click(await screen.findByRole("button", { name: "确认微信支付 ¥38" }));
  await waitFor(() => expect(screen.getByText(/后台尚未确认支付/)).toBeInTheDocument(), { timeout: 5000 });
  expect(refresh).toHaveBeenCalledTimes(3);
  expect(screen.queryByText(/剩余.*张/)).not.toBeInTheDocument();
  expect(screen.queryByText(/后台已确认支付/)).not.toBeInTheDocument();
  expect(onPaid).not.toHaveBeenCalled();
});

test("取消收银台后保留原待支付订单", async () => {
  vi.spyOn(api, "cardAccount").mockResolvedValue({ ...base, mode: "live", orders: [order] });
  vi.spyOn(api, "prepay").mockResolvedValue({ mode: "live", parameters: { package: "prepay_id=test" } });
  vi.spyOn(api, "refreshOrder").mockResolvedValue(order);
  vi.mocked(invokeWeChatPay).mockRejectedValue(new Error("已取消收银台支付"));
  render(<CardShop auth={auth} revision={0} onLogin={vi.fn()} />);
  await userEvent.click(await screen.findByRole("button", { name: "确认微信支付 ¥38" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("已取消收银台支付");
  expect(screen.getByRole("button", { name: "确认微信支付 ¥38" })).toBeEnabled();
});

test("登录失效后迟到的预支付响应不再唤起收银台", async () => {
  vi.spyOn(api, "cardAccount").mockResolvedValue({ ...base, mode: "live", orders: [order] });
  let resolve!: (value: { mode: "live"; parameters: Record<string, string> }) => void;
  const prepay = vi.spyOn(api, "prepay").mockImplementation(() => new Promise(done => { resolve = done; }));
  const refresh = vi.spyOn(api, "refreshOrder");
  render(<CardShop auth={auth} revision={0} onLogin={vi.fn()} />);
  await userEvent.click(await screen.findByRole("button", { name: "确认微信支付 ¥38" }));
  expect(prepay).toHaveBeenCalledOnce();
  fireEvent(window, new Event(SESSION_EXPIRED_EVENT));
  resolve({ mode: "live", parameters: { package: "prepay_id=expired" } });
  await waitFor(() => expect(screen.getByRole("button", { name: "确认微信支付 ¥38" })).toBeEnabled());
  expect(invokeWeChatPay).not.toHaveBeenCalled();
  expect(refresh).not.toHaveBeenCalled();
});

test("后台确认支付后才显示到账", async () => {
  vi.spyOn(api, "cardAccount").mockResolvedValueOnce({ ...base, orders: [order] })
    .mockResolvedValue({ ...base, balance: 1, orders: [{ ...order, status: "paid" }] });
  vi.spyOn(api, "prepay").mockResolvedValue({ mode: "mock", parameters: null });
  const mock = vi.spyOn(api, "mockConfirmOrder").mockResolvedValue({ ...order, status: "paid" });
  vi.spyOn(api, "refreshOrder").mockResolvedValue({ ...order, status: "paid" });
  const unlock = vi.spyOn(api, "unlockChart");
  const createAnalysis = vi.spyOn(api, "createAnalysis");
  const onPaid = vi.fn();
  render(<CardShop auth={auth} revision={0} onLogin={vi.fn()} onPaid={onPaid} />);
  await userEvent.click(await screen.findByRole("button", { name: "模拟支付（不扣款）" }));
  expect(await screen.findByText(/后台已确认支付，解读卡已到账/)).toBeInTheDocument();
  expect(mock).toHaveBeenCalledOnce();
  expect(screen.queryByText(/剩余.*张/)).not.toBeInTheDocument();
  expect(screen.queryByText("继续刚才的测算")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "使用 1 张解读卡开始解读" })).not.toBeInTheDocument();
  expect(unlock).not.toHaveBeenCalled();
  expect(createAnalysis).not.toHaveBeenCalled();
  expect(onPaid).toHaveBeenCalledOnce();
});


test("移除手动查单后，关闭待支付订单仍正常且不触发前端查单", async () => {
  vi.spyOn(api, "cardAccount").mockResolvedValueOnce({ ...base, orders: [order] })
    .mockResolvedValue({ ...base, orders: [{ ...order, status: "closed" }] });
  const query = vi.spyOn(api, "refreshOrder");
  const close = vi.spyOn(api, "closeOrder").mockResolvedValue({ ...order, status: "closed" });
  render(<CardShop auth={auth} revision={0} onLogin={vi.fn()} />);
  await screen.findByRole("button", { name: "关闭订单" });
  expect(screen.queryByRole("button", { name: "查单" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "关闭订单" }));
  expect(await screen.findByText("订单已关闭；未使用且未过期的优惠券可重新使用。")).toBeInTheDocument();
  expect(close).toHaveBeenCalledWith(order.id);
  expect(query).not.toHaveBeenCalled();
  expect(screen.queryByRole("button", { name: "关闭订单" })).not.toBeInTheDocument();
});


test.each(["used", "reserved"] as const)("%s 优惠券不参与抵扣，下单按原价且 use_coupon 为 false", async status => {
  const original = { ...order, original_amount: 8800, discount_amount: 0, total_amount: 8800 };
  vi.spyOn(api, "cardAccount").mockResolvedValue({ ...base, coupon: { ...base.coupon, status }, orders: [] });
  const create = vi.spyOn(api, "createOrder").mockResolvedValue(original);
  const pay = vi.spyOn(api, "prepay");
  render(<CardShop auth={auth} revision={0} onLogin={vi.fn()} />);
  expect(await screen.findByText("¥88")).toBeInTheDocument();
  expect(screen.getByText("¥158")).toBeInTheDocument();
  expect(screen.getByText("¥228")).toBeInTheDocument();
  expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  await userEvent.click(screen.getAllByRole("button", { name: "选择此套餐" })[0]);
  await waitFor(() => expect(create).toHaveBeenCalledWith("single", false, expect.any(String), undefined));
  expect(pay).not.toHaveBeenCalled();
});

const largeCoupon = { ...base.coupon, id: "coupon-88", amount: 8800, expires_at: "2099-10-27T00:00:00Z" };
const multipleCoupons = { ...base, coupons: [largeCoupon, base.coupon] };

test("可以手动选择88元券或不使用券，价格与创建订单传递的券一致", async () => {
  vi.spyOn(api, "cardAccount").mockResolvedValue(multipleCoupons);
  const create = vi.spyOn(api, "createOrder").mockResolvedValue({ ...order, total_amount: 1, discount_amount: 8799 });
  render(<CardShop auth={auth} revision={0} onLogin={vi.fn()} />);
  const picker = await screen.findByRole("combobox", { name: "优惠券" });
  expect(picker).toHaveValue("coupon");
  expect(screen.getByText("¥38")).toBeVisible();
  await userEvent.selectOptions(picker, "coupon-88");
  expect(screen.getByText("¥0.01")).toBeVisible();
  expect(screen.getByText("¥70")).toBeVisible();
  expect(screen.getByText("¥140")).toBeVisible();
  await userEvent.selectOptions(picker, "");
  expect(screen.getByText("¥88")).toBeVisible();
  await userEvent.selectOptions(picker, "coupon-88");
  await userEvent.click(screen.getAllByRole("button", { name: "选择此套餐" })[0]);
  expect(create).toHaveBeenCalledWith("single", true, expect.any(String), "coupon-88");
});

test("待支付订单使用50元券时不再展示另一张88元券计算的新价格", async () => {
  vi.spyOn(api, "cardAccount").mockResolvedValue({ ...multipleCoupons, coupon: largeCoupon, coupons: [largeCoupon], orders: [order] });
  render(<CardShop auth={auth} revision={0} onLogin={vi.fn()} />);
  expect(await screen.findByText(/实付 ¥38/)).toBeVisible();
  expect(screen.queryByText("¥0.01")).not.toBeInTheDocument();
  expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "选择此套餐" })).not.toBeInTheDocument();
});

test("手动选择的券刷新后不可用时阻止下单，不偷偷改用50元券", async () => {
  vi.spyOn(api, "cardAccount").mockResolvedValueOnce(multipleCoupons).mockResolvedValue(base);
  const create = vi.spyOn(api, "createOrder");
  const { rerender } = render(<CardShop auth={auth} revision={0} onLogin={vi.fn()} />);
  await userEvent.selectOptions(await screen.findByRole("combobox", { name: "优惠券" }), "coupon-88");
  rerender(<CardShop auth={auth} revision={1} onLogin={vi.fn()} />);
  await screen.findByRole("option", { name: "所选优惠券已失效，请重新选择" });
  screen.getAllByRole("button", { name: "选择此套餐" }).forEach(button => expect(button).toBeDisabled());
  expect(create).not.toHaveBeenCalled();
  await userEvent.selectOptions(screen.getByRole("combobox"), "coupon");
  expect(screen.getByText("¥38")).toBeVisible();
  expect(screen.getAllByRole("button", { name: "选择此套餐" })[0]).toBeEnabled();
});
