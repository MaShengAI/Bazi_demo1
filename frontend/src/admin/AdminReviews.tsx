import { useEffect, useState } from "react";
import { ReviewCard } from "../components/ReviewPages";
import { reviewRequest, reviewStatuses, type ReviewList } from "../reviews";

export function AdminReviews() {
  const [status, setStatus] = useState("pending");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<ReviewList | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [revision, refresh] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setBusy(true); setError(""); setData(null);
    reviewRequest<ReviewList>(`admin/reviews?status=${status}&page=${page}`, { signal: controller.signal })
      .then(setData).catch(e => { if (!controller.signal.aborted) setError(e.message); })
      .finally(() => { if (!controller.signal.aborted) setBusy(false); });
    return () => controller.abort();
  }, [status, page, revision]);
  async function moderate(id: string, value: string) {
    if (busy) return;
    setBusy(true); setError("");
    try {
      await reviewRequest(`admin/reviews/${id}/moderate`, { method: "POST", body: JSON.stringify({ status: value }) });
      refresh(v => v + 1);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  return <section className="admin-panel"><h1>评价管理</h1>
    <p>审核只改变首页展示状态，不影响提交时已发放的赠券。</p>
    <label>审核状态 <select value={status} disabled={busy} onChange={e => { setStatus(e.target.value); setPage(1); }}>
      <option value="">全部</option>{Object.entries(reviewStatuses).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
    </select></label> <button disabled={busy} onClick={() => refresh(v => v + 1)}>刷新</button>
    {error && <p role="alert">{error}</p>}{busy && <p role="status">正在处理…</p>}
    {data && <><p>共 {data.total} 条评价</p>{data.items.map(item => <div key={item.id} style={{ marginBlock: 20 }}>
      <p>{reviewStatuses[item.status || ""]} · 报告编号：{item.job_id}</p>
      <ReviewCard review={item} />
      <button disabled={busy || item.status === "approved"} onClick={() => moderate(item.id, "approved")}>通过并展示</button>
      <button disabled={busy || item.status === "hidden"} onClick={() => moderate(item.id, "hidden")}>隐藏评价</button>
    </div>)}<button disabled={busy || page === 1} onClick={() => setPage(v => v - 1)}>上一页</button>
      <span> 第 {page} 页 </span><button disabled={busy || page * 10 >= data.total} onClick={() => setPage(v => v + 1)}>下一页</button></>}
  </section>;
}
