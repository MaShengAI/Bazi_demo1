import { useEffect, useRef, useState } from "react";

type Batch = { id: string; label: string; kind: "cards" | "coupon"; value: number; quantity: number; expires_at: string; created_at: string };
type Code = { id: string; masked_code: string; batch: Batch; status: string; redeemed_by: string | null; redeemed_at: string | null; disabled_by: string | null };
type List = { items: Code[]; total: number; batches: Batch[] };
const LABELS: Record<string, string> = { unused: "未兑换", redeemed: "已兑换", expired: "已过期", disabled: "已停用" };
const time = (value: string | null) => value ? new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai", dateStyle: "short", timeStyle: "short", hour12: false }).format(new Date(value)) : "—";
const reward = (batch: Batch) => batch.kind === "cards" ? `${batch.value} 张解读卡` : `¥${batch.value / 100} 优惠券`;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch("/api/v1/admin/redemptions" + path, { ...init, credentials: "same-origin", cache: "no-store", headers: init?.body ? { "Content-Type": "application/json" } : undefined });
  if (!res.ok) { const data = await res.json().catch(() => ({})); throw new Error(data.error?.message || "操作失败，请刷新核对；登录过期时请重新登录。"); }
  return res.status === 204 ? undefined as T : res.json();
}

export function AdminRedemptions() {
  const [kind, setKind] = useState<"cards" | "coupon">("cards");
  const [value, setValue] = useState("1");
  const [quantity, setQuantity] = useState("10");
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [generated, setGenerated] = useState<{ batch: Batch; codes: string[] } | null>(null);
  const [downloaded, setDownloaded] = useState(false);
  const [list, setList] = useState<List | null>(null);
  const [batchId, setBatchId] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [revision, setRevision] = useState(0);
  const [selection, setSelection] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [operation, setOperation] = useState<{ action: "disable" | "delete"; codes: Code[] } | null>(null);
  const [notice, setNotice] = useState("");
  const key = useRef(crypto.randomUUID());
  const lock = useRef(false);
  // Editing a form is a new intentional request; network retries retain the same key.
  function edited() { key.current = crypto.randomUUID(); }
  useEffect(() => {
    let active = true;
    setLoading(true); setSelection([]);
    const params = new URLSearchParams({ page: String(page), batch_id: batchId, status });
    request<List>(`?${params}`).then(result => { if (active) setList(result); }).catch(reason => { if (active) setError(reason.message); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [batchId, status, page, revision]);

  const chosen = list?.items.filter(code => selection.includes(code.id)) || [];
  const deletable = (code: Code) => code.status === "disabled" || code.status === "redeemed";
  const allSelected = Boolean(list?.items.length && list.items.every(code => selection.includes(code.id)));
  function toggle(id: string) { setSelection(old => old.includes(id) ? old.filter(value => value !== id) : [...old, id]); }
  async function confirmOperation() {
    if (lock.current || !operation) return;
    lock.current = true; setBusy(true); setError(""); setNotice("");
    try {
      const result = await request<{ changed: number }>(`/bulk-${operation.action}`, { method: "POST", body: JSON.stringify({ code_ids: operation.codes.map(code => code.id) }) });
      setNotice(`已${operation.action === "disable" ? "停用" : "删除"} ${result.changed} 个兑换码。`);
      if (operation.action === "delete" && operation.codes.length === list?.items.length && page > 1) setPage(p => p - 1);
      setSelection([]); setRevision(r => r + 1);
    } catch (reason) { setError((reason as Error).message); setRevision(r => r + 1); }
    finally { setOperation(null); setBusy(false); lock.current = false; }
  }

  function download() {
    if (!generated) return;
    // Do not interpolate administrator labels into CSV: prevents spreadsheet formulas.
    const rows = ["兑换码,奖励,兑换码到期时间", ...generated.codes.map(code => `${code},${reward(generated.batch)},${time(generated.batch.expires_at)}`)];
    const url = URL.createObjectURL(new Blob(["\uFEFF" + rows.join("\r\n")], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a"); link.href = url; link.download = `redemption-${generated.batch.id}.csv`; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000); setDownloaded(true);
  }

  return <>
    <div className="admin-heading"><div><p className="admin-eyebrow">运营管理</p><h1>兑换码管理</h1><p className="admin-muted">一码一次 · 生成后一个月内可兑换 · 优惠券兑换后 7 天到期</p></div><button onClick={() => { setError(""); setRevision(r => r + 1); }}>刷新列表</button></div>
    {error && <p className="admin-error" role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    <section className="admin-card admin-code-generator"><h2>批量生成</h2>
      <form className="admin-code-form" onSubmit={async e => {
        e.preventDefault(); if (lock.current || generated) return;
        lock.current = true; setBusy(true); setError("");
        try {
          const result = await request<{ batch: Batch; codes: string[] }>("/batches", { method: "POST", body: JSON.stringify({ kind, value: kind === "coupon" ? Math.round(Number(value) * 100) : Number(value), quantity: Number(quantity), label: label.trim(), request_key: key.current }) });
          setGenerated(result); setDownloaded(false); setRevision(r => r + 1);
        } catch (reason) { setError((reason as Error).message); }
        finally { setBusy(false); lock.current = false; }
      }}>
        <label>批次名称<input required maxLength={80} value={label} disabled={busy || !!generated} onChange={e => { setLabel(e.target.value); edited(); }} placeholder="例如：十一月客户赠礼" /></label>
        <label>奖励类型<select disabled={busy || !!generated} value={kind} onChange={e => { const k = e.target.value as typeof kind; setKind(k); setValue(k === "cards" ? "1" : "50"); edited(); }}><option value="cards">解读卡</option><option value="coupon">优惠券</option></select></label>
        <label>{kind === "cards" ? "每码解读卡（张）" : "每码优惠券（元）"}<input type="number" required min={kind === "cards" ? 1 : 0.01} max={kind === "cards" ? 100 : 1000} step={kind === "cards" ? 1 : 0.01} value={value} disabled={busy || !!generated} onChange={e => { setValue(e.target.value); edited(); }} /></label>
        <label>生成数量<input type="number" required min={1} max={1000} step={1} value={quantity} disabled={busy || !!generated} onChange={e => { setQuantity(e.target.value); edited(); }} /></label>
        <button className="admin-primary" disabled={busy || !!generated}>{busy ? "生成中…" : "生成兑换码"}</button>
      </form>
      <p className="admin-muted">每批最多 1000 个。明码只在生成后本次页面提供，请立即导出保管；关闭页面后无法再次查看完整兑换码。</p>
      {kind === "coupon" && <p className="admin-muted">每单使用一张优惠券，超出订单金额的部分不结转，订单最低实付 ¥0.01。</p>}
      {generated && <div className="admin-generated" role="status"><h3>已生成 {generated.codes.length} 个 · {reward(generated.batch)}</h3><p>到期：{time(generated.batch.expires_at)}</p>
        <div className="admin-toolbar"><button className="admin-primary" onClick={download}>导出本批兑换码 CSV</button><button disabled={!downloaded} onClick={() => { setGenerated(null); setDownloaded(false); edited(); }}>生成下一批</button></div>
        <textarea aria-label="本次生成的兑换码" readOnly rows={5} value={generated.codes.join("\n")} />
      </div>}
    </section>
    <div className="admin-code-filter"><label>批次<select disabled={busy} value={batchId} onChange={e => { setBatchId(e.target.value); setPage(1); }}><option value="">全部批次</option>{list?.batches.map(b => <option key={b.id} value={b.id}>{b.label} · {reward(b)} · {time(b.created_at)}</option>)}</select></label><label>状态<select disabled={busy} value={status} onChange={e => { setStatus(e.target.value); setPage(1); }}><option value="">全部状态</option>{Object.entries(LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label></div>
    <section className="admin-card"><div className="admin-list-summary">共 {list?.total ?? "—"} 个兑换码</div>
      <div className="admin-toolbar"><span>已选 {chosen.length} 个</span><button disabled={busy || loading || !chosen.length || chosen.some(code => code.status !== "unused")} onClick={() => setOperation({ action: "disable", codes: chosen })}>批量停用</button><button disabled={busy || loading || !chosen.length || chosen.some(code => !deletable(code))} onClick={() => setOperation({ action: "delete", codes: chosen })}>批量删除</button></div>
      <p className="admin-muted">可全选本页；停用仅限未兑换且未过期的码，删除仅限已停用或已兑换的码。</p>
      {loading && <p role="status">正在读取兑换码…</p>}<div className="admin-table-wrap"><table><thead><tr><th><input type="checkbox" aria-label="全选本页" disabled={busy || loading || !list?.items.length} checked={allSelected} onChange={e => setSelection(e.target.checked ? list?.items.map(code => code.id) || [] : [])} /></th><th>兑换码尾号 / 批次</th><th>奖励</th><th>到期时间</th><th>状态</th><th>兑换人 / 时间</th><th>操作</th></tr></thead><tbody>{list?.items.map(code => <tr key={code.id}><td><input type="checkbox" aria-label={`选择兑换码 ${code.masked_code}`} disabled={busy || loading} checked={selection.includes(code.id)} onChange={() => toggle(code.id)} /></td><td><b>{code.masked_code}</b><small>{code.batch.label}</small></td><td>{reward(code.batch)}</td><td>{time(code.batch.expires_at)}</td><td>{LABELS[code.status]}</td><td><small>{code.redeemed_by || "—"}</small><small>{time(code.redeemed_at)}</small></td><td>{code.status === "unused" ? <button disabled={busy || loading} onClick={() => setOperation({ action: "disable", codes: [code] })}>停用</button> : <>{code.disabled_by && <small>停用人：{code.disabled_by}</small>}{deletable(code) ? <button disabled={busy || loading} onClick={() => setOperation({ action: "delete", codes: [code] })}>删除</button> : "—"}</>}</td></tr>)}</tbody></table></div>
      {list && !list.items.length && <p className="admin-empty">暂无符合条件的兑换码</p>}
      <div className="admin-pagination"><span>第 {page} 页</span><button disabled={busy || loading || page === 1} onClick={() => setPage(p => p - 1)}>上一页</button><button disabled={busy || loading || !list || page * 50 >= list.total} onClick={() => setPage(p => p + 1)}>下一页</button></div>
    </section>
    {operation && <div className="admin-code-dialog" role="dialog" aria-modal="true" aria-labelledby="code-operation-title"><section className="admin-card">
      <h2 id="code-operation-title">{operation.action === "disable" ? "停用" : "删除"}这 {operation.codes.length} 个兑换码？</h2>
      <p>{operation.action === "disable" ? "停用后无法兑换，且不能重新启用。" : "删除后将从管理列表移除；已发放的解读卡、优惠券及兑换凭据仍保留，不会回收用户权益。"}</p>
      <div className="admin-toolbar"><button disabled={busy} onClick={() => setOperation(null)}>取消</button><button className="admin-primary" disabled={busy} onClick={() => void confirmOperation()}>{busy ? "正在处理…" : operation.action === "disable" ? "确认停用" : "确认删除"}</button></div>
    </section></div>}

  </>;
}
