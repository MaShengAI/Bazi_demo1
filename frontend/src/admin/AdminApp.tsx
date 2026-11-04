import { AdminReviews } from "./AdminReviews";
import { AdminRedemptions } from "./AdminRedemptions";
import { useEffect, useState } from "react";
import type { ChartRequest, ChartResult } from "../types";
import { ChartResultView } from "../components/ChartResultView";
import "./admin.css";

const ROOT = "/api/v1/admin";
const LABELS: Record<string, string> = {
  pending: "等待中", running: "解读中", partial: "部分完成", completed: "已完成",
  failed: "未完成", cancelled: "已取消",
};
type AdminSession = { authenticated: boolean; username: string | null };
type ReportItem = {
  id: string; chart_id: string; user_id: string | null; name: string; status: string;
  model: string; birth_local_datetime: string; gender: string; created_at: string;
  completed_sections: number; total_sections: number;
};
type ReportList = { items: ReportItem[]; total: number; page: number; page_size: number };
type ReportDetail = {
  id: string; chart_id: string; user_id: string | null; status: string; model: string;
  prompt_version: string; created_at: string; finished_at: string | null;
  request: ChartRequest; chart: ChartResult;
  sections: { code: string; title: string; status: string; content: string | null;
    char_count: number; retry_count: number; length_status: string | null;
    error: string | null; error_code: string | null }[];
};
type Filters = { q: string; status: string; start: string; end: string };
const EMPTY: Filters = { q: "", status: "", start: "", end: "" };

class AdminApiError extends Error {
  constructor(message: string, public status: number) { super(message); }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(ROOT + path, {
    ...init, credentials: "same-origin", cache: "no-store",
    headers: init?.body ? { "Content-Type": "application/json" } : undefined,
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new AdminApiError(data.error?.message || "暂时无法读取，请稍后再试。", response.status);
  }
  return response.status === 204 ? undefined as T : response.json();
}

function createdTime(value: string | null) {
  return value ? new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai", dateStyle: "medium", timeStyle: "short", hour12: false,
  }).format(new Date(value)) : "—";
}

function Badge({ status }: { status: string }) {
  return <span className={`admin-badge admin-status-${status}`}>{LABELS[status] || status}</span>;
}

