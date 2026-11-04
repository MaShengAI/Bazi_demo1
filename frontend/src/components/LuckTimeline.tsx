import { useEffect, useRef, useState, type ReactNode } from "react";
import type { AnnualYear, ChartResult, MajorLuckCycle, ShenSha } from "../types";
import { elementForSymbol } from "../data/fiveElements";
import "./LuckTimeline.css";

function formatDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  const parts = new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "numeric", day: "numeric", timeZone: "Asia/Shanghai" }).formatToParts(date);
  const part = (type: "year" | "month" | "day") => parts.find(item => item.type === type)?.value;
  return `${part("year")}年${part("month")}月${part("day")}日`;
}

function yearOf(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("en", { year: "numeric", timeZone: "Asia/Shanghai" }).format(date);
}

function containsNow(start: string, end: string, now: number) {
  return Date.parse(start) <= now && now < Date.parse(end);
}

function currentCycle(cycles: MajorLuckCycle[], now: number) {
  return cycles.find(cycle => containsNow(cycle.start_datetime, cycle.end_datetime, now))
    || (now < Date.parse(cycles[0]?.start_datetime || "") ? cycles[0] : cycles[cycles.length - 1]);
}

function currentAnnual(cycle: MajorLuckCycle | undefined, now: number) {
  return cycle?.annual_years.find(year => containsNow(year.start_at_li_chun, year.end_at_next_li_chun, now)) || cycle?.annual_years[0];
}

const STAR_SHORT: Record<string, string> = { 比肩: "比", 劫财: "劫", 食神: "食", 伤官: "伤", 偏财: "才", 正财: "财", 七杀: "杀", 正官: "官", 偏印: "枭", 正印: "印" };

function TimelinePillar({ pillar, stemStar, branchStar }: { pillar: string; stemStar: string; branchStar?: string }) {
  return <span className="timeline-pillar" aria-hidden="true">
    <span><b className={`element-${elementForSymbol(pillar[0])?.className || "unknown"}`}>{pillar[0]}</b><small title={stemStar}>{STAR_SHORT[stemStar] || stemStar}</small></span>
    <span><b className={`element-${elementForSymbol(pillar[1])?.className || "unknown"}`}>{pillar[1]}</b>{branchStar && <small title={branchStar}>{STAR_SHORT[branchStar] || branchStar}</small>}</span>
  </span>;
}

