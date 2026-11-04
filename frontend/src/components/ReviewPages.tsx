import { useEffect, useRef, useState } from "react";
import type { AuthState } from "../types";
import { reviewFaces, reviewRequest, reviewTextLength, type Review, type ReviewList, type ReviewOptions } from "../reviews";
import "./ReviewPages.css";
import { ReportPlaceholder } from "./ReportPlaceholder";
import { zodiacForName } from "../data/zodiac";

const date = (value: string) => new Intl.DateTimeFormat("zh-CN", {
  timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit",
}).format(new Date(value));
const elements: Record<string, string> = Object.fromEntries(Array.from("甲乙丙丁戊己庚辛壬癸子丑寅卯辰巳午未申酉戌亥").map((c, i) => [c, Array.from("木木火火土土金金水水水土木木土火火土金金土水")[i]]));

function ReviewGenderIcon({ gender }: { gender: string }) {
  if (gender !== "male" && gender !== "female") return null;
  const male = gender === "male";
  return <svg className={`review-gender review-gender-${gender}`} viewBox="0 0 24 24" role="img" aria-label={male ? "男" : "女"} focusable="false">
    {male ? <><circle cx="8" cy="15" r="5.3" /><path d="M11.75 11.25 21 2M15 2h6v6" /></> : <g transform="rotate(-30 9 7)"><circle cx="9" cy="7" r="5.4" /><path d="M9 12.4V22M5 18.5h8" /></g>}
  </svg>;
}

export function ReviewCard({ review, preview = false }: { review: Review; preview?: boolean }) {
  const p = review.profile;
  const zodiac = zodiacForName(p.zodiac);
  return <article className="paper-card customer-review-card">
    <header className="review-person">
      {p.avatar_url ? <img className="review-avatar" src={p.avatar_url} alt="" referrerPolicy="no-referrer" onError={e => { e.currentTarget.style.visibility = "hidden"; }} /> : <span className="review-avatar review-avatar-fallback" aria-hidden="true">{p.nickname}</span>}
      <div className="review-person-name"><div className="review-nickname"><strong>{p.nickname}**</strong><ReviewGenderIcon gender={p.gender} /></div><p>{p.cohort}</p></div>
      <div className="review-score" aria-label={`${review.rating}星`}><span className="review-score-face" aria-hidden="true">{review.face}</span><span className="review-score-stars" aria-hidden="true">{Array.from({ length: 5 }, (_, i) => <svg key={i} className={`review-star${i < review.rating ? " lit" : ""}`} viewBox="0 0 24 24"><path d="m12 2 3.1 6.3 7 .9-5.1 5 1.2 7-6.2-3.3-6.2 3.3 1.2-7-5.1-5 7-.9Z" /></svg>)}</span></div>
    </header>
    {review.content && <p className="review-body">{review.content}</p>}
    <div className="review-chart"><div className="review-zodiac">{zodiac && <img className="review-zodiac-avatar" src={zodiac.image} alt={`生肖属${zodiac.name}`} width={40} height={40} loading="lazy" decoding="async" onError={e => { e.currentTarget.hidden = true; }} />}<div className="review-zodiac-copy"><span>生肖：{p.zodiac || "—"}</span><span>日主：{p.day_master || "—"}</span></div></div><div className="review-pillars" aria-label={`八字：${p.pillars.join(" ")}`}>{p.pillars.map((pillar, i) => <span key={i}>{Array.from(pillar).map((c, j) => <b key={j} data-element={elements[c]}>{c}</b>)}</span>)}</div></div>
    <div className="review-date">{preview ? "提交日期" : date(review.created_at)} · {p.province}</div>
  </article>;
}

export function PublicReviews() {
  const [list, setList] = useState<Review[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController(); setBusy(true); setError("");
    reviewRequest<ReviewList>(`reviews?page=${page}`, { signal: controller.signal }).then(data => {
      if (controller.signal.aborted) return;
      if (!Array.isArray(data.items) || !Number.isInteger(data.total)) throw new Error("评价暂时无法读取，请稍后重试。");
      setList(old => page === 1 ? data.items : [...old, ...data.items.filter(v => !old.some(r => r.id === v.id))]);
      setTotal(data.total); setLoaded(true);
    }).catch(e => { if (!controller.signal.aborted) setError((e as Error).message); })
      .finally(() => { if (!controller.signal.aborted) setBusy(false); });
    return () => controller.abort();
  }, [page, revision]);
  return <section className="customer-reviews" aria-labelledby="reviews-title">
    <div className="ornament-heading"><span /><h2 id="reviews-title">用户评价</h2><span /></div>
    <div className="review-feed">{list.map(r => <ReviewCard key={r.id} review={r} />)}</div>
    {loaded && list.length === 0 && <div className="paper-card reviews-empty"><span className="review-flower" aria-hidden="true">❀</span><p>每一份用心，都期待你的回响</p></div>}
    {error && <p role="alert">{error}<button className="text-button" onClick={() => setRevision(r => r + 1)}>重新加载</button></p>}
    {list.length < total && <button className="text-button review-load-more" disabled={busy} onClick={() => setPage(p => p + 1)}>{busy ? "加载中…" : "加载更多评价"}</button>}
  </section>;
}

