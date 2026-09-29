export type JobStatus =
  | "pending"
  | "running"
  | "partial"
  | "completed"
  | "failed"
  | "cancelled";

export type SectionStatus = Exclude<JobStatus, "partial">;

export interface ChartRequest {
  name?: string;
  gender: "male" | "female";
  birth_local_datetime: string;
  location_id: number;
}

export interface Province {
  code: string;
  name: string;
}

export interface City {
  code: number;
  name: string;
  longitude: number;
  latitude: number;
}

export interface HiddenStem {
  stem: string;
  role: string;
  secondary_star: string;
}

export interface ShenSha {
  code: string;
  name: string;
  rule_id: string;
  evidence: string;
}

export interface Pillar {
  pillar: string;
  main_star: string;
  heavenly_stem: string;
  earthly_branch: string;
  hidden_stems: HiddenStem[];
  secondary_stars: string[];
  na_yin: string;
  star_fortune: string;
  self_seat: string;
  void: string[];
  shen_sha: ShenSha[];
}

export interface AnnualYear {
  gregorian_year: number;
  pillar: string;
  age: number;
  ten_god: string;
  na_yin: string;
  start_at_li_chun: string;
  end_at_next_li_chun: string;
  shen_sha: ShenSha[];
}

export interface MajorLuckCycle extends Pillar {
  index: number;
  start_age: number;
  end_age: number;
  start_datetime: string;
  end_datetime: string;
  ten_god_of_stem: string;
  annual_years: AnnualYear[];
}

export interface ChartResult {
  request: ChartRequest;
  location: {
    location_id: number;
    province: string;
    city: string;
    name: string;
    longitude: number;
    latitude: number;
    timezone_id: string;
  };
  time_normalization: {
    input_wall_time: string;
    standard_local_time: string;
    true_solar_datetime: string;
    longitude_correction_seconds: number;
    equation_of_time_seconds: number;
  };
  pillars: Record<"year" | "month" | "day" | "hour", Pillar>;
  luck_direction: {
    direction: "forward" | "backward";
    direction_reason: string;
  };
  luck_start: {
    reference_jie: string;
    start_age: {
      years: number;
      months: number;
      days: number;
      hours: number;
      minutes: number;
      seconds: number;
    };
    start_datetime: string;
  };
  major_luck_cycles: MajorLuckCycle[];
  ruleset_versions: Record<string, string>;
}

export interface AnalysisAccepted {
  job_id: string;
  chart_id: string;
  status: JobStatus;
  deduplicated: boolean;
}

export interface AnalysisStatus {
  job_id: string;
  chart_id: string;
  status: JobStatus;
  model_id: string;
  prompt_version: string;
  request_hash: string;
  cancel_requested: boolean;
  completed_sections: number;
  failed_sections: number;
  total_sections: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface AnalysisSection {
  code: string;
  title: string;
  status: SectionStatus;
  content: string | null;
  char_count: number;
  length_status: "ok" | "short" | "long" | null;
  retry_count: number;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface AnalysisResult extends AnalysisStatus {
  chart: ChartResult;
  sections: AnalysisSection[];
  disclaimer: string;
}

export interface ApiErrorBody {
  error?: {
    code?: string;
    message?: string;
    details?: Record<string, unknown>;
  };
  detail?: unknown;
}

export interface AuthUser {
  id: string;
  display_name: string;
  avatar_url: string | null;
}

export interface AuthState {
  enabled: boolean;
  authenticated: boolean;
  require_for_analysis: boolean;
  analysis_limit_per_24h: number;
  user: AuthUser | null;
}

export interface AnalysisHistoryItem {
  job_id: string;
  chart_id: string;
  status: JobStatus;
  name: string | null;
  birth_local_datetime: string | null;
  completed_sections: number;
  total_sections: number;
  created_at: string;
}
