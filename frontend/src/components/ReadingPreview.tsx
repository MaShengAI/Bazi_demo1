import { READING_TOPICS } from "../data/readingTopics";
import { ReadingCardHeading } from "./ReadingCardHeading";

function PreviewLock() {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" aria-hidden="true"><rect x="5" y="10" width="14" height="11" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0v3M12 15v2" /></svg>;
}

export function ReadingPreview({ onUnlock, busy, usesCard }: { onUnlock: () => void; busy: boolean; usesCard: boolean }) {
  return <section className="reading-preview" aria-labelledby="reading-preview-title">
    <h2 id="reading-preview-title" className="sr-only">详细解读内容介绍</h2>
    <p className="reading-preview-note">以下为解读内容介绍，获取完整解读后可查看个人报告。</p>
    <div className="reading-preview-cards">
      {READING_TOPICS.map((topic, index) => <article className="paper-card reading-preview-card reading-paper-card" key={topic.code} aria-labelledby={`preview-${topic.code}`}>
        <ReadingCardHeading title={topic.title} index={index} id={`preview-${topic.code}`} />
        <div className="reading-preview-scope"><ul>{topic.items.map(item => <li key={item}>{item}</li>)}</ul></div>
        <div className="preview-unlock"><p>{usesCard ? "使用 1 张解读卡，解锁全部八部分" : "获取完整报告，查看你的个人解读"}</p><button className="button button-primary" type="button" onClick={onUnlock} disabled={busy}><PreviewLock />解锁完整解读</button></div>
      </article>)}
    </div>
  </section>;
}
