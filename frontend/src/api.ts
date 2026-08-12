import type {
  AnalysisAccepted,
  AnalysisResult,
  AnalysisStatus,
  ApiErrorBody,
  ChartRequest,
  ChartResult,
  City,
  Province,
} from "./types";
import { APP_VERSION, NETWORK_TIMEOUTS } from "./config";

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly code?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit, timeoutMs: number = NETWORK_TIMEOUTS.read): Promise<T> {
  if (typeof navigator !== "undefined" && !navigator.onLine) {
    throw new ApiError("当前网络已断开，联网后会自动继续。", 0, "offline");
  }
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      signal: controller.signal,
      headers: {
        ...(init?.body ? { "Content-Type": "application/json" } : {}),
        "X-Bazi-Client-Version": APP_VERSION,
        ...init?.headers,
      },
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiError("网络响应较慢，本次请求已超时，将自动重试。", 0, "timeout");
    }
    throw new ApiError("无法连接排盘服务，请确认后端已启动。", 0, "network_error");
  } finally {
    window.clearTimeout(timer);
  }

  if (!response.ok) {
    let payload: ApiErrorBody = {};
    try {
      payload = (await response.json()) as ApiErrorBody;
    } catch {
      // Non-JSON upstream errors still get a useful Chinese fallback.
    }
    throw new ApiError(
      friendlyError(payload.error?.code, payload.error?.message, response.status),
      response.status,
      payload.error?.code,
    );
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

function friendlyError(code: string | undefined, message: string | undefined, status: number) {
  const known: Record<string, string> = {
    database_not_configured: "AI 分析服务尚未配置数据库，普通排盘仍可正常使用。",
    database_unavailable: "AI 分析存储暂时不可用，普通排盘仍可正常使用。",
    location_not_found: "所选城市不存在，请重新选择出生地点。",
    invalid_birth_datetime: "出生时间格式无效，请检查日期和时间。",
    unsupported_date_range: "目前仅支持 1901—2100 年的出生时间。",
    ambiguous_local_time: "该时间处于历史夏令时重复时段，请换一个明确的分钟。",
    nonexistent_local_time: "该时间处于历史夏令时跳过时段，请换一个有效的分钟。",
    analysis_not_found: "未找到该分析任务，它可能已被删除。",
    analysis_not_retryable: "该板块当前不能重试。",
    section_not_retryable: "该板块当前不能重试。",
  };
  if (code && known[code]) return known[code];
  if (status === 429) return "请求较多，请稍后再试。";
  if ([502, 503, 504].includes(status)) return "服务暂时不可用，普通排盘不受 AI 服务影响，请稍后重试。";
  return message || `服务返回错误（HTTP ${status}）`;
}

export const api = {
  provinces: () => request<Province[]>("/api/v1/locations/provinces"),
  cities: (province: string) =>
    request<City[]>(`/api/v1/locations/cities?province=${encodeURIComponent(province)}`),
  createChart: (payload: ChartRequest) =>
    request<ChartResult>("/api/v1/charts", { method: "POST", body: JSON.stringify(payload) }, NETWORK_TIMEOUTS.write),
  createAnalysis: (payload: ChartRequest) =>
    request<AnalysisAccepted>("/api/v1/analyses", {
      method: "POST",
      body: JSON.stringify(payload),
    }, NETWORK_TIMEOUTS.write),
  getAnalysisStatus: (jobId: string) =>
    request<AnalysisStatus>(`/api/v1/analyses/${encodeURIComponent(jobId)}/status`),
  getAnalysis: (jobId: string) =>
    request<AnalysisResult>(`/api/v1/analyses/${encodeURIComponent(jobId)}`),
  retrySection: (jobId: string, code: string) =>
    request<AnalysisAccepted>(
      `/api/v1/analyses/${encodeURIComponent(jobId)}/sections/${encodeURIComponent(code)}/retry`,
      { method: "POST" },
    ),
  cancelAnalysis: (jobId: string) =>
    request<AnalysisStatus>(`/api/v1/analyses/${encodeURIComponent(jobId)}/cancel`, {
      method: "POST",
    }),
  deleteAnalysis: (jobId: string) =>
    request<void>(`/api/v1/analyses/${encodeURIComponent(jobId)}`, { method: "DELETE" }),
  deleteChart: (chartId: string) =>
    request<void>(`/api/v1/charts/${encodeURIComponent(chartId)}`, { method: "DELETE" }),
};
