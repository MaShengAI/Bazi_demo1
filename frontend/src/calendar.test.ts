import { lunarToSolar, solarToLunar, lunarMonthLabel, lunarDayLabel, selectableLunarMonths, selectableLunarDays } from "./calendar";

test("春节、正月初一和闰二月均正确换算", () => {
  expect(lunarToSolar({ year: 2024, month: 1, day: 1 })).toEqual({ year: 2024, month: 2, day: 10 });
  expect(lunarToSolar({ year: 2025, month: 1, day: 1 })).toEqual({ year: 2025, month: 1, day: 29 });
  expect(lunarToSolar({ year: 2023, month: -2, day: 1 })).toEqual({ year: 2023, month: 3, day: 22 });
  expect(solarToLunar({ year: 2023, month: 3, day: 22 })).toEqual({ year: 2023, month: -2, day: 1 });
  expect(lunarMonthLabel(-2)).toBe("闰二月");
  expect(lunarMonthLabel(11)).toBe("十一月");
  expect(lunarMonthLabel(12)).toBe("十二月");
  expect(lunarDayLabel(21)).toBe("廿一");
  expect(lunarDayLabel(30)).toBe("三十");
});

test("支持区间每一天可往返换算，最早/最晚农历月份不越界", () => {
  const end = Date.UTC(2100, 11, 31);
  for (let t = Date.UTC(1901, 0, 1); t <= end; t += 86400000) {
    const d = new Date(t);
    const solar = { year: d.getUTCFullYear(), month: d.getUTCMonth() + 1, day: d.getUTCDate() };
    const lunar = solarToLunar(solar);
    const roundTrip = lunarToSolar(lunar);
    if (JSON.stringify(roundTrip) !== JSON.stringify(solar)) throw new Error(`Calendar round-trip failed: ${JSON.stringify(solar)}`);
  }
  expect(solarToLunar({ year: 1901, month: 1, day: 1 }).year).toBe(1900);
  for (const year of [1900, 2100]) for (const month of selectableLunarMonths(year)) {
    for (const day of selectableLunarDays(year, month.month)) expect(lunarToSolar({ year, month: month.month, day }).year).toBeGreaterThanOrEqual(1901);
  }
});

test("不存在的闰月、农历越日和无效公历不会被默默改成别的日期", () => {
  expect(() => lunarToSolar({ year: 2024, month: -2, day: 1 })).toThrow();
  expect(() => lunarToSolar({ year: 2023, month: 1, day: 30 })).toThrow();
  expect(() => solarToLunar({ year: 2023, month: 2, day: 29 })).toThrow();
  expect(() => solarToLunar({ year: 2101, month: 1, day: 1 })).toThrow();
});
