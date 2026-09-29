import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";
import { AnalysisPanel } from "./components/AnalysisPanel";
import { AccountPanel } from "./components/AccountPanel";
import { BirthForm } from "./components/BirthForm";
import { ChartResultView } from "./components/ChartResultView";
import { ConfirmDialog, type ConfirmDialogState } from "./components/ConfirmDialog";
import { useMobileViewport } from "./hooks/useMobileViewport";
import { useVersionCheck } from "./hooks/useVersionCheck";
import type {
  AnalysisAccepted,
  AnalysisHistoryItem,
  AnalysisResult,
  AnalysisStatus,
  AuthState,
  ChartRequest,
  ChartResult,
} from "./types";
import { getWeChatIntegrationState } from "./wechat";
import { ACTIVE_JOB_STATUSES, nextPollingDelay } from "./polling";

const STORAGE_KEY = "bazi.analysis.task.v1";
const PENDING_ANALYSIS_KEY = "bazi.analysis.pending-login.v1";

function clearSavedTask() {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    // WeChat private mode can disable storage; the current page still remains usable.
  }
}

function saveTask(jobId: string, chartId: string) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ jobId, chartId }));
    return true;
  } catch {
    return false;
  }
}

function readSavedTask(): { jobId: string; chartId: string } | null {
  try {
    const value = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null") as unknown;
    if (
      value &&
      typeof value === "object" &&
      "jobId" in value &&
      "chartId" in value &&
      typeof value.jobId === "string" &&
      typeof value.chartId === "string"
    ) return { jobId: value.jobId, chartId: value.chartId };
  } catch {
    clearSavedTask();
  }
  return null;
}

function savePendingAnalysis(payload: ChartRequest) {
  try {
    sessionStorage.setItem(PENDING_ANALYSIS_KEY, JSON.stringify(payload));
  } catch {
    // Login still works; the user may need to submit the form again afterwards.
  }
}

function takePendingAnalysis(): ChartRequest | null {
  try {
    const raw = sessionStorage.getItem(PENDING_ANALYSIS_KEY);
    sessionStorage.removeItem(PENDING_ANALYSIS_KEY);
    return raw ? (JSON.parse(raw) as ChartRequest) : null;
  } catch {
    return null;
  }
}

function acceptedStatus(accepted: AnalysisAccepted): AnalysisStatus {
  return {
    job_id: accepted.job_id,
    chart_id: accepted.chart_id,
    status: accepted.status,
    model_id: "",
    prompt_version: "",
    request_hash: "",
    cancel_requested: false,
    completed_sections: 0,
    failed_sections: 0,
    total_sections: 8,
    created_at: new Date().toISOString(),
    started_at: null,
    finished_at: null,
  };
}