function TimelineBand({ label, selection, children }: { label: string; selection: string; children: ReactNode }) {
  const strip = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const center = () => {
      const element = strip.current;
      const button = element?.querySelector<HTMLButtonElement>("[aria-pressed='true']");
      if (element && button) element.scrollTo?.({ left: button.offsetLeft - (element.clientWidth - button.offsetWidth) / 2, behavior: "auto" });
    };
    center();
    window.addEventListener("resize", center);
    return () => window.removeEventListener("resize", center);
  }, [selection]);
  const scroll = (direction: number) => strip.current?.scrollBy?.({ left: direction * strip.current.clientWidth * .75, behavior: window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  return <div className="timeline-band">
    <h4>{label}</h4>
    <div className="timeline-band-content"><div className="timeline-strip" role="group" aria-label={`${label}选择`} ref={strip}>{children}</div>
      <div className="timeline-scroll-controls"><button type="button" onClick={() => scroll(-1)} aria-label={`向前滚动${label}`}>‹</button><span>左右滑动查看</span><button type="button" onClick={() => scroll(1)} aria-label={`向后滚动${label}`}>›</button></div>
    </div>
  </div>;
}

function Stars({ items }: { items: ShenSha[] }) {
  return <div className="timeline-stars">{items.length ? items.map((item, index) => <span key={`${item.code}-${index}`} title={`${item.rule_id} · ${item.evidence}`}>{item.name}</span>) : <span>无命中神煞</span>}</div>;
}

function AnnualDetails({ year }: { year: AnnualYear }) {
  return <div className="timeline-annual-details"><h5 className="timeline-detail-title"><span>{year.pillar}流年</span>{" "}<span>· {year.gregorian_year}年</span>{" "}<span>· {year.age}岁</span></h5><p>{year.ten_god} · {year.na_yin}</p><Stars items={year.shen_sha} /></div>;
}

function Timeline({ chart }: { chart: ChartResult }) {
  const cycles = chart.major_luck_cycles;
  const initial = currentCycle(cycles, Date.now());
  const [cycleIndex, setCycleIndex] = useState(initial?.index);
  const [annualYear, setAnnualYear] = useState(currentAnnual(initial, Date.now())?.gregorian_year);
  const [revision, setRevision] = useState(0);
  const cycle = cycles.find(item => item.index === cycleIndex) || initial;
  const year = cycle?.annual_years.find(item => item.gregorian_year === annualYear) || currentAnnual(cycle, Date.now());
  const age = chart.luck_start.start_age;
  const now = Date.now();
  const isCurrentCycle = cycle && containsNow(cycle.start_datetime, cycle.end_datetime, now);
  function selectCycle(next: MajorLuckCycle) {
    setCycleIndex(next.index);
    setAnnualYear(currentAnnual(next, Date.now())?.gregorian_year);
  }
  function today() {
    const next = currentCycle(cycles, Date.now());
    if (next) selectCycle(next);
    setRevision(value => value + 1);
  }
  return <section className="luck-timeline" aria-labelledby="luck-timeline-title">
    <h3 id="luck-timeline-title" className="sr-only">大运与流年</h3>
    <div className="timeline-heading"><div><p><span>起运时间：</span>出生后 {age.years}年{age.months}月{age.days}天起运</p><p><span>交运：</span>{formatDate(chart.luck_start.start_datetime)} · {chart.luck_direction.direction === "forward" ? "顺行" : "逆行"}</p><p className="timeline-heading-meta">参照节气：{chart.luck_start.reference_jie} · 日柱空亡：{chart.pillars.day.void.join("、") || "—"}</p></div><button className="timeline-today" type="button" onClick={today} disabled={!cycles.length} aria-label="回到当前大运流年"><svg className="timeline-calendar-icon" viewBox="0 0 32 36" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M6 7H4.5A2.5 2.5 0 0 0 2 9.5v22A2.5 2.5 0 0 0 4.5 34h23a2.5 2.5 0 0 0 2.5-2.5v-22A2.5 2.5 0 0 0 27.5 7H26M12 7h8M8 2v9M24 2v9" /><text x="16" y="29" textAnchor="middle" fill="currentColor" stroke="none">今</text></svg></button></div>
    {!cycle ? <p className="timeline-empty">暂无大运数据</p> : <>
      <TimelineBand label="大运" selection={`${cycle.index}-${revision}`}>
        {cycles.map(item => <button type="button" className="timeline-column" key={item.index} aria-pressed={cycle.index === item.index} aria-label={`${yearOf(item.start_datetime)}年起 ${item.start_age}至${item.end_age}岁 大运${item.pillar}`} onClick={() => selectCycle(item)}>
          <span className="timeline-year">{yearOf(item.start_datetime)}</span><span className="timeline-age">{item.start_age}岁</span><TimelinePillar pillar={item.pillar} stemStar={item.ten_god_of_stem} branchStar={item.secondary_stars[0]} />
        </button>)}
      </TimelineBand>
      {cycle.annual_years.length ? <TimelineBand label="流年" selection={`${cycle.index}-${year?.gregorian_year}-${revision}`}>
        {cycle.annual_years.map(item => <button type="button" className="timeline-column" key={item.gregorian_year} aria-pressed={year?.gregorian_year === item.gregorian_year} aria-label={`${item.gregorian_year}年 ${item.age}岁 流年${item.pillar}`} onClick={() => setAnnualYear(item.gregorian_year)}>
          <span className="timeline-year">{item.gregorian_year}{isCurrentCycle && containsNow(item.start_at_li_chun, item.end_at_next_li_chun, now) && <i className="timeline-current-dot" title="当前流年" />}</span><span className="timeline-age">{item.age}岁</span><TimelinePillar pillar={item.pillar} stemStar={item.ten_god} branchStar={item.secondary_stars?.[0]} />
        </button>)}
      </TimelineBand> : <p className="timeline-empty">本运暂无流年数据</p>}
      <div className="timeline-facts"><div className="timeline-facts-content"><h5 className="timeline-detail-title"><span>{cycle.pillar}大运</span>{" "}<span>· {yearOf(cycle.start_datetime)}—{yearOf(cycle.end_datetime)}年</span>{" "}<span>· {cycle.start_age}—{cycle.end_age}岁</span></h5><p>{cycle.ten_god_of_stem} · {cycle.na_yin}</p><Stars items={cycle.shen_sha} />{year && <AnnualDetails year={year} />}</div></div>
    </>}
  </section>;
}

export function LuckTimeline({ chart }: { chart: ChartResult }) {
  return <Timeline key={`${chart.request.birth_local_datetime}-${chart.request.location_id}-${chart.request.gender}`} chart={chart} />;
}
