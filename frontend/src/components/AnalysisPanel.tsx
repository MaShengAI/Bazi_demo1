import { StatusBadge, STATUS_LABELS } from "./StatusBadge";
import type { AnalysisResult, AnalysisSection, AnalysisStatus, JobStatus } from "../types";

const SECTION_TITLES = [
  "性格特点与行为模式",
  "恋爱情感与婚姻状况预测",
  "子女状况与关系预测",
  "学业发展分析与建议",
  "事业发展预测与建议",
  "财运状况与求财建议",
  "个人健康与灾厄状况预测",
  "大运流年与人生起伏运程",
];

interface AnalysisPanelProps {
  status: AnalysisStatus | null;
  result: AnalysisResult | null;
  actionBusy: string | null;
  onRetry: (code: string) => void;
  onCancel: () => void;
  onDeleteAnalysis: () => void;
  onDeleteChart: () => void;
}

function SectionCard({
  section,
  index,
  busy,
  onRetry,
}: {
  section: AnalysisSection;
  index: number;
  busy: boolean;
  onRetry: () => void;
}) {
  const progress = section.status === "completed" ? 100 : section.status === "running" ? 55 : 0;
  return (
    <article className={`analysis-section-card section-${section.status}`}>
      <header>
        <span className="section-number">{String(index + 1).padStart(2, "0")}</span>
        <div>
          <h4>{section.title}</h4>
          <StatusBadge status={section.status} />
        </div>
      </header>
      <div className="section-progress" aria-label={`${section.title}进度 ${progress}%`}>
        <span style={{ width: `${progress}%` }} />
      </div>
      <dl className="section-stats">
        <div><dt>字符数</dt><dd>{section.char_count.toLocaleString("zh-CN")}</dd></div>
        <div><dt>重试次数</dt><dd>{section.retry_count}</dd></div>
        <div><dt>篇幅</dt><dd>{section.length_status === "ok" ? "适中" : section.length_status === "short" ? "偏短" : section.length_status === "long" ? "偏长" : "—"}</dd></div>
      </dl>
      {section.error && <div className="section-error" role="alert"><b>生成失败</b><span>{section.error}</span></div>}
      {section.content ? (
        <div className="analysis-copy">
          {section.content.split(/\n+/).filter(Boolean).map((paragraph, paragraphIndex) => <p key={paragraphIndex}>{paragraph}</p>)}
        </div>
      ) : (
        <div className="section-empty">
          {section.status === "running" ? <><span className="spinner" />正在撰写本板块…</> : section.status === "failed" ? "本板块未生成内容" : section.status === "cancelled" ? "本板块已取消" : "等待开始"}
        </div>
      )}
      {["failed", "cancelled"].includes(section.status) && (
        <button className="button button-small" type="button" onClick={onRetry} disabled={busy}>
          {busy ? <span className="spinner" /> : "↻"} {busy ? "正在重试" : "重试此板块"}
        </button>
      )}
    </article>
  );
}

export function AnalysisPanel({
  status,
  result,
  actionBusy,
  onRetry,
  onCancel,
  onDeleteAnalysis,
  onDeleteChart,
}: AnalysisPanelProps) {
  if (!status && !result) return null;
  const current = result || status!;
  const progress = current.total_sections ? Math.round((current.completed_sections / current.total_sections) * 100) : 0;
  const sections = result?.sections ?? SECTION_TITLES.map((title, index) => ({
    code: `placeholder-${index}`,
    title,
    status: "pending" as const,
    content: null,
    char_count: 0,
    length_status: null,
    retry_count: 0,
    error: null,
    started_at: null,
    finished_at: null,
  }));
  const canCancel = ["pending", "running", "partial"].includes(current.status);

  return (
    <section className="analysis-panel" aria-labelledby="analysis-title">
      <div className="analysis-hero">
        <div>
          <div className="section-kicker">AI 文化分析</div>
          <div className="analysis-title-line">
            <h2 id="analysis-title">八个主题，逐项生成</h2>
            <StatusBadge status={current.status} />
          </div>
          <p>任务编号 {current.job_id.slice(0, 8)}… · 模型 {current.model_id || "等待分配"}</p>
        </div>
        <div className="overall-progress" aria-label={`总体进度 ${progress}%`}>
          <strong>{progress}<small>%</small></strong>
          <span>{current.completed_sections}/{current.total_sections || 8} 板块完成</span>
        </div>
      </div>

      <div className="progress-track"><span style={{ width: `${progress}%` }} /></div>

      <div className="status-legend" aria-label="任务状态说明">
        {(Object.keys(STATUS_LABELS) as JobStatus[]).map((item) => <StatusBadge key={item} status={item} />)}
      </div>

      {current.cancel_requested && current.status !== "cancelled" && (
        <div className="notice notice-neutral">已收到取消请求，正在等待 worker 安全停止。</div>
      )}
      {current.status === "partial" && (
        <div className="notice notice-warning">部分板块生成失败，已完成内容仍可阅读。你可以单独重试失败板块。</div>
      )}
      {current.status === "failed" && (
        <div className="notice notice-error">任务未能完成。请检查后端 worker 和模型服务状态。</div>
      )}

      <div className="analysis-grid">
        {sections.map((section, index) => (
          <SectionCard
            key={section.code}
            section={section}
            index={index}
            busy={actionBusy === `retry:${section.code}`}
            onRetry={() => onRetry(section.code)}
          />
        ))}
      </div>

      <div className="analysis-actions">
        {canCancel && (
          <button className="button button-outline" type="button" onClick={onCancel} disabled={actionBusy !== null}>
            {actionBusy === "cancel" ? "正在取消" : "取消任务"}
          </button>
        )}
        <button className="button button-danger-ghost" type="button" onClick={onDeleteAnalysis} disabled={actionBusy !== null}>
          {actionBusy === "delete-analysis" ? "正在删除" : "删除分析"}
        </button>
        <button className="button button-danger-ghost" type="button" onClick={onDeleteChart} disabled={actionBusy !== null}>
          {actionBusy === "delete-chart" ? "正在删除" : "删除出生信息与全部结果"}
        </button>
      </div>

      <div className="disclaimer">
        <span className="disclaimer-mark" aria-hidden="true">!</span>
        <div>
          <b>传统文化参考声明</b>
          <p>{result?.disclaimer || "命理分析属于传统文化视角的参考性内容，不构成医疗、投资、法律意见，也不应作为婚姻、生育、健康或其他人生重大决定的唯一依据。"}</p>
        </div>
      </div>
    </section>
  );
}