export function App() {
  const [saved] = useState(readSavedTask);
  const [chart, setChart] = useState<ChartResult | null>(null);
  const [jobId, setJobId] = useState(saved?.jobId || "");
  const [chartId, setChartId] = useState(saved?.chartId || "");
  const [analysisStatus, setAnalysisStatus] = useState<AnalysisStatus | null>(null);
  const [analysisResult, setAnalysisResult] = useState<AnalysisResult | null>(null);
  const [busy, setBusy] = useState<"chart" | "analysis" | null>(null);
  const [actionBusy, setActionBusy] = useState<string | null>(null);
  const [pollRevision, setPollRevision] = useState(0);
  const [error, setError] = useState("");
  const [message, setMessage] = useState(saved ? "正在恢复上次的分析任务…" : "");
  const [networkState, setNetworkState] = useState<"online" | "offline" | "weak">(
    navigator.onLine ? "online" : "offline",
  );
  const [networkMessage, setNetworkMessage] = useState("");
  const [confirmDialog, setConfirmDialog] = useState<ConfirmDialogState | null>(null);
  const [authState, setAuthState] = useState<AuthState | null>(null);
  const [accountOpen, setAccountOpen] = useState(false);
  const [accountBusy, setAccountBusy] = useState(false);
  const [history, setHistory] = useState<AnalysisHistoryItem[]>([]);
  const submissionLock = useRef(false);
  const version = useVersionCheck();
  useMobileViewport();
  const weChatState = getWeChatIntegrationState();

  useEffect(() => {
    let active = true;
    api.authState()
      .then((nextAuth) => {
        if (!active) return;
        setAuthState(nextAuth);
        if (nextAuth.authenticated) {
          const pending = takePendingAnalysis();
          if (pending) void submit(pending, "analysis", true);
        }
      })
      .catch(() => {
        // Auth is an optional capability; deterministic charting stays available.
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    const onOnline = () => {
      setNetworkState("online");
      setNetworkMessage("");
    };
    const onOffline = () => {
      setNetworkState("offline");
      setNetworkMessage("网络已断开，恢复连接后将自动继续查询任务。");
    };
    window.addEventListener("online", onOnline);
    window.addEventListener("offline", onOffline);
    return () => {
      window.removeEventListener("online", onOnline);
      window.removeEventListener("offline", onOffline);
    };
  }, []);

  useEffect(() => {
    if (!jobId) return;
    let stopped = false;
    let timer: number | undefined;
    let inFlight = false;
    let failureCount = 0;

    function schedule(delay: number) {
      if (stopped || document.visibilityState === "hidden" || !navigator.onLine) return;
      if (timer) window.clearTimeout(timer);
      timer = window.setTimeout(poll, delay);
    }

    async function poll() {
      if (stopped || inFlight || document.visibilityState === "hidden" || !navigator.onLine) return;
      inFlight = true;
      try {
        const status = await api.getAnalysisStatus(jobId);
        if (stopped) return;
        setAnalysisStatus(status);
        setChartId(status.chart_id);
        const result = await api.getAnalysis(jobId);
        if (stopped) return;
        setAnalysisResult(result);
        setChart(result.chart);
        setMessage("");
        setNetworkState("online");
        setNetworkMessage("");
        failureCount = 0;
        const hasActiveSection = result.sections.some((section) => ["pending", "running"].includes(section.status));
        if (ACTIVE_JOB_STATUSES.has(status.status) || (status.status === "partial" && hasActiveSection)) {
          schedule(2000);
        }
      } catch (reason) {
        if (stopped) return;
        const apiError = reason as ApiError;
        setMessage("");
        if (apiError.status === 404) {
          setError(apiError.message);
          clearSavedTask();
          setJobId("");
          setChartId("");
          setAnalysisStatus(null);
          setAnalysisResult(null);
        } else {
          setError("");
          failureCount += 1;
          const delay = nextPollingDelay(failureCount);
          const weakNetwork = ["offline", "timeout", "network_error"].includes(apiError.code || "");
          setNetworkState(navigator.onLine ? "weak" : "offline");
          setNetworkMessage(
            navigator.onLine
              ? `${weakNetwork ? "当前网络较慢" : "服务暂时不可用"}，${delay / 1000} 秒后自动重试。`
              : "网络已断开，恢复连接后将自动继续查询任务。",
          );
          schedule(delay);
        }
      } finally {
        inFlight = false;
      }
    }

    function wakePolling() {
      const online = navigator.onLine;
      setNetworkState(online ? "online" : "offline");
      setNetworkMessage(online ? "网络已恢复，正在更新任务…" : "网络已断开，恢复连接后将自动继续查询任务。");
      if (online && document.visibilityState === "visible") {
        failureCount = 0;
        schedule(0);
      }
    }

    function pauseOffline() {
      if (timer) window.clearTimeout(timer);
      setNetworkState("offline");
      setNetworkMessage("网络已断开，恢复连接后将自动继续查询任务。");
    }

    function onVisibilityChange() {
      if (document.visibilityState === "visible") wakePolling();
      else if (timer) window.clearTimeout(timer);
    }

    window.addEventListener("online", wakePolling);
    window.addEventListener("offline", pauseOffline);
    document.addEventListener("visibilitychange", onVisibilityChange);
    schedule(0);
    return () => {
      stopped = true;
      if (timer) window.clearTimeout(timer);
      window.removeEventListener("online", wakePolling);
      window.removeEventListener("offline", pauseOffline);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [jobId, pollRevision]);

  function beginLogin() {
    const returnTo = `${window.location.pathname}${window.location.search}${window.location.hash}`;
    window.location.assign(`/api/v1/auth/wechat/start?return_to=${encodeURIComponent(returnTo)}`);
  }

  async function toggleAccount() {
    const nextOpen = !accountOpen;
    setAccountOpen(nextOpen);
    if (!nextOpen) return;
    setAccountBusy(true);
    try {
      setHistory(await api.myAnalyses());
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setAccountBusy(false);
    }
  }

  async function logout() {
    setAccountBusy(true);
    try {
      await api.logout();
      setAuthState((current) => current ? { ...current, authenticated: false, user: null } : current);
      setHistory([]);
      setAccountOpen(false);
      setMessage("已退出微信账号，本机已生成的页面仍可继续查看。 ");
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setAccountBusy(false);
    }
  }

  function openHistoryItem(item: AnalysisHistoryItem) {
    saveTask(item.job_id, item.chart_id);
    setJobId(item.job_id);
    setChartId(item.chart_id);
    setAnalysisStatus(null);
    setAnalysisResult(null);
    setAccountOpen(false);
    setPollRevision((value) => value + 1);
    window.setTimeout(
      () => document.getElementById("analysis-title")?.scrollIntoView?.({ behavior: "smooth" }),
      0,
    );
  }

  async function submit(
    payload: ChartRequest,
    mode: "chart" | "analysis",
    skipAuthCheck = false,
  ) {
    if (
      !skipAuthCheck
      && mode === "analysis"
      && authState?.enabled
      && authState.require_for_analysis
      && !authState.authenticated
    ) {
      savePendingAnalysis(payload);
      beginLogin();
      return;
    }
    if (submissionLock.current) return;
    submissionLock.current = true;
    setBusy(mode);
    setError("");
    setMessage("");
    try {
      if (mode === "chart") {
        const nextChart = await api.createChart(payload);
        setChart(nextChart);
        setMessage("排盘完成。结果由后端确定性规则计算，不依赖 AI。 ");
        window.setTimeout(() => document.getElementById("chart-title")?.scrollIntoView?.({ behavior: "smooth" }), 0);
      } else {
        const accepted = await api.createAnalysis(payload);
        const nextStatus = acceptedStatus(accepted);
        const savedLocally = saveTask(accepted.job_id, accepted.chart_id);
        setAnalysisStatus(nextStatus);
        setAnalysisResult(null);
        setJobId(accepted.job_id);
        setChartId(accepted.chart_id);
        setMessage(
          !savedLocally
            ? "任务已提交；当前微信环境禁止本地存储，关闭页面后可能无法自动恢复。"
            : accepted.deduplicated
              ? "已找到相同任务，正在恢复已有进度。"
              : "任务已提交，八个板块将在后端依次生成。 ",
        );
        window.setTimeout(() => document.getElementById("analysis-title")?.scrollIntoView?.({ behavior: "smooth" }), 0);
      }
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setBusy(null);
      submissionLock.current = false;
    }
  }

  async function runAction(key: string, action: () => Promise<unknown>, success: string) {
    setActionBusy(key);
    setError("");
    try {
      await action();
      setMessage(success);
      if (jobId && key.startsWith("retry:")) {
        const status = await api.getAnalysisStatus(jobId);
        setAnalysisStatus(status);
        setPollRevision((value) => value + 1);
      }
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setActionBusy(null);
      setConfirmDialog(null);
    }
  }

  function retrySection(code: string) {
    if (!jobId) return;
    void runAction(`retry:${code}`, () => api.retrySection(jobId, code), "已重新排队，将继续更新本板块。 ");
  }

  function cancelAnalysis() {
    if (!jobId) return;
    setConfirmDialog({
      title: "取消当前分析？",
      description: "已完成的板块会保留，尚未开始的板块将停止生成。",
      confirmLabel: "确认取消",
      action: () => void runAction("cancel", async () => {
        const status = await api.cancelAnalysis(jobId);
        setAnalysisStatus(status);
        setPollRevision((value) => value + 1);
      }, "取消请求已提交。 "),
    });
  }

  function deleteAnalysis() {
    if (!jobId) return;
    setConfirmDialog({
      title: "删除这份 AI 分析？",
      description: "分析正文和任务记录会被删除，出生信息与命盘快照暂时保留。此操作无法撤销。",
      confirmLabel: "删除分析",
      danger: true,
      action: () => void runAction("delete-analysis", async () => {
        await api.deleteAnalysis(jobId);
        clearSavedTask();
        setJobId("");
        setAnalysisStatus(null);
        setAnalysisResult(null);
      }, "分析已删除。 "),
    });
  }

  function deleteChart() {
    if (!chartId) return;
    setConfirmDialog({
      title: "删除全部出生资料？",
      description: "出生信息、命盘快照、全部分析及调用记录都会被彻底删除。此操作无法撤销。",
      confirmLabel: "全部删除",
      danger: true,
      action: () => void runAction("delete-chart", async () => {
        await api.deleteChart(chartId);
        clearSavedTask();
        setJobId("");
        setChartId("");
        setChart(null);
        setAnalysisStatus(null);
        setAnalysisResult(null);
      }, "出生信息及关联结果已删除。 "),
    });
  }

  return (
    <div className="app-shell">
      <header className="site-header">
        <a className="brand" href="#top" aria-label="知命八字排盘首页">
          <span className="brand-seal">命</span>
          <span><b>知命</b><small>确定性八字排盘</small></span>
        </a>
        <nav aria-label="页面导航">
          <a href="#form">出生信息</a>
          <a href="#result">排盘结果</a>
          <a href="#analysis">AI 分析</a>
        </nav>
        <span className="api-state"><i /> {weChatState.isWeChat ? "微信 H5" : "移动 H5"} · 规则引擎</span>
        {authState ? (
          <AccountPanel
            auth={authState}
            open={accountOpen}
            busy={accountBusy}
            history={history}
            onToggle={() => void toggleAccount()}
            onLogin={beginLogin}
            onLogout={() => void logout()}
            onOpenReport={openHistoryItem}
          />
        ) : null}
      </header>

      <main id="top">
        <section className="intro">
          <div className="intro-copy">
            <div className="eyebrow"><span /> 规则可审计 · 结果可追溯</div>
            <h1>把生辰交给规则，<br /><em>把判断留给自己。</em></h1>
            <p>基于立春换年、节令换月、真太阳时与 23 点换日的确定性排盘。AI 只负责文化解读，不参与四柱计算。</p>
          </div>
          <div className="intro-orbit" aria-hidden="true">
            <span className="orbit-ring ring-one" />
            <span className="orbit-ring ring-two" />
            <span className="orbit-center">天<br />地<br />人</span>
            <i className="orbit-mark mark-one">甲</i>
            <i className="orbit-mark mark-two">子</i>
            <i className="orbit-mark mark-three">辰</i>
            <i className="orbit-mark mark-four">午</i>
          </div>
        </section>

        <div className="top-disclaimer" role="note">
          <b>文化参考，不是人生判决</b>
          <span>命理内容不构成医疗、投资、法律建议或对人生事件的确定性预测，请勿据此替代专业意见与现实判断。</span>
        </div>

        {version.updateAvailable && (
          <div className="update-banner" role="status">
            <span><b>发现新版本</b> 为避免微信缓存旧页面，建议立即刷新。</span>
            <button type="button" onClick={version.refresh}>刷新更新</button>
          </div>
        )}

        {networkState !== "online" && (
          <div className={`network-banner network-${networkState}`} role="status">
            <span aria-hidden="true">{networkState === "offline" ? "×" : "…"}</span>
            <p>{networkMessage || (networkState === "offline" ? "当前处于离线状态。" : "当前网络较慢，请耐心等待。")}</p>
          </div>
        )}

        <div id="form"><BirthForm busy={busy} onSubmit={submit} /></div>

        {(message || error) && (
          <div className={`global-message ${error ? "global-error" : "global-success"}`} role={error ? "alert" : "status"}>
            <span aria-hidden="true">{error ? "!" : "✓"}</span>
            <p>{error || message}</p>
            {error && <button type="button" onClick={() => setError("")} aria-label="关闭错误提示">×</button>}
          </div>
        )}

        <div id="result">
          {chart ? <ChartResultView chart={chart} /> : (
            <section className="empty-state" aria-label="排盘空状态">
              <span>四柱</span>
              <h2>命盘结果将在这里展开</h2>
              <p>填写出生信息并选择“开始排盘”，无需数据库或 AI 服务。</p>
            </section>
          )}
        </div>

        <div id="analysis">
          <AnalysisPanel
            status={analysisStatus}
            result={analysisResult}
            actionBusy={actionBusy}
            onRetry={retrySection}
            onCancel={cancelAnalysis}
            onDeleteAnalysis={deleteAnalysis}
            onDeleteChart={deleteChart}
          />
        </div>
      </main>

      <footer>
        <div className="brand compact"><span className="brand-seal">命</span><span><b>知命</b><small>规则先于解释</small></span></div>
        <p>本页面不会要求或保存模型密钥、数据库密码。DeepSeek 密钥只应配置在后端 worker 环境中。</p>
      </footer>

      <ConfirmDialog dialog={confirmDialog} busy={actionBusy !== null} onCancel={() => setConfirmDialog(null)} />
    </div>
  );
}
