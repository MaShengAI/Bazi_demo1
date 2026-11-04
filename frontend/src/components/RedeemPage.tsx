import { useRef, useState } from "react";
import { api } from "../api";
import type { AuthState, RedemptionReceipt } from "../types";
import { AccountPlaceholder } from "./AccountPlaceholder";

export function RedeemPage({ auth, onLogin, onRedeemed }: {
  auth: AuthState | null; onLogin: () => void; onRedeemed: () => void;
}) {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<RedemptionReceipt | null>(null);
  const lock = useRef(false);
  if (!auth) return <AccountPlaceholder />;
  if (!auth.authenticated) return <section className="paper-card report-empty"><p>登录后，兑换奖励将存入你的账户。</p><button className="button button-primary" onClick={onLogin}>微信登录</button></section>;
  return <section className="paper-card redeem-card">
    <form onSubmit={async e => {
      e.preventDefault(); if (lock.current || !code.trim()) return;
      lock.current = true; setBusy(true); setError(""); setResult(null);
      try { const value = await api.redeemCode(code.trim()); setResult(value); setCode(""); onRedeemed(); }
      catch (reason) { setError((reason as Error).message); }
      finally { lock.current = false; setBusy(false); }
    }}>
      <input id="redeem-code" aria-label="兑换码" placeholder="请输入兑换码" value={code} maxLength={100} autoComplete="off" autoCapitalize="characters" spellCheck={false} disabled={busy}
        onChange={e => { setCode(e.target.value); setError(""); setResult(null); }} />
      <button className="button button-primary" disabled={busy || !code.trim()}>{busy ? "正在兑换…" : "确认兑换"}</button>
    </form>
    {error && <p className="redeem-error" role="alert">{error}</p>}
    {result && <div className="redeem-success" role="status"><h3>{result.already_redeemed ? "此兑换码已存入你的账户" : "兑换成功"}</h3>
      <p>{result.kind === "cards" ? `${result.value} 张解读卡` : `¥${result.value / 100} 解读卡优惠券`}</p>
      {result.coupon_expires_at && <p>{new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai", month: "long", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(result.coupon_expires_at))} 到期</p>}
    </div>}
  </section>;
}
