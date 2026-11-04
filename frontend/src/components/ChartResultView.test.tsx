import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import { chartFixture } from "../test/fixtures";
import { ChartResultView } from "./ChartResultView";

test.each([
  [1984, "鼠", "rat"], [1985, "牛", "ox"], [1986, "虎", "tiger"],
  [1987, "兔", "rabbit"], [1988, "龙", "dragon"], [1989, "蛇", "snake"],
  [1990, "马", "horse"], [1991, "羊", "goat"], [1992, "猴", "monkey"],
  [1993, "鸡", "rooster"], [1994, "狗", "dog"], [1995, "猪", "pig"],
])("农历 %s 年使用生肖%s头像", (year, animal, file) => {
  render(<ChartResultView chart={{ ...chartFixture, request: { ...chartFixture.request, birth_local_datetime: `${year}-07-01T12:00` } }} />);
  expect(screen.getByRole("img", { name: `生肖属${animal}` })).toHaveAttribute("src", expect.stringContaining(`/zodiac/${file}.png`));
});

test("生肖复用农历年份，春节前后切换且不受日期输入方式影响", () => {
  const chart = { ...chartFixture, request: { ...chartFixture.request, birth_local_datetime: "2024-02-09T23:30", birth_calendar: "solar" as const } };
  const { rerender } = render(<ChartResultView chart={chart} />);
  expect(screen.getByRole("img", { name: "生肖属兔" })).toBeVisible();
  rerender(<ChartResultView chart={{ ...chart, request: { ...chart.request, birth_local_datetime: "2024-02-10T00:00", birth_calendar: "lunar" } }} />);
  expect(screen.getByRole("img", { name: "生肖属龙" })).toBeVisible();
});

test("生辰同时显示农历时辰和公历时分，不展示真太阳时", () => {
  const chart = { ...chartFixture, request: { ...chartFixture.request, birth_local_datetime: "2023-03-22T08:30", birth_calendar: "lunar" as const }, time_normalization: { ...chartFixture.time_normalization, true_solar_datetime: "2023-03-22T08:35:00+08:00" } };
  const { rerender } = render(<ChartResultView chart={chart} />);
  expect(screen.getByText("农历：2023年闰二月初一 辰时")).toBeVisible();
  expect(screen.getByText("公历：2023年3月22日 08:30")).toBeVisible();
  expect(screen.queryByText(/真太阳时/)).not.toBeInTheDocument();
  rerender(<ChartResultView chart={{ ...chart, request: { ...chart.request, birth_calendar: "solar" } }} />);
  expect(screen.getByText("农历：2023年闰二月初一 辰时")).toBeVisible();
  expect(screen.getByText("公历：2023年3月22日 08:30")).toBeVisible();
});

test.each([
  ["00:00", "子"], ["00:59", "子"], ["01:00", "丑"], ["02:59", "丑"],
  ["03:00", "寅"], ["05:00", "卯"], ["07:00", "辰"], ["09:00", "巳"],
  ["11:00", "午"], ["13:00", "未"], ["15:00", "申"], ["17:00", "酉"],
  ["19:00", "戌"], ["21:00", "亥"], ["22:59", "亥"], ["23:00", "子"], ["23:59", "子"],
])("当地时间 %s 显示为 %s时", (time, shichen) => {
  render(<ChartResultView chart={{ ...chartFixture, request: { ...chartFixture.request, birth_local_datetime: `2023-03-22T${time}` } }} />);
  expect(screen.getByText(`农历：2023年闰二月初一 ${shichen}时`)).toBeVisible();
  expect(screen.getByText(`公历：2023年3月22日 ${time}`)).toBeVisible();
});

test("展示四柱、藏干、纳音、神煞、起运和流年", async () => {
  render(<ChartResultView chart={chartFixture} />);
  expect(screen.getByRole("heading", { name: "测试用户" })).toBeInTheDocument();
  expect(screen.getByLabelText("年柱戊辰")).toBeInTheDocument();
  expect(screen.getByRole("cell", { name: "大林木" })).toBeInTheDocument();
  const table = screen.getByRole("table", { name: "四柱命盘" });
  expect(within(table).getAllByRole("columnheader").map(item => item.textContent)).toEqual(["日期", "年柱", "月柱", "日柱", "时柱"]);
  expect(within(table).getAllByRole("rowheader").map(item => item.textContent)).toEqual(["主星", "天干", "地支", "藏干", "副星", "星运", "自坐", "空亡", "纳音", "神煞"]);
  expect(screen.getAllByText("太极贵人").length).toBeGreaterThan(0);
  expect(screen.getByText(/出生后 9年4月19天起运/)).toHaveTextContent("起运时间：出生后 9年4月19天起运");
  await userEvent.click(screen.getByRole("button", { name: /大运庚申/ }));
  expect(screen.getByText("1998")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /流年戊寅/ })).toBeInTheDocument();
});


