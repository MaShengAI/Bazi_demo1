import { useId } from "react";
import "./ReadingPreparation.css";

function RingLabels({ characters, radius, className }: { characters: string; radius: number; className: string }) {
  const labels = [...characters];
  return <g className={className}>
    {labels.map((label, index) => {
      const angle = index * 360 / labels.length;
      return <g key={label} transform={`rotate(${angle} 170 170)`}>
        <line x1="170" y1={170 - radius - 19} x2="170" y2={170 - radius + 19} transform={`rotate(${-180 / labels.length} 170 170)`} />
        <text x="170" y={170 - radius} textAnchor="middle" dominantBaseline="central">{label}</text>
      </g>;
    })}
  </g>;
}

export function ReadingCompass() {
  const id = useId().replace(/:/g, "");
  return <div className="reading-compass" aria-hidden="true">
    <svg viewBox="0 0 340 340" focusable="false">
      <defs>
        <radialGradient id={`${id}-outer`}><stop stopColor="#e57f6c" /><stop offset="1" stopColor="#bd4a3e" /></radialGradient>
        <radialGradient id={`${id}-inner`}><stop stopColor="#f6b798" /><stop offset="1" stopColor="#e28b71" /></radialGradient>
        <radialGradient id={`${id}-gold`}><stop stopColor="#ffedca" /><stop offset="1" stopColor="#eed0a2" /></radialGradient>
      </defs>
      <circle cx="170" cy="170" r="159" fill={`url(#${id}-outer)`} stroke="#b44c40" strokeWidth="2" />
      <circle cx="170" cy="170" r="154" className="compass-rim" />
      <g className="compass-ring compass-branches">
        <RingLabels characters="子丑寅卯辰巳午未申酉戌亥" radius={135} className="compass-outer-labels" />
      </g>
      <circle cx="170" cy="170" r="112" fill={`url(#${id}-gold)`} stroke="#f9e2b9" strokeWidth="2" />
      <g className="compass-ring compass-stems">
        <RingLabels characters="甲乙丙丁戊己庚辛壬癸" radius={90} className="compass-gold-labels" />
      </g>
      <circle cx="170" cy="170" r="66" fill={`url(#${id}-inner)`} stroke="#d57e63" strokeWidth="1.5" />
      <g className="compass-ring compass-pillars">
        <RingLabels characters="年月日时" radius={47} className="compass-inner-labels" />
      </g>
      <g className="compass-ring compass-taiji">
        <circle cx="170" cy="170" r="29" fill="#fff8e9" />
        <path d="M170 141a29 29 0 0 1 0 58a14.5 14.5 0 0 1 0-29a14.5 14.5 0 0 0 0-29" fill="#bb4c42" />
        <circle cx="170" cy="155.5" r="4.7" fill="#bb4c42" />
        <circle cx="170" cy="184.5" r="4.7" fill="#fff8e9" />
        <circle cx="170" cy="170" r="29" fill="none" stroke="#eac398" strokeWidth="1.5" />
      </g>
    </svg>
    <span className="compass-ground-shadow" />
  </div>;
}

export function ReadingPreparation({ completed, total, hasContent, showContent, onToggleContent }: {
  completed: number;
  total: number;
  hasContent: boolean;
  showContent: boolean;
  onToggleContent: () => void;
}) {
  // The server reports completed sections, not elapsed-time estimates. Never
  // reach 100% while the job is active, even if its final result is in transit.
  const progress = total > 0 ? Math.min(99, Math.max(0, Math.round(completed / total * 100))) : 0;
  return <section className="reading-preparation" aria-labelledby="preparation-title">
    <div className="preparation-heading">
      <p id="preparation-title">正在推演</p>
    </div>
    <ReadingCompass />
    <div className="preparation-progress">
      <div className="preparation-progress-caption"><span>进度</span><output aria-live="polite" aria-atomic="true">{progress}%</output></div>
      <div className="preparation-progress-track" role="progressbar" aria-label="完整解读准备进度" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress}>
        <span className="preparation-progress-fill" style={{ width: `${progress}%` }} />
      </div>
    </div>
    {hasContent && <button type="button" className="text-button preparation-preview-toggle" aria-expanded={showContent} onClick={onToggleContent}>{showContent ? "收起已就绪内容" : "查看已就绪内容"}</button>}
  </section>;
}
