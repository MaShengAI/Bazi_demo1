import type { ReactNode } from "react";
import type { ChartResult, Pillar } from "../types";
import { LuckTimeline } from "./LuckTimeline";
import { solarToLunar, lunarMonthLabel, lunarDayLabel } from "../calendar";
import { elementForSymbol } from "../data/fiveElements";
import { zodiacForLunarYear } from "../data/zodiac";

const PILLAR_LABELS = { year: "年柱", month: "月柱", day: "日柱", hour: "时柱" } as const;

function formatBirthTimes(chart: ChartResult) {
  const [date, time] = chart.request.birth_local_datetime.split("T");
  const [year, month, day] = date.split("-").map(Number);
  const lunar = solarToLunar({ year, month, day });
  // Show the entered local clock time, independently of chart time correction.
  const hour = Number(time.split(":")[0]);
  const shichen = "子丑寅卯辰巳午未申酉戌亥"[Math.floor((hour + 1) / 2) % 12];
  return {
    lunar: `农历：${lunar.year}年${lunarMonthLabel(lunar.month)}${lunarDayLabel(lunar.day)} ${shichen}时`,
    solar: `公历：${year}年${month}月${day}日 ${time}`,
    zodiac: zodiacForLunarYear(lunar.year),
  };
}

const PILLAR_KEYS = ["year", "month", "day", "hour"] as const;
function PillarSymbol({ value, large = false }: { value: string; large?: boolean }) {
  const element = elementForSymbol(value);
  return <span className={`matrix-symbol ${large ? "matrix-symbol-large" : "matrix-hidden-stem"} element-${element?.className || "unknown"}`} aria-label={`${value}${element?.label || ""}`}>
    {value}{!large && element?.label}
  </span>;
}

function PillarTable({ pillars }: { pillars: ChartResult["pillars"] }) {
  const rows: Array<{ label: string; className?: string; content: (pillar: Pillar) => ReactNode }> = [
    { label: "主星", content: pillar => pillar.main_star },
    { label: "天干", className: "matrix-glyph-row", content: pillar => <PillarSymbol value={pillar.heavenly_stem} large /> },
    { label: "地支", className: "matrix-glyph-row", content: pillar => <PillarSymbol value={pillar.earthly_branch} large /> },
    { label: "藏干", content: pillar => <div className="matrix-stack">{pillar.hidden_stems.length ? pillar.hidden_stems.map((item, index) => <span key={`${item.stem}-${index}`} title={item.role}><PillarSymbol value={item.stem} /></span>) : "—"}</div> },
    { label: "副星", content: pillar => <div className="matrix-stack">{pillar.secondary_stars.length ? pillar.secondary_stars.map((star, index) => <span key={`${star}-${index}`}>{star}</span>) : "—"}</div> },
    { label: "星运", content: pillar => pillar.star_fortune },
    { label: "自坐", content: pillar => pillar.self_seat },
    { label: "空亡", content: pillar => pillar.void.join("、") || "—" },
    { label: "纳音", content: pillar => pillar.na_yin },
    { label: "神煞", className: "matrix-shensha-row", content: pillar => <div className="matrix-stack">{pillar.shen_sha.length ? pillar.shen_sha.map((item, index) => <span key={`${item.code}-${index}`} title={`${item.rule_id} · ${item.evidence}`}>{item.name}</span>) : "—"}</div> },
  ];
  return <div className="pillar-matrix-frame">
    <table className="pillar-matrix">
      <caption className="sr-only">四柱命盘</caption>
      <colgroup><col className="matrix-label-col" /><col span={4} /></colgroup>
      <thead><tr><th scope="col">日期</th>{PILLAR_KEYS.map(key => <th scope="col" key={key} aria-label={`${PILLAR_LABELS[key]}${pillars[key].pillar}`}>{PILLAR_LABELS[key]}</th>)}</tr></thead>
      <tbody>{rows.map(row => <tr key={row.label} className={row.className}><th scope="row">{row.label}</th>{PILLAR_KEYS.map(key => <td key={key}>{row.content(pillars[key])}</td>)}</tr>)}</tbody>
    </table>
  </div>;
}

export function ChartResultView({ chart }: { chart: ChartResult }) {
  const birthTimes = formatBirthTimes(chart);
  return (
    <section id="chart-facts" className="results-section" aria-labelledby="chart-title">
      <h2 className="report-section-heading">基础信息</h2>
      <div className="results-title-row">
        <div className="chart-basic-info">
          <img className="chart-zodiac-avatar" src={birthTimes.zodiac.image} alt={`生肖属${birthTimes.zodiac.name}`} width={76} height={76} decoding="async" />
          <div className="chart-basic-copy">
            <h2 id="chart-title">{chart.request.name || "未署名"}</h2>
            <p className="chart-birth-times"><span>{chart.location.province} · {chart.location.city}</span><span>{birthTimes.lunar}</span><span>{birthTimes.solar}</span></p>
          </div>
        </div>
        <span className="ruleset-badge">规则版本 {chart.ruleset_versions.service}</span>
      </div>

      <h2 className="report-section-heading">八字信息</h2>
      <PillarTable pillars={chart.pillars} />

      <h2 className="report-section-heading">大运流年</h2>
      <LuckTimeline chart={chart} />

    </section>
  );
}
