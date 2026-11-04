import { groupReportsByName, reportNameKey } from "./reportNameGroups";
import type { SavedReportItem } from "./types";

const report = (name: string | null, chart_id = String(name), created_at = "2026-11-04T00:00:00Z"): SavedReportItem => ({
  name, chart_id, job_id: null, status: "locked", birth_local_datetime: null,
  completed_sections: 0, total_sections: 8, created_at,
});

test("按中文拼音、常见多音姓氏和英文字母生成索引，空名及符号归入#", () => {
  for (const [name, letter] of [["案例5", "A"], ["财气通门户", "C"], ["何林", "H"], ["李贺港", "L"], ["齐洋晨", "Q"], ["单小明", "S"], ["曾小明", "Z"], ["区小明", "O"], ["alice", "A"], ["Émile", "E"], ["Ａlan", "A"], [null, "#"], [" ", "#"], ["123", "#"], ["🙂小王", "#"]] as const) {
    expect(reportNameKey(name).letter, String(name)).toBe(letter);
  }
});

test("字母组按A到Z且#在最后，同组按姓名自然顺序，同名按最新时间，不修改原列表", () => {
  const rows = [report(null), report("张三"), report("案例10"), report("李明", "old", "2026-11-01T00:00:00Z"), report("案例2"), report("李明", "new")];
  const original = rows.slice();
  const groups = groupReportsByName(rows);
  expect(groups.map(g => g.letter)).toEqual(["A", "L", "Z", "#"]);
  expect(groups[0].items.map(r => r.name)).toEqual(["案例2", "案例10"]);
  expect(groups[1].items.map(r => r.chart_id)).toEqual(["new", "old"]);
  expect(rows).toEqual(original);
});