const ratingDescriptions = [
  "很不满意，体验糟糕", "不太满意，内容还有改进空间", "一般，部分内容有帮助",
  "比较满意，内容清楚，有参考价值", "非常满意，解读细致，超出预期",
];
const suggestedReviews = [
  "解读挺详细的，值得一看。", "有几处说到心里了。", "看完对自己更了解了。",
  "比预想的好。", "有些符合，有些不太像。", "还行，希望再具体点。", "有些地方没看懂。",
];

export function ReviewPage({ auth, reportId, onLogin, onSubmitted, onReturn }: { reportId?: string; auth: AuthState | null; onLogin: () => void; onSubmitted: () => void; onReturn?: () => void }) {
  const [options, setOptions] = useState<ReviewOptions | null>(null);
  const selected = reportId || "";
  const [rating, setRating] = useState(5);
  const [content, setContent] = useState("");
  const [suggestionMessage, setSuggestionMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(false);
  const [revision, setRevision] = useState(0);
  const lock = useRef(false);
  useEffect(() => {
    if (!auth?.authenticated || !reportId) return;
    const controller = new AbortController();
    reviewRequest<ReviewOptions>("reviews/mine", { signal: controller.signal }).then(data => {
      if (controller.signal.aborted) return;
      setOptions(data);
    }).catch(e => { if (!controller.signal.aborted) setError((e as Error).message); });
    return () => controller.abort();
  }, [auth?.authenticated, reportId, revision]);
  if (!auth) return null;
  if (!auth.authenticated) return <section className="paper-card report-empty"><p>微信登录后，可为已完成的完整解读报告评价。</p><button className="button button-primary" onClick={onLogin}>微信登录</button></section>;
  if (!reportId) return <div className="paper-card report-empty"><p>请从已解锁的报告底部进入评价。</p></div>;
  if (success) return <section className="paper-card review-success" role="status">
    <svg className="review-success-icon" viewBox="0 0 48 48" aria-hidden="true"><circle cx="24" cy="24" r="20" /><path d="m14 24 7 7 14-15" /></svg>
    <h2>评价成功</h2>
    {onReturn && <button type="button" className="text-button" onClick={onReturn}>返回报告</button>}
  </section>;
  const choice = options?.items.find(i => i.job_id === selected);
  const length = reviewTextLength(content.trim());
  async function submitReview() {
    if (lock.current || !options || !choice || choice.review || length < 2 || length > 100) return;
    lock.current = true; setBusy(true); setError("");
    try {
      const result = await reviewRequest<{ review: Review }>("reviews", { method: "POST", body: JSON.stringify({ job_id: selected, rating, content: content.trim(), consent: true, consent_version: options.consent_version }) });
      setOptions(old => old && { ...old, items: old.items.map(i => i.job_id === selected ? { ...i, review: result.review } : i) });
      setSuccess(true); onSubmitted();
    } catch (reason) { setError((reason as Error).message); }
    finally { lock.current = false; setBusy(false); }
  }
  return <section className="review-editor">
    {error && <p role="alert">{error}<button className="text-button" onClick={() => { setError(""); setRevision(r => r + 1); }}>刷新</button></p>}
    {!options && !error && <ReportPlaceholder label="正在载入评价" />}
    {options && !choice && <div className="paper-card report-empty"><p>完整解读完成后，即可在这里评价。</p></div>}
    {options && choice && <div className="paper-card review-form-card">
      {choice?.review ? <><p role="status">此报告已评价</p><ReviewCard review={choice.review} /></> : choice && <form onSubmit={e => {
        e.preventDefault();
        void submitReview();
      }}>
        <fieldset className="review-rating" disabled={busy}><legend>感谢对我们的支持！可对本次解读进行评价</legend>{[5, 4, 3, 2, 1].map(value => <label key={value} className={rating === value ? "is-selected" : ""}>
          <input type="radio" name="review-rating" value={value} checked={rating === value} aria-label={`${value}星 ${ratingDescriptions[value - 1]}`} onChange={() => setRating(value)} />
          <span className="review-rating-face" aria-hidden="true">{reviewFaces[value - 1]}</span><span className="review-rating-description">{ratingDescriptions[value - 1]}</span>
        </label>)}</fieldset>
        <textarea id="review-text" aria-label="评价内容" aria-describedby="review-count" value={content} disabled={busy} maxLength={2000} placeholder="您的评价是我们前进的动力" onChange={e => { setContent(e.target.value); setSuggestionMessage(""); }} /><p id="review-count" className="review-count" aria-live="polite">{length}/100</p>
        <div className="review-suggestions" role="group" aria-label="可选评价短句">{suggestedReviews.map(text => <button key={text} type="button" disabled={busy} onClick={() => {
          if (content.includes(text)) { setSuggestionMessage("这句已经添加过了，可以在输入框中修改。"); return; }
          const next = content.trim() ? `${content.trim()} ${text}` : text;
          if (reviewTextLength(next) > 100) { setSuggestionMessage("添加后将超过100字，请先精简输入框中的文字。"); return; }
          setContent(next); setSuggestionMessage("");
        }}>{text}</button>)}</div>
        {suggestionMessage && <p className="review-suggestion-message" role="status">{suggestionMessage}</p>}
        <button className="button button-primary" disabled={busy || length < 2 || length > 100}>{busy ? "正在提交…" : "提交评价"}</button>
      </form>}
    </div>}
  </section>;
}
