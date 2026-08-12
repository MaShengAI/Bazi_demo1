import type { AnalysisResult, ChartResult } from "../types";

export const chartFixture: ChartResult = {
  request: { name: "测试用户", gender: "male", birth_local_datetime: "1988-07-10T12:30", location_id: 3101 },
  location: { location_id: 3101, province: "上海市", city: "上海市", name: "上海市", longitude: 121.47, latitude: 31.23, timezone_id: "Asia/Shanghai" },
  time_normalization: {
    input_wall_time: "1988-07-10T12:30",
    standard_local_time: "1988-07-10T11:30:00+08:00",
    true_solar_datetime: "1988-07-10T11:30:44+08:00",
    longitude_correction_seconds: 353,
    equation_of_time_seconds: -309,
  },
  pillars: {
    year: makePillar("戊辰", "食神", "戊", "辰", "大林木"),
    month: makePillar("己未", "伤官", "己", "未", "天上火"),
    day: makePillar("丙寅", "日主", "丙", "寅", "炉中火"),
    hour: makePillar("甲午", "偏印", "甲", "午", "沙中金"),
  },
  luck_direction: { direction: "forward", direction_reason: "阳年生男，顺行" },
  luck_start: {
    reference_jie: "立秋",
    start_age: { years: 9, months: 4, days: 19, hours: 4, minutes: 0, seconds: 0 },
    start_datetime: "1997-11-29T15:30:44+08:00",
  },
  major_luck_cycles: [
    {
      ...makePillar("庚申", "偏财", "庚", "申", "石榴木"),
      index: 1,
      start_age: 9,
      end_age: 19,
      start_datetime: "1997-11-29T15:30:44+08:00",
      end_datetime: "2007-11-29T15:30:44+08:00",
      ten_god_of_stem: "偏财",
      annual_years: [{ gregorian_year: 1998, pillar: "戊寅", age: 9, ten_god: "食神", na_yin: "城头土", start_at_li_chun: "1998-02-04T08:57+08:00", end_at_next_li_chun: "1999-02-04T14:57+08:00", shen_sha: [] }],
    },
  ],
  ruleset_versions: { service: "0.3.0", core: "bazi-core-1.0.0" },
};

function makePillar(pillar: string, star: string, stem: string, branch: string, naYin: string) {
  return {
    pillar,
    main_star: star,
    heavenly_stem: stem,
    earthly_branch: branch,
    hidden_stems: [{ stem, role: "本气", secondary_star: star }],
    secondary_stars: [star],
    na_yin: naYin,
    star_fortune: "长生",
    self_seat: "冠带",
    void: ["戌", "亥"],
    shen_sha: [{ code: "taiji", name: "太极贵人", rule_id: "SS-009", evidence: "测试证据" }],
  };
}

export const analysisFixture: AnalysisResult = {
  job_id: "job-12345678",
  chart_id: "chart-12345678",
  status: "partial",
  model_id: "deepseek-chat",
  prompt_version: "v1",
  request_hash: "hash",
  cancel_requested: false,
  completed_sections: 1,
  failed_sections: 1,
  total_sections: 8,
  created_at: "2026-08-04T00:00:00Z",
  started_at: "2026-08-04T00:00:01Z",
  finished_at: null,
  chart: chartFixture,
  disclaimer: "本分析属于传统文化视角的参考性内容。",
  sections: [
    { code: "personality", title: "性格特点与行为模式", status: "completed", content: "这是一段文化分析正文。", char_count: 1500, length_status: "ok", retry_count: 0, error: null, started_at: null, finished_at: null },
    { code: "wealth", title: "财运状况与求财建议", status: "failed", content: null, char_count: 0, length_status: null, retry_count: 2, error: "模型响应超时", started_at: null, finished_at: null },
    ...["children", "education", "career", "relationship", "health", "life_cycles"].map((code, index) => ({ code, title: `等待板块 ${index + 1}`, status: "pending" as const, content: null, char_count: 0, length_status: null, retry_count: 0, error: null, started_at: null, finished_at: null })),
  ],
};
