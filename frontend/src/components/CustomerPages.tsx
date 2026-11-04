import { PublicReviews } from "./ReviewPages";
import { useEffect, useMemo, useRef, useState } from "react";
import { groupReportsByName } from "../reportNameGroups";
import type { SavedReportItem, AuthState, CardAccount } from "../types";
import { StatusBadge } from "./StatusBadge";
import { APP_VERSION } from "../config";
import { AccountPlaceholder } from "./AccountPlaceholder";

export type CustomerRoute = "measure" | "reports" | "me" | "chart" | "report" | "cards" | "coupon" | "redeem" | "review" | "service" | "privacy";
export function readCustomerRoute(): { page: CustomerRoute; reportId?: string; chartId?: string } {
  const path = window.location.hash.replace(/^#\/?/, "").split("/");
  if (path[0] === "review" && /^[\w-]{1,100}$/.test(path[1] || "")) return { page: "review", reportId: path[1] };
  if (path[0] === "report" && /^[\w-]{1,100}$/.test(path[1] || "")) return { page: "report", reportId: path[1] };
  if (path[0] === "chart" && /^[\w-]{1,100}$/.test(path[1] || "")) return { page: "chart", chartId: path[1] };
  const pages: CustomerRoute[] = ["measure", "reports", "me", "chart", "cards", "coupon", "redeem", "review", "service", "privacy"];
  return { page: pages.includes(path[0] as CustomerRoute) ? path[0] as CustomerRoute : "measure" };
}

export function CustomerIcon({ name }: { name: string }) {
  const paths: Record<string, React.ReactNode> = {
    measure: <><circle cx="12" cy="12" r="9" /><path d="M12 3c-6 0-6 9 0 9s6 9 0 9" /><circle cx="12" cy="7.5" r="1" /><circle cx="12" cy="16.5" r="1" /></>,
    reports: <><path d="M5 3h14v18H5zM9 3v18M13 7h3M13 11h3M13 15h3" /></>,
    me: <><circle cx="12" cy="8" r="4" /><path d="M4 21v-2a8 8 0 0 1 16 0v2" /></>,
    cards: <><rect x="3" y="5" width="18" height="14" rx="2" /><path d="M3 10h18M7 15h4" /></>,
    coupon: <><path d="M3 5h18v5a2 2 0 0 0 0 4v5H3v-5a2 2 0 0 0 0-4zM9 5v14M13 9h4M13 15h4" /></>,
    redeem: <><rect x="3" y="6" width="18" height="15" rx="2" /><path d="M3 11h18M12 6v15M12 6C7-2 2 6 12 6Zm0 0c5-8 10 0 0 0Z" /></>,
    service: <><path d="M4 14v-2a8 8 0 0 1 16 0v5a4 4 0 0 1-4 4h-3" /><rect x="2" y="10" width="4" height="7" rx="2" /><rect x="18" y="10" width="4" height="7" rx="2" /></>,
  };
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.45" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name] || paths.reports}</svg>;
}

export function BottomTabs({ page, navigate }: { page: CustomerRoute; navigate: (page: CustomerRoute) => void }) {
  const current = ["report", "reports", "review"].includes(page) ? "reports" : ["measure", "chart"].includes(page) ? "measure" : "me";
  return <nav className="customer-tabs" aria-label="主导航">
    {([['measure', '测算'], ['reports', '报告'], ['me', '我的']] as const).map(([key, label]) => <button key={key} type="button" aria-current={current === key ? "page" : undefined} onClick={() => navigate(key)}><CustomerIcon name={key} /><span>{label}</span></button>)}
  </nav>;
}

export function ReportBack({ onBack }: { onBack: () => void }) {
  return <nav className="report-back-bar" aria-label="报告导航"><button type="button" className="page-back" onClick={onBack} aria-label="返回"><svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="m15 5-7 7 7 7" /></svg></button></nav>;
}

export function PageTitle({ title, subtitle, onBack, className = "" }: { title: string; subtitle?: string; onBack?: () => void; className?: string }) {
  return <header className={`customer-page-title${onBack ? " has-back" : ""} ${className}`}>{onBack && <button type="button" className="page-back" onClick={onBack} aria-label="返回"><svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="m15 5-7 7 7 7" /></svg></button>}<h1>{title}</h1>{subtitle && <p>{subtitle}</p>}</header>;
}

export function Reviews() {
  return <PublicReviews />;
}

export function ReportList({ auth, items, loaded, busy, error, onLogin, onMeasure, onOpen, onDelete, deletingChartId, onRefresh, onService }: {
  auth: AuthState | null; items: SavedReportItem[]; loaded: boolean; busy: boolean; error: string;
  onLogin: () => void; onMeasure: () => void; onOpen: (item: SavedReportItem) => void; onDelete: (item: SavedReportItem) => void; deletingChartId: string | null; onRefresh: () => void; onService: () => void;
}) {
  const [query, setQuery] = useState("");
  const [submittedQuery, setSubmittedQuery] = useState("");
  const visible = useMemo(() => items.filter(item => `${item.name || ""} ${item.chart_id} ${item.job_id || ""}`.toLocaleLowerCase().includes(submittedQuery.toLocaleLowerCase())), [items, submittedQuery]);
  const groups = useMemo(() => groupReportsByName(visible), [visible]);
  const groupRefs = useRef<Record<string, HTMLElement | null>>({});
  const [activeLetter, setActiveLetter] = useState("");
  useEffect(() => {
    let frame = 0;
    const update = () => {
      let current = groups[0]?.letter || "";
      for (const group of groups) {
        const node = groupRefs.current[group.letter];
        if (node && node.getBoundingClientRect().top <= 110) current = group.letter;
      }
      setActiveLetter(current);
    };
    const scroll = () => { cancelAnimationFrame(frame); frame = requestAnimationFrame(update); };
    update(); window.addEventListener("scroll", scroll, { passive: true });
    return () => { cancelAnimationFrame(frame); window.removeEventListener("scroll", scroll); };
  }, [groups]);
  const loggedIn = auth?.authenticated;
  return <>
    {loggedIn && <form className="report-list-tools" role="search" onSubmit={event => { event.preventDefault(); if (busy) return; setSubmittedQuery(query.trim()); onRefresh(); }}><label><span className="sr-only">搜索报告</span><input type="search" placeholder="搜索姓名" value={query} onChange={e => setQuery(e.target.value)} /></label><button type="submit" className="text-button" disabled={busy}>搜索</button></form>}
    {error ? <div className="paper-card report-empty" role="alert"><h2>暂时无法读取报告</h2><p>{error}</p><button className="button button-primary" onClick={onRefresh}>重新读取</button></div> : !auth || (loggedIn && !loaded) ? <div className="paper-card report-empty" role="status"><span className="spinner" /><p>正在读取报告…</p></div> : !loggedIn ? <div className="paper-card report-empty"><div className="empty-scroll" aria-hidden="true">卷</div><h2>你的解读，妥善珍藏</h2><p>{auth.enabled ? "微信登录后，即可查看属于你的报告。" : "账户服务暂未开放，基础排盘仍可使用。"}</p><button className="button button-primary" onClick={auth.enabled ? onLogin : onMeasure}>{auth.enabled ? "微信登录" : "去测算"}</button></div> : items.length === 0 ? <div className="paper-card report-empty"><div className="empty-scroll" aria-hidden="true">卷</div><h2>还没有解读报告</h2><p>从一次测算开始，留下一份属于你的解读。</p><button className="button button-primary" onClick={onMeasure}>去测算</button><button className="text-button" onClick={onService}>找不到已有报告？联系客服</button></div> : <>
      <div className="report-list-layout"><div className="customer-report-groups">{groups.map(group => <section className="report-letter-group" key={group.letter} ref={node => { groupRefs.current[group.letter] = node; }} aria-label={`${group.letter}组报告`}><h2 className="report-letter-heading">{group.letter}</h2><div className="customer-report-list">{group.items.map(item => <article className="paper-card report-summary" key={`${item.chart_id}-${item.job_id || "locked"}`}>
        <div className="report-summary-overview">
          <div className="report-summary-identity">
            <div className="report-name-row"><h2>{item.name || "未署名"}</h2>{item.status !== "locked" && <StatusBadge status={item.status} hideCompleted />}</div>
            <p className="report-birth"><span>生辰：</span>{item.birth_local_datetime ? <time>{item.birth_local_datetime.replace("T", " ")}</time> : "未记录"}</p>
          </div>
          {item.pillars?.length ? <div className="summary-pillars" role="group" aria-label="四柱">{item.pillars.map((pillar, i) => <span className="summary-pillar-column" key={i} title={`${["年柱", "月柱", "日柱", "时柱"][i]} ${pillar}`}><span className="sr-only">{["年柱", "月柱", "日柱", "时柱"][i]}</span><b>{pillar[0] || "—"}</b><b>{pillar[1] || "—"}</b></span>)}</div> : null}
        </div>
        <div className="report-summary-actions"><button className="button button-primary" disabled={deletingChartId !== null} onClick={() => onOpen(item)}>查看解读</button><button type="button" className="button report-delete" disabled={deletingChartId !== null} onClick={() => onDelete(item)} aria-label="删除报告" title="删除出生信息与全部结果">{deletingChartId === item.chart_id ? "删除中" : "删除报告"}</button></div>
      </article>)}</div></section>)}</div>{groups.length > 0 && <nav className="report-letter-index" aria-label="姓名首字母索引">{groups.map(group => <button type="button" key={group.letter} aria-label={`跳到${group.letter}组`} aria-current={activeLetter === group.letter ? "location" : undefined} onClick={() => { setActiveLetter(group.letter); groupRefs.current[group.letter]?.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" }); }}>{group.letter}</button>)}</nav>}</div>
      {visible.length === 0 && <p className="paper-card search-empty">没有找到匹配的报告，请换个名字试试。</p>}
    </>}
  </>;
}

export function MyAccount({ auth, account, loading, error, navigate, onLogin, onLogout, onRefresh }: {
  auth: AuthState | null; account: CardAccount | null; loading: boolean; error: string; navigate: (page: CustomerRoute) => void;
  onLogin: () => void; onLogout: () => void; onRefresh: () => void;
}) {
  if (!auth) return <AccountPlaceholder profile label="正在读取账户…" />;
  const user = auth?.user;
  const coupons = account ? (account.coupons ?? [account.coupon]).filter(c => c.status === "available") : [];
  const couponCount = auth?.authenticated && account ? `${coupons.length}张` : "—";
  return <>
    <section className="profile-hero"><div className="profile-avatar">{user?.avatar_url ? <img src={user.avatar_url} alt="微信头像" referrerPolicy="no-referrer" onError={e => { e.currentTarget.hidden = true; }} /> : null}<span aria-hidden="true">梅</span></div><h1>{user?.display_name || "欢迎来到四柱知微"}</h1>{user ? <>{(!user.avatar_url || user.display_name === "微信用户") && <button className="text-button" onClick={onLogin}>授权更新微信头像昵称</button>}</> : <button className="button button-primary" disabled={!auth?.enabled} onClick={onLogin}>{!auth ? "正在读取账户…" : auth.enabled ? "微信登录" : "账户服务暂未开放"}</button>}</section>
    <div className="paper-card account-assets" aria-busy={loading}><button onClick={() => navigate("cards")}><b>{auth.authenticated && auth.payments_enabled && !account && loading ? <span className="skeleton-count" aria-label="正在读取解读卡" /> : auth.authenticated && account ? `${account.balance}张` : "—"}</b><span>解读卡</span></button><button onClick={() => navigate("coupon")}><b>{auth.authenticated && auth.payments_enabled && !account && loading ? <span className="skeleton-count" aria-label="正在读取优惠券" /> : couponCount}</b><span>优惠券</span></button></div>
    {error && <p className="inline-error" role="alert">{error} <button className="text-button" onClick={onRefresh}>重新读取</button></p>}
    <div className="paper-card account-links">{([['cards', '购买解读卡'], ['coupon', '优惠券'], ['redeem', '兑换码'], ['service', '联系客服']] as const).map(([page, label]) => <button key={page} onClick={() => navigate(page)}><span className={`account-link-icon icon-${page}`}><CustomerIcon name={page} /></span><span>{label}</span><i aria-hidden="true">›</i></button>)}</div>
    <div className="account-footer"><button className="text-button" onClick={() => navigate("privacy")}>隐私与服务说明</button>{user && <button className="text-button" onClick={onLogout}>退出登录</button>}<span>四柱知微 · v{APP_VERSION}</span></div>
  </>;
}

export function CouponPage({ account, auth, onLogin, error = "", onRetry }: {
  account: CardAccount | null; auth: AuthState | null; onLogin: () => void;
  error?: string; onRetry?: () => void;
}) {
  if (!auth) return <AccountPlaceholder label="正在读取账户…" />;
  if (!auth.authenticated) return <div className="paper-card report-empty"><p>{auth.enabled ? "登录后查看可用优惠券" : "卡券服务暂未开放"}</p>{auth.enabled && <button className="button button-primary" onClick={onLogin}>微信登录</button>}</div>;
  if (!auth.payments_enabled) return <div className="paper-card report-empty"><p>卡券服务暂未开放</p></div>;
  if (error) return <div className="paper-card report-empty" role="alert"><p>{error}</p>{onRetry && <button className="button button-primary" onClick={onRetry}>重新读取</button>}</div>;
  if (!account) return <AccountPlaceholder label="正在读取优惠券…" />;
  const coupons = (account.coupons ?? [account.coupon]).filter(c => c.status === "available");
  if (!coupons.length) return <div className="paper-card report-empty coupon-empty"><p>暂无可用优惠券</p></div>;
  return <>{coupons.map(coupon => <div key={coupon.id} className="paper-card coupon-detail"><span className="coupon-amount">¥<b>{coupon.amount / 100}</b></span><h2>解读卡优惠券</h2><p>{new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai", month: "long", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(coupon.expires_at))} 到期</p></div>)}</>;
}

export function ServicePage() {
  const [notice, setNotice] = useState("");
  return <div className="paper-card service-card"><span className="service-emblem"><CustomerIcon name="service" /></span><h2>四柱知微人工客服</h2><p>报告咨询、使用反馈与人工退款申请</p><strong className="service-qq">QQ 836493209</strong><button className="button button-primary" onClick={async () => { try { await navigator.clipboard.writeText("836493209"); setNotice("QQ 号已复制，请打开 QQ 添加客服。"); } catch { setNotice("当前环境无法自动复制，请长按 QQ 号复制。"); } }}>复制客服 QQ</button><p role="status">{notice}</p><div className="service-notes"><p>报告问题请提供测算时填写的称呼与问题截图。</p><p>退款申请请提供订单号和退款原因，由人工核实处理。提交申请不代表已退款。</p></div></div>;
}

export function PrivacyPage() {
  return <article className="paper-card customer-privacy"><h2>隐私与服务说明</h2><p>姓名可使用称呼或昵称。出生时间、性别和出生地点用于排盘；完整解读报告会保存到当前账户，方便再次阅读。</p><p>微信登录用于识别账户，授权取得的头像与昵称用于本站账户展示。请勿将它们误认为出生资料中的姓名。</p><p>内容属于传统文化参考，不构成医疗、投资、法律意见，不应作为人生重大决定的唯一依据。</p><p>基础排盘免费；开启购买服务后，每份新完整报告使用一张解读卡，卡片无使用期限。重看已有报告及失败板块恢复不重复扣卡。删除后重新生成视为新报告。</p><p>可在报告列表删除出生资料及全部关联结果。订单、账务记录另行保留，以便核对交易和处理退款。</p><p>需要帮助或申请人工退款，请添加 QQ 836493209。</p></article>;
}
