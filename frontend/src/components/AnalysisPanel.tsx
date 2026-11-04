import { useState } from "react";
import { StatusBadge } from "./StatusBadge";
import { READING_TOPICS } from "../data/readingTopics";
import { ReadingNavigation } from "./ReadingNavigation";
import { ReadingPreparation } from "./ReadingPreparation";
import { ReadingCardHeading } from "./ReadingCardHeading";
import type { AnalysisResult, AnalysisSection, AnalysisStatus } from "../types";

interface AnalysisPanelProps {
  active?: boolean;
  status: AnalysisStatus | null;
  result: AnalysisResult | null;
}

function SectionCard({
  section,
  index,
}: {
  section: AnalysisSection;
  index: number;
}) {
  return (
    <article id={`reading-${section.code}`} className={`analysis-section-card reading-paper-card section-${section.status}`} aria-labelledby={`reading-title-${section.code}`}>
      <ReadingCardHeading title={section.title} index={index} id={`reading-title-${section.code}`} focusable />
      {section.status !== "running" && <StatusBadge status={section.status} hideCompleted />}
      {!section.content && section.status === "failed" && (
        <div className="section-error" role="alert"><b>解读暂未完成</b><span>请稍后查看或联系客服处理。</span></div>
      )}
      {section.content ? (
        <div className="analysis-copy">
          {section.content.split(/\n+/).filter(Boolean).map((paragraph, paragraphIndex) => <p key={paragraphIndex}>{paragraph}</p>)}
        </div>
      ) : (
        <div className="section-empty">
          {section.status === "cancelled" ? "本板块已取消" : "本板块暂未完成"}
        </div>
      )}
    </article>
  );
}

export function AnalysisPanel({
  active = true,
  status,
  result,
}: AnalysisPanelProps) {
  if (!status && !result) return null;
  // A result carries the section snapshot associated with its counters. Keep
  // that snapshot intact while the next status/result pair is being fetched.
  const current = result || status!;
  return <AnalysisView key={current.job_id} current={current} result={result} active={active} />;
}

function AnalysisView({ current, result, active }: { current: AnalysisStatus; result: AnalysisResult | null; active: boolean }) {
  const [showContent, setShowContent] = useState(false);
  const rawSections = result?.sections ?? READING_TOPICS.map(({ title, code }) => ({
    code,
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
  // The presentation order is independent of worker completion or API array order.
  const order = new Map<string, number>(READING_TOPICS.map((topic, index) => [topic.code, index]));
  const sections = [...rawSections].sort((a, b) => (order.get(a.code) ?? 99) - (order.get(b.code) ?? 99));
  const preparing = current.status === "pending" || current.status === "running"
    || (current.status === "partial" && sections.some(section => section.status === "pending" || section.status === "running"));
  // During preparation only expose a continuous ready prefix: a later ready
  // section waits for every earlier topic. Retained text remains readable while
  // its background retry runs. Terminal failures still show all available text.
  const readableSections: AnalysisSection[] = [];
  for (const topic of READING_TOPICS) {
    const section = sections.find(item => item.code === topic.code);
    if (!section?.content?.trim()) break;
    readableSections.push(section);
  }
  const visibleSections = preparing ? readableSections : sections.filter(section => section.content || section.status === "failed" || section.status === "cancelled");
  const displayContent = !preparing || showContent;

  return (
    <section className="analysis-panel" aria-labelledby="analysis-title" data-active={active}>
      <h2 id="analysis-title" className="sr-only">详细解读</h2>

      {preparing && <ReadingPreparation completed={current.completed_sections} total={current.total_sections} hasContent={readableSections.length > 0} showContent={showContent} onToggleContent={() => setShowContent(value => !value)} />}

      {displayContent && visibleSections.length > 0 && <ReadingNavigation sections={visibleSections} active={active} />}

      {current.cancel_requested && current.status !== "cancelled" && (
        <div className="notice notice-neutral">已收到取消请求，正在结束本次解读。</div>
      )}
      {current.status === "partial" && !preparing && (
        <div className="notice notice-warning">部分板块尚未完成，已有内容可正常阅读。</div>
      )}
      {current.status === "failed" && (
        <div className="notice notice-error">解读暂未完成，请稍后查看或联系客服处理。</div>
      )}

      {displayContent && <div className="analysis-grid">
        {visibleSections.map((section) => (
          <SectionCard
            key={section.code}
            section={section}
            index={order.get(section.code) ?? sections.indexOf(section)}
          />
        ))}
      </div>}

      {!preparing && <div className="disclaimer">
        <span className="disclaimer-mark" aria-hidden="true">!</span>
        <div>
          <b>传统文化参考声明</b>
          <p>{result?.disclaimer || "命理分析属于传统文化视角的参考性内容，不构成医疗、投资、法律意见，也不应作为婚姻、生育、健康或其他人生重大决定的唯一依据。"}</p>
        </div>
      </div>}
    </section>
  );
}