test("表格各列保留多项藏干、副星与全部神煞，不互相错位或截断", () => {
  const year = {
    ...chartFixture.pillars.year,
    hidden_stems: [
      { stem: "戊", role: "本气", secondary_star: "食神" },
      { stem: "乙", role: "中气", secondary_star: "正印" },
      { stem: "癸", role: "余气", secondary_star: "正官" },
    ],
    secondary_stars: ["食神", "正印", "正官"],
    shen_sha: Array.from({ length: 9 }, (_, index) => ({ code: `star-${index}`, name: `神煞${index}`, rule_id: `rule-${index}`, evidence: "测试" })),
  };
  render(<ChartResultView chart={{ ...chartFixture, pillars: { ...chartFixture.pillars, year } }} />);
  const table = screen.getByRole("table", { name: "四柱命盘" });
  const cells = (label: string) => within(within(table).getByRole("rowheader", { name: label }).closest("tr")!).getAllByRole("cell");
  expect(cells("藏干")[0]).toHaveTextContent("戊土乙木癸水");
  expect(cells("副星")[0]).toHaveTextContent("食神正印正官");
  expect(cells("副星")[1]).toHaveTextContent("伤官");
  expect(within(cells("神煞")[0]).getByText("神煞8")).toBeInTheDocument();
  expect(within(cells("神煞")[1]).getByText("太极贵人")).toBeInTheDocument();
});


test("大运与流年选择联动，详情合并为名称、年份、年龄且不展示立春区间", async () => {
  vi.spyOn(Date, "now").mockReturnValue(Date.parse("2026-10-29T08:00:00+08:00"));
  const old = chartFixture.major_luck_cycles[0];
  const current = {
    ...old, index: 2, pillar: "辛酉", ten_god_of_stem: "正财",
    start_age: 31, end_age: 41, start_datetime: "2020-07-14T18:43:00+08:00", end_datetime: "2030-07-14T17:43:00+08:00",
    annual_years: [{ ...old.annual_years[0], gregorian_year: 2026, age: 37, pillar: "丙午", ten_god: "比肩", start_at_li_chun: "2026-02-04T08:00:00+08:00", end_at_next_li_chun: "2027-02-04T08:00:00+08:00" }],
  };
  render(<ChartResultView chart={{ ...chartFixture, major_luck_cycles: [old, current] }} />);
  const user = userEvent.setup();
  const major = screen.getByRole("group", { name: "大运选择" });
  expect(within(major).getByRole("button", { name: /大运辛酉/ })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByRole("button", { name: /2026年.*流年丙午/ })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByRole("heading", { name: "辛酉大运 · 2020—2030年 · 31—41岁" })).toBeVisible();
  expect(screen.getAllByText("辛酉大运", { exact: true })).toHaveLength(1);
  expect(screen.queryByText(/立春流年：/)).not.toBeInTheDocument();
  await user.click(within(major).getByRole("button", { name: /大运庚申/ }));
  expect(screen.getByRole("button", { name: /1998年.*流年戊寅/ })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /2026年.*流年丙午/ })).not.toBeInTheDocument();
  expect(screen.queryByText("查看所选大运与流年详情")).not.toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "戊寅流年 · 1998年 · 9岁" })).toBeVisible();
  await user.click(screen.getByRole("button", { name: "回到当前大运流年" }));
  expect(within(major).getByRole("button", { name: /大运辛酉/ })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByRole("button", { name: /2026年.*流年丙午/ })).toHaveAttribute("aria-pressed", "true");
});

test("流年地支右侧显示后端返回的本气十神，旧数据不猜测补值", () => {
  const cycle = chartFixture.major_luck_cycles[0];
  const chart = { ...chartFixture, major_luck_cycles: [{ ...cycle, annual_years: [{ ...cycle.annual_years[0], secondary_stars: ["偏印", "比肩", "食神"] }] }] };
  const { rerender } = render(<ChartResultView chart={chart} />);
  const annual = screen.getByRole("group", { name: "流年选择" });
  expect(annual.querySelector('.timeline-pillar > span:last-child')).toHaveTextContent("寅枭");
  expect(annual.querySelector('.timeline-pillar > span:last-child small')).toHaveAttribute("title", "偏印");
  rerender(<ChartResultView chart={chartFixture} />);
  expect(annual.querySelector('.timeline-pillar > span:last-child small')).toBeNull();
});

test("缺少大运或流年数据时显示空状态，不构造小运和司令数据", () => {
  const { rerender } = render(<ChartResultView chart={{ ...chartFixture, major_luck_cycles: [] }} />);
  expect(screen.getByText("暂无大运数据")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "回到当前大运流年" })).toBeDisabled();
  rerender(<ChartResultView chart={{ ...chartFixture, major_luck_cycles: [{ ...chartFixture.major_luck_cycles[0], annual_years: [] }] }} />);
  expect(screen.getByText("本运暂无流年数据")).toBeInTheDocument();
  expect(screen.queryByRole("group", { name: "流年选择" })).not.toBeInTheDocument();
});
