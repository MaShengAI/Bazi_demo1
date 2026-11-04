import { useEffect, useRef, useState } from "react";
import { api, isSessionExpired, SESSION_EXPIRED_EVENT } from "../api";
import { AccountPlaceholder } from "./AccountPlaceholder";
import type { AuthState, CardAccount, CardProduct, PaymentOrder } from "../types";
import { invokeWeChatPay, paymentAttemptKey } from "../wechatPay";
import "./CardShop.css";

export function money(cents: number) { return (cents / 100).toFixed(2).replace(/\.00$/, ""); }
function beijing(value: string) {
  return new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(value));
}

export function CardShop({ auth, revision, onLogin, onPaid }: {
  auth: AuthState; revision: number; onLogin: () => void; onPaid?: () => void;
}) {
  const [account, setAccount] = useState<CardAccount | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [couponChoice, setCouponChoice] = useState("auto");
  const lock = useRef(false);
  const attempt = useRef<{ code: string; coupon: string; key: string } | null>(null);
  const newOrderId = useRef("");
  const pendingOrders = useRef<HTMLDivElement>(null);
  const mounted = useRef(true);
  const expiredSession = useRef(false);

  useEffect(() => {
    mounted.current = true;
    const expire = () => { expiredSession.current = true; };
    window.addEventListener(SESSION_EXPIRED_EVENT, expire);
    return () => { mounted.current = false; window.removeEventListener(SESSION_EXPIRED_EVENT, expire); };
  }, []);

  useEffect(() => {
    if (newOrderId.current && account?.orders.some(order => order.id === newOrderId.current && order.status === "pending")) {
      newOrderId.current = "";
      pendingOrders.current?.scrollIntoView?.({ block: "start", behavior: window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
    }
  }, [account]);

  useEffect(() => {
    let active = true;
    const refreshAccount = () => {
      if (!auth.payments_enabled || !auth.authenticated || document.visibilityState === "hidden" || lock.current) return;
      api.cardAccount().then((next) => { if (active) { setAccount(next); setError(""); } })
        .catch((reason: Error) => { if (active && !isSessionExpired(reason)) setError(reason.message); })
        .finally(() => { if (active) setLoading(false); });
    };
    refreshAccount();
    const timer = window.setInterval(refreshAccount, 60000);
    document.addEventListener("visibilitychange", refreshAccount);
    return () => {
      active = false;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", refreshAccount);
    };
  }, [auth.authenticated, auth.payments_enabled, revision]);

  if (!auth.payments_enabled) return null;

  const coupons = (account?.coupons ?? (account?.coupon ? [account.coupon] : []))
    .filter(coupon => coupon.status === "available" && Date.parse(coupon.expires_at) - Date.now() >= 120000)
    .sort((a, b) => Date.parse(a.expires_at) - Date.parse(b.expires_at) || a.id.localeCompare(b.id));
  const selectedCoupon = couponChoice === "auto"
    ? (coupons.find(coupon => coupon.id === account?.coupon.id) ?? coupons[0])
    : coupons.find(coupon => coupon.id === couponChoice);
  const staleCoupon = couponChoice !== "auto" && couponChoice !== "" && !selectedCoupon;

  const reload = async () => { const next = await api.cardAccount(); if (mounted.current && !expiredSession.current) setAccount(next); return next; };
  const retryLoad = async () => {
    setLoading(true); setError("");
    try { await reload(); }
    catch (reason) { if (!isSessionExpired(reason)) setError((reason as Error).message); }
    finally { setLoading(false); }
  };
  const run = async (action: () => Promise<void>) => {
    if (lock.current || !mounted.current || expiredSession.current) return;
    lock.current = true; setBusy(true); setError(""); setNotice("");
    try { await action(); }
    catch (reason) {
      if (isSessionExpired(reason)) return;
      setError((reason as Error).message);
      // Recover an order whose create response may have been lost.
      if (mounted.current && !expiredSession.current) try { await reload(); } catch { /* Keep the original error. */ }
    } finally { setBusy(false); lock.current = false; }
  };
  const choose = (product: CardProduct) => void run(async () => {
    if (staleCoupon || (selectedCoupon && Date.parse(selectedCoupon.expires_at) - Date.now() < 120000)) {
      throw new Error("所选优惠券已失效或即将到期，请重新选择。");
    }
    const coupon = selectedCoupon?.id ?? "";
    if (attempt.current?.code !== product.code || attempt.current.coupon !== coupon) {
      attempt.current = { code: product.code, coupon, key: paymentAttemptKey() };
    }
    const order = await api.createOrder(product.code, Boolean(coupon), attempt.current.key, coupon || undefined);
    newOrderId.current = order.id;
    await reload();
    setNotice(`订单已创建：${order.product_name}，${order.cards} 张卡，实付 ¥${money(order.total_amount)}。请核对上方待支付订单后继续支付。`);
  });
  const pay = (order: PaymentOrder) => void run(async () => {
    const prepay = await api.prepay(order.id);
    if (!mounted.current || expiredSession.current) return;
    let bridgeError = "";
    if (prepay.mode === "mock") {
      await api.mockConfirmOrder(order.id);
    } else {
      if (!prepay.parameters) throw new Error("缺少支付参数，请刷新页面后重试。");
      try { await invokeWeChatPay(prepay.parameters); }
      catch (reason) { bridgeError = (reason as Error).message; }
    }
    // Never grant cards or display payment success on the strength of JS alone.
    if (!mounted.current || expiredSession.current) return;
    let latest = await api.refreshOrder(order.id);
    for (let i = 0; latest.status === "pending" && !bridgeError && i < 2; i++) {
      await new Promise((resolve) => window.setTimeout(resolve, 1500));
      if (!mounted.current || expiredSession.current) return;
      latest = await api.refreshOrder(order.id);
    }
    await reload();
    if (latest.status === "paid") {
      attempt.current = null;
      setNotice("后台已确认支付，解读卡已到账。可继续填写出生信息生成报告。");
      if (mounted.current && !expiredSession.current) onPaid?.();
    } else if (bridgeError) setError(bridgeError);
    else setNotice("后台尚未确认支付，请稍后重新打开本页确认支付状态，不要重复购买。");
  });
  const close = (order: PaymentOrder) => void run(async () => {
    const latest = await api.closeOrder(order.id);
    await reload();
    if (latest.status !== "pending") attempt.current = null;
    setNotice(latest.status === "paid" ? "后台已确认支付，解读卡已到账。" : latest.status === "closed" ? "订单已关闭；未使用且未过期的优惠券可重新使用。" : "尚未确认支付，请勿重复购买。");
  });
  const pending = account?.orders.filter((order) => order.status === "pending") || [];
  return <section id="card-shop" className="card-shop card-view-shop" aria-labelledby="card-shop-title">
    <h2 id="card-shop-title" className="sr-only">解读卡套餐</h2>
    {!auth.authenticated ? <button type="button" className="button button-primary" onClick={onLogin}>微信登录，查看当周 50 元券</button> : <>
      {!account && (loading ? <AccountPlaceholder label="正在读取套餐与卡券…" /> : <div className="card-shop-load-error"><p>暂时无法读取卡券，请重试。</p><button type="button" className="button button-primary" onClick={() => void retryLoad()}>重新读取卡券</button></div>)}
      {account?.mode === "mock" && <p className="card-shop-warning">本地模拟支付：不会扣款，不是真实购买。</p>}
      {account && <>
        {pending.length > 0 && <div className="card-shop-pending" ref={pendingOrders}>
          {pending.map((order) => <div className="card-shop-order" key={order.id}>
            <h3>待支付：{order.product_name}</h3>
            <p>订单原价 ¥{money(order.original_amount)} − 优惠 ¥{money(order.discount_amount)} = <b>实付 ¥{money(order.total_amount)}</b> · {order.cards} 张卡</p>
            <small>订单号 {order.id} · 北京时间 {beijing(order.expires_at)} 截止</small>
            <p className="pending-order-help">订单金额已确定，如需更换优惠券或套餐，请先关闭此订单。</p>
            <div className="card-shop-actions">
              <button type="button" className="button button-primary" disabled={busy || Date.now() >= Date.parse(order.expires_at)} onClick={() => pay(order)}>{account.mode === "mock" ? "模拟支付（不扣款）" : `确认微信支付 ¥${money(order.total_amount)}`}</button>
              <button type="button" className="button" disabled={busy} onClick={() => close(order)}>关闭订单</button>
            </div>
          </div>)}
        </div>}
        {account.accept_new_orders === false && <p role="status">新购暂时关闭，已有待支付订单仍可继续处理。</p>}
        {pending.length === 0 && <>
        <div className="card-shop-coupon-picker">
          <label htmlFor="checkout-coupon">优惠券</label>
          <select id="checkout-coupon" value={staleCoupon ? couponChoice : selectedCoupon?.id ?? ""} disabled={busy} onChange={event => { setCouponChoice(event.target.value); setNotice(""); setError(""); }}>
            <option value="">不使用优惠券</option>
            {staleCoupon && <option value={couponChoice} disabled>所选优惠券已失效，请重新选择</option>}
            {coupons.map(coupon => <option key={coupon.id} value={coupon.id}>¥{money(coupon.amount)} 优惠券 · {beijing(coupon.expires_at)} 到期</option>)}
          </select>
          {selectedCoupon && account.products.some(product => selectedCoupon.amount >= product.price) && <small>优惠后最低实付 ¥0.01</small>}
        </div>
        <div className="card-shop-products">{account.products.map((product) => <article key={product.code}>
          <div className="card-product-heading"><div className="card-product-name"><h3>{product.name}</h3><span>（{product.cards} 张八字解读卡）</span></div><div className="card-product-price"><b>¥{money(product.price - (selectedCoupon ? Math.min(selectedCoupon.amount, product.price - 1) : 0))}</b>{selectedCoupon && <small><span>原价 ¥{money(product.price)}</span><span>券减 ¥{money(Math.min(selectedCoupon.amount, product.price - 1))}</span></small>}</div></div>
          <button type="button" className="button button-primary" disabled={busy || staleCoupon || account.accept_new_orders === false} onClick={() => choose(product)}>选择此套餐</button>
        </article>)}</div>
        </>}
      </>}
    </>}
    {busy && <p role="status">正在处理，请勿重复点击或关闭页面…</p>}
    {notice && <p role="status">{notice}</p>}{error && <p className="inline-error" role="alert">{error}</p>}
  </section>;
}
