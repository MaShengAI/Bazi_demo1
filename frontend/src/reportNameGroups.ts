import { pinyin } from "pinyin-pro";
import type { SavedReportItem } from "./types";

export interface ReportNameGroup { letter: string; items: SavedReportItem[] }
const alphabetical = new Intl.Collator("en", { numeric: true, sensitivity: "base" });

export function reportNameKey(name: string | null): { letter: string; key: string } {
  const normalized = (name || "").normalize("NFKC").trim();
  const first = Array.from(normalized)[0] || "";
  const key = /^\p{Script=Han}/u.test(first)
    ? pinyin(normalized, { toneType: "none", surname: "head", type: "array", nonZh: "consecutive", v: true }).join("")
    : normalized.normalize("NFKD").replace(/\p{Mark}/gu, "");
  const initial = Array.from(key)[0]?.toUpperCase() || "";
  return { letter: /^[A-Z]$/.test(initial) ? initial : "#", key };
}

export function groupReportsByName(items: SavedReportItem[]): ReportNameGroup[] {
  const sorted = items.map(item => ({ item, ...reportNameKey(item.name) })).sort((a, b) => {
    const group = (a.letter === "#" ? 1 : 0) - (b.letter === "#" ? 1 : 0)
      || alphabetical.compare(a.letter, b.letter);
    return group || alphabetical.compare(a.key, b.key)
      || b.item.created_at.localeCompare(a.item.created_at)
      || a.item.chart_id.localeCompare(b.item.chart_id);
  });
  const groups: ReportNameGroup[] = [];
  for (const entry of sorted) {
    let group = groups[groups.length - 1];
    if (!group || group.letter !== entry.letter) {
      group = { letter: entry.letter, items: [] };
      groups.push(group);
    }
    group.items.push(entry.item);
  }
  return groups;
}
