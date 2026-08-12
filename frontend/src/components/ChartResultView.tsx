import type { ChartResult, MajorLuckCycle, Pillar } from "../types";

const PILLAR_LABELS = { year: "年柱", month: "月柱", day: "日柱", hour: "时柱" } as const;

function formatDateTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value.replace("T", " ");
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "Asia/Shanghai",
  }).format(date);
}

function PillarCard({ label, data, isDay }: { label: string; data: Pillar; isDay?: boolean }) {
  return (
    <article className={`pillar-card${isDay ? " pillar-day" : ""}`}>
      <div className="pillar-label">{label}</div>
      <div className="pillar-main-star">{data.main_star}</div>
      <div className="pillar-glyphs" aria-label={`${label}${data.pillar}`}>
        <span>{data.heavenly_stem}</span>
        <span>{data.earthly_branch}</span>
      </div>
      <div className="pillar-nayin">纳音 · {data.na_yin}</div>
      <dl className="pillar-meta">
        <div><dt>十二长生</dt><dd>{data.star_fortune}</dd></div>
        <div><dt>自坐</dt><dd>{data.self_seat}</dd></div>
        <div><dt>旬空</dt><dd>{data.void.join("、") || "—"}</dd></div>
      </dl>
      <div className="hidden-stems">
        <span className="mini-label">藏干</span>
        {data.hidden_stems.map((item) => (
          <span className="stem-chip" key={`${item.stem}-${item.role}`}>
            <b>{item.stem}</b> {item.secondary_star}<small>{item.role}</small>
          </span>
        ))}
      </div>
      <div className="shensha-list">
        <span className="mini-label">神煞</span>
        {data.shen_sha.length ? data.shen_sha.map((item) => (
          <span className="shensha-chip" title={`${item.rule_id} · ${item.evidence}`} key={`${item.rule_id}-${item.code}`}>
            {item.name}
          </span>
        )) : <span className="muted">无命中</span>}
      </div>
    </article>
  );
}

function LuckCycle({ cycle }: { cycle: MajorLuckCycle }) {
  return (
    <details className="luck-cycle">
      <summary>
        <div className="luck-index">{String(cycle.index).padStart(2, "0")}</div>
        <div className="luck-pillar">{cycle.pillar}</div>
        <div className="luck-summary-meta">
          <b>{cycle.start_age}—{cycle.end_age} 岁</b>
          <span>{cycle.ten_god_of_stem} · {cycle.na_yin}</span>
        </div>
        <span className="details-hint">查看流年</span>
      </summary>
      <div className="cycle-details">
        <p className="cycle-date">{formatDateTime(cycle.start_datetime)} — {formatDateTime(cycle.end_datetime)}</p>
        <div className="cycle-shensha">
          {cycle.shen_sha.map((item) => <span className="shensha-chip" key={`${item.rule_id}-${item.code}`}>{item.name}</span>)}
        </div>
        <div className="annual-grid">
          {cycle.annual_years.map((year) => (
            <article className="annual-card" key={`${cycle.index}-${year.gregorian_year}`}>
              <div><b>{year.gregorian_year}</b><span>{year.age} 岁</span></div>
              <strong>{year.pillar}</strong>
              <p>{year.ten_god} · {year.na_yin}</p>
              <div>{year.shen_sha.slice(0, 4).map((item) => <span key={`${item.rule_id}-${item.code}`}>{item.name}</span>)}</div>
            </article>
          ))}
        </div>
      </div>
    </details>
  );
}

export function ChartResultView({ chart }: { chart: ChartResult }) {
  const age = chart.luck_start.start_age;
  return (
    <section className="results-section" aria-labelledby="chart-title">
      <div className="results-title-row">
        <div>
          <div className="section-kicker">确定性排盘结果</div>
          <h2 id="chart-title">{chart.request.name || "未署名"}的四柱命盘</h2>
          <p>{chart.location.province} · {chart.location.city} ｜ 真太阳时 {formatDateTime(chart.time_normalization.true_solar_datetime)}</p>
        </div>
        <span className="ruleset-badge">规则版本 {chart.ruleset_versions.service}</span>
      </div>

      <div className="pillar-grid">
        {(Object.keys(PILLAR_LABELS) as Array<keyof typeof PILLAR_LABELS>).map((key) => (
          <PillarCard key={key} label={PILLAR_LABELS[key]} data={chart.pillars[key]} isDay={key === "day"} />
        ))}
      </div>

      <div className="luck-overview">
        <div className="seal" aria-hidden="true">运</div>
        <div>
          <span>起运</span>
          <strong>{age.years} 年 {age.months} 月 {age.days} 日</strong>
        </div>
        <div>
          <span>行运方向</span>
          <strong>{chart.luck_direction.direction === "forward" ? "顺行" : "逆行"}</strong>
          <small>{chart.luck_direction.direction_reason}</small>
        </div>
        <div>
          <span>参照节气</span>
          <strong>{chart.luck_start.reference_jie}</strong>
        </div>
        <div>
          <span>起运时刻</span>
          <strong>{formatDateTime(chart.luck_start.start_datetime)}</strong>
        </div>
      </div>

      <div className="subsection-heading">
        <div>
          <div className="section-kicker">十年一步</div>
          <h3>大运与流年</h3>
        </div>
        <p>展开任一大运，可查看对应流年、十神与神煞。</p>
      </div>
      <div className="luck-list">
        {chart.major_luck_cycles.map((cycle) => <LuckCycle key={cycle.index} cycle={cycle} />)}
      </div>
    </section>
  );
}
