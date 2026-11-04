import table from "./data/lunar-months.json";

export interface CalendarDate { year: number; month: number; day: number }
export interface LunarMonth { month: number; days: number; start: number }
const rows = table.years as Record<string, number[]>;
const DAY = 86400000;
const minimum = Date.UTC(1901, 0, 1) / DAY;
const maximum = Date.UTC(2100, 11, 31) / DAY;
export const LUNAR_YEARS = Object.keys(rows).map(Number);

export function lunarMonths(year: number): LunarMonth[] {
  const row = rows[year];
  if (!row) throw new Error("农历年份超出支持范围");
  const result: LunarMonth[] = [];
  let start = row[0];
  for (let i = 1; i < row.length; i += 2) {
    result.push({ month: row[i], days: row[i + 1], start });
    start += row[i + 1];
  }
  return result;
}

export function selectableLunarMonths(year: number) {
  return lunarMonths(year).filter(item => item.start <= maximum && item.start + item.days - 1 >= minimum);
}

export function selectableLunarDays(year: number, month: number): number[] {
  const item = lunarMonths(year).find(item => item.month === month);
  if (!item) return [];
  return Array.from({ length: item.days }, (_, index) => index + 1)
    .filter(day => item.start + day - 1 >= minimum && item.start + day - 1 <= maximum);
}

export function solarToLunar(date: CalendarDate): CalendarDate {
  const time = Date.UTC(date.year, date.month - 1, date.day) / DAY;
  const check = new Date(time * DAY);
  if (!Number.isInteger(time) || time < minimum || time > maximum || check.getUTCFullYear() !== date.year
    || check.getUTCMonth() + 1 !== date.month || check.getUTCDate() !== date.day) throw new Error("公历日期无效");
  for (const year of [date.year, date.year - 1]) {
    const item = lunarMonths(year).find(item => time >= item.start && time < item.start + item.days);
    if (item) return { year, month: item.month, day: time - item.start + 1 };
  }
  throw new Error("无法换算农历日期");
}

export function lunarToSolar(date: CalendarDate): CalendarDate {
  const item = lunarMonths(date.year).find(item => item.month === date.month);
  if (!item || !Number.isInteger(date.day) || date.day < 1 || date.day > item.days) throw new Error("农历日期无效");
  const day = item.start + date.day - 1;
  if (day < minimum || day > maximum) throw new Error("支持的公历范围为1901—2100年");
  const value = new Date(day * DAY);
  return { year: value.getUTCFullYear(), month: value.getUTCMonth() + 1, day: value.getUTCDate() };
}

const MONTH_NAMES = ["正月", "二月", "三月", "四月", "五月", "六月", "七月", "八月", "九月", "十月", "十一月", "十二月"];
export function lunarMonthLabel(month: number) { return `${month < 0 ? "闰" : ""}${MONTH_NAMES[Math.abs(month) - 1]}`; }
export function lunarDayLabel(day: number) {
  if (day === 10) return "初十";
  if (day === 20) return "二十";
  if (day === 30) return "三十";
  return `${["初", "十", "廿"][Math.floor(day / 10)]}${["", "一", "二", "三", "四", "五", "六", "七", "八", "九"][day % 10]}`;
}