export function AdminApp() {
  const [view, setView] = useState(() => ["codes", "reviews"].includes(new URLSearchParams(location.search).get("view") || "") ? new URLSearchParams(location.search).get("view")! : "reports");
  const [session, setSession] = useState<AdminSession | null>(null);
  const [initializing, setInitializing] = useState(true);
  const [error, setError] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [filters, setFilters] = useState<Filters>(EMPTY);
  const [applied, setApplied] = useState<Filters>(EMPTY);
  const [page, setPage] = useState(1);
  const [revision, setRevision] = useState(0);
  const [list, setList] = useState<ReportList | null>(null);
  const [selected, setSelected] = useState<string | null>(() => new URLSearchParams(location.search).get("report"));
  const [detail, setDetail] = useState<ReportDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [tab, setTab] = useState<"report" | "chart">("report");

  useEffect(() => {
    document.title = "四柱知微 · 管理后台";
    let active = true;
    request<AdminSession>("/session").then((value) => { if (active) setSession(value); })
      .catch((reason) => { if (active) setError(reason.message); })
      .finally(() => { if (active) setInitializing(false); });
    const pop = () => { setSelected(new URLSearchParams(location.search).get("report")); setView(["codes", "reviews"].includes(new URLSearchParams(location.search).get("view") || "") ? new URLSearchParams(location.search).get("view")! : "reports"); };
    window.addEventListener("popstate", pop);
    return () => { active = false; window.removeEventListener("popstate", pop); };
  }, []);

  useEffect(() => {
    if (!session?.authenticated || view !== "reports") return;
    const abort = new AbortController();
    setLoading(true); setError("");
    if (selected) { setDetail(null); setTab("report"); }
    const params = new URLSearchParams({ page: String(page) });
    for (const [key, value] of Object.entries(applied)) {
      if (value) params.set(key, value);
    }
    request<ReportDetail | ReportList>(selected ? `/reports/${encodeURIComponent(selected)}` : `/reports?${params}`, { signal: abort.signal })
      .then((value) => {
        if (abort.signal.aborted) return;
        if (selected) setDetail(value as ReportDetail); else setList(value as ReportList);
      })
      .catch((reason) => {
        if (abort.signal.aborted) return;
        if (reason.status === 401) {
          setSession({ authenticated: false, username: null }); setList(null); setDetail(null);
        }
        setError(reason.message);
      }).finally(() => { if (!abort.signal.aborted) setLoading(false); });
    return () => abort.abort();
  }, [session?.authenticated, selected, applied, page, revision, view]);

  async function login(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      const value = await request<AdminSession>("/login", { method: "POST", body: JSON.stringify({ username, password }) });
      setSession(value);
    } catch (reason) { setError((reason as Error).message); }
    finally { setPassword(""); setBusy(false); }
  }

  async function logout() {
    setBusy(true); setError("");
    try {
      await request<void>("/logout", { method: "POST" });
      setSession({ authenticated: false, username: null }); setList(null); setDetail(null);
    } catch (reason) { setError((reason as Error).message); }
    finally { setBusy(false); }
  }

  function navigate(id: string | null) {
    setView("reports");
    setSelected(id); setDetail(null); setError("");
    history.pushState({}, "", id ? `/admin?report=${encodeURIComponent(id)}` : "/admin");
    window.scrollTo({ top: 0, behavior: "instant" });
  }

  if (initializing) return <main className="admin-shell admin-login-shell"><p role="status">正在连接管理后台…</p></main>;
  if (!session?.authenticated) return <main className="admin-shell admin-login-shell">
    <div className="admin-login-card">
      <a className="admin-brand" href="/">四柱知微<span>运营管理</span></a>
      <span className="admin-readonly">独立管理员登录</span>
      <h1>管理后台登录</h1>
      <p className="admin-muted">查阅报告与命盘资料，管理兑换码。</p>
      <form onSubmit={login}>
        <label>管理员账号<input autoComplete="username" required maxLength={32} value={username} onChange={(e) => setUsername(e.target.value)} /></label>
        <label>密码<input type="password" autoComplete="current-password" required maxLength={256} value={password} onChange={(e) => setPassword(e.target.value)} /></label>
        {error && <p className="admin-error" role="alert">{error}</p>}
        <button className="admin-primary" disabled={busy || !session}>{busy ? "正在登录…" : "登录后台"}</button>
      </form>
      <p className="admin-footnote">与客户微信登录分开 · 登录有效期 1 小时</p>
    </div>
  </main>;

  return <div className="admin-shell">
    <header className="admin-topbar">
      <a className="admin-brand" href="/admin" onClick={(e) => { e.preventDefault(); navigate(null); }}>四柱知微<span>运营管理</span></a>
      <div><span className="admin-readonly">报告只读</span><span className="admin-username">{session.username}</span><button onClick={logout} disabled={busy}>退出登录</button></div>
    </header>
    <main className="admin-main">
      <nav className="admin-tabs" aria-label="后台功能"><button aria-current={view === "reports" ? "page" : undefined} onClick={() => navigate(null)}>报告管理</button><button aria-current={view === "codes" ? "page" : undefined} onClick={() => { setView("codes"); setError(""); history.pushState({}, "", "/admin?view=codes"); }}>兑换码管理</button><button aria-current={view === "reviews" ? "page" : undefined} onClick={() => { setView("reviews"); setError(""); history.pushState({}, "", "/admin?view=reviews"); }}>评价管理</button></nav>
      {view === "codes" ? <AdminRedemptions /> : view === "reviews" ? <AdminReviews /> : <>
      <div className="admin-heading">
        <div><p className="admin-eyebrow">报告中心</p><h1>{selected ? "报告详情" : "全部解读报告"}</h1>
          <p className="admin-muted">{selected ? "查看原始资料、命盘与完整正文。" : "按姓名、报告编号和创建日期查找，列表时间均为北京时间。"}</p></div>
        <div className="admin-toolbar">{selected && <button onClick={() => navigate(null)}>返回报告列表</button>}
          <button disabled={loading} onClick={() => setRevision((r) => r + 1)}>{loading ? "读取中…" : "刷新数据"}</button></div>
      </div>
      {error && <p className="admin-error" role="alert">{error}</p>}
      {!selected && <>
        <form className="admin-filters" onSubmit={(e) => { e.preventDefault(); setApplied({ ...filters }); setPage(1); }}>
          <label className="admin-search">姓名 / 报告编号<input placeholder="输入姓名或报告编号" maxLength={100} value={filters.q} onChange={(e) => setFilters({ ...filters, q: e.target.value })} /></label>
          <label>报告状态<select value={filters.status} onChange={(e) => setFilters({ ...filters, status: e.target.value })}><option value="">全部状态</option>{Object.entries(LABELS).map(([value, text]) => <option key={value} value={value}>{text}</option>)}</select></label>
          <label>开始日期<input type="date" value={filters.start} onChange={(e) => setFilters({ ...filters, start: e.target.value })} /></label>
          <label>结束日期<input type="date" min={filters.start || undefined} value={filters.end} onChange={(e) => setFilters({ ...filters, end: e.target.value })} /></label>
          <button className="admin-primary" disabled={loading}>查询</button>
          <button type="button" onClick={() => { setFilters(EMPTY); setApplied(EMPTY); setPage(1); }}>重置</button>
        </form>
        <section className="admin-card" aria-label="报告列表">
          <div className="admin-list-summary"><b>共 {list?.total ?? "—"} 份报告</b><span>每页 20 条</span></div>
          <div className="admin-table-wrap"><table><thead><tr><th>姓名 / 报告编号</th><th>出生资料</th><th>状态 / 进度</th><th>创建时间（北京）</th><th>操作</th></tr></thead><tbody>
            {list?.items.map((item) => <tr key={item.id}><td><b>{item.name}</b><code>{item.id}</code></td>
              <td>{item.gender === "male" ? "男" : "女"}<small>{item.birth_local_datetime?.replace("T", " ") || "—"}</small></td>
              <td><Badge status={item.status} /><small>{item.completed_sections} / {item.total_sections} 板块</small></td>
              <td>{createdTime(item.created_at)}</td><td><button className="admin-link" onClick={() => navigate(item.id)}>查看报告</button></td></tr>)}
          </tbody></table></div>
          {loading && <p className="admin-empty" role="status">正在读取报告…</p>}
          {!loading && !list?.items.length && <p className="admin-empty">没有符合条件的报告。</p>}
          <div className="admin-pagination"><span>第 {page} / {Math.max(1, Math.ceil((list?.total || 0) / 20))} 页</span>
            <button disabled={loading || page === 1} onClick={() => setPage((p) => p - 1)}>上一页</button>
            <button disabled={loading || page * 20 >= (list?.total || 0)} onClick={() => setPage((p) => p + 1)}>下一页</button></div>
        </section>
      </>}
      {selected && loading && <p className="admin-empty" role="status">正在读取报告详情…</p>}
      {selected && detail && <>
        <section className="admin-card admin-profile">
          <div><h2>{detail.request.name || "未命名命盘"}</h2><Badge status={detail.status} /></div>
          <dl><div><dt>出生时间（当地）</dt><dd>{detail.request.birth_local_datetime.replace("T", " ")}</dd></div>
            <div><dt>性别 / 出生地点</dt><dd>{detail.request.gender === "male" ? "男" : "女"} · {detail.chart.location.name}</dd></div>
            <div><dt>创建时间（北京）</dt><dd>{createdTime(detail.created_at)}</dd></div>
            <div><dt>完成时间（北京）</dt><dd>{createdTime(detail.finished_at)}</dd></div>
            <div><dt>报告编号</dt><dd className="admin-mono">{detail.id}</dd></div>
            <div><dt>所属用户编号</dt><dd className="admin-mono">{detail.user_id || "未关联微信账号"}</dd></div>
            <div><dt>使用模型</dt><dd>{detail.model}</dd></div><div><dt>提示词版本</dt><dd>{detail.prompt_version}</dd></div></dl>
        </section>
        <div className="admin-tabs" role="tablist" aria-label="报告详情分类">
          <button role="tab" aria-selected={tab === "report"} onClick={() => setTab("report")}>解读正文</button>
          <button role="tab" aria-selected={tab === "chart"} onClick={() => setTab("chart")}>命盘资料</button>
        </div>
        {tab === "chart" ? <section className="admin-chart" role="tabpanel" aria-label="命盘资料"><ChartResultView chart={detail.chart} /></section> :
          <div className="admin-detail-grid" role="tabpanel" aria-label="解读正文">
            <nav className="admin-card admin-outline" aria-label="板块目录"><b>板块目录</b>{detail.sections.map((s, index) => <a key={s.code} href={`#admin-section-${s.code}`}>{String(index + 1).padStart(2, "0")} · {s.title}</a>)}</nav>
            <div>{detail.sections.map((s, index) => <article className="admin-card admin-section" id={`admin-section-${s.code}`} key={s.code}>
              <header><h2>{String(index + 1).padStart(2, "0")} · {s.title}</h2><Badge status={s.status} /></header>
              <div className="admin-internal-stats">字符数 {s.char_count.toLocaleString("zh-CN")} · 重试 {s.retry_count} 次 · 篇幅 {s.length_status === "ok" ? "适中" : s.length_status === "short" ? "偏短" : s.length_status === "long" ? "偏长" : "—"}</div>
              {s.error && <p className="admin-error">{s.error_code ? `${s.error_code}：` : ""}{s.error}</p>}
              <div className="admin-copy">{s.content || "暂无正文。"}</div>
            </article>)}</div>
          </div>}
      </>}
      <footer className="admin-footer">只读查询 · 此后台不提供编辑、删除、重新生成或支付操作</footer>
      </>}
    </main>
  </div>;
}
