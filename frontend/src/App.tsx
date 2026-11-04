import { ReportPlaceholder } from "./components/ReportPlaceholder";
import { CustomerNavigation, CustomerNavigationContext } from "./customerNavigation";
import { ReviewPage } from "./components/ReviewPages";
import { RedeemPage } from "./components/RedeemPage";
import { useEffect, useRef, useState } from "react";
import { api, ApiError, isSessionExpired, SESSION_EXPIRED_EVENT } from "./api";
import { AccountPlaceholder } from "./components/AccountPlaceholder";
import { AnalysisPanel } from "./components/AnalysisPanel";
import { BottomTabs, CouponPage, MyAccount, PageTitle, PrivacyPage, readCustomerRoute, ReportBack, ReportList, Reviews, ServicePage, type CustomerRoute } from "./components/CustomerPages";
import { BirthForm } from "./components/BirthForm";
import { CardShop } from "./components/CardShop";
import { ChartResultView } from "./components/ChartResultView";
import { ReadingPreview } from "./components/ReadingPreview";
import { ConfirmDialog, type ConfirmDialogState } from "./components/ConfirmDialog";
import { useMobileViewport } from "./hooks/useMobileViewport";
import { useVersionCheck } from "./hooks/useVersionCheck";
import { beginWechatLogin, completeWechatLogin, pauseAutoLogin, shouldAutoLogin } from "./wechatLogin";
import type {
  AnalysisAccepted,
  SavedReportItem,
  AnalysisResult,
  AnalysisStatus,
  AuthState,
  ChartRequest,
  ChartResult,
  CardAccount,
} from "./types";
import { ACTIVE_JOB_STATUSES, nextPollingDelay } from "./polling";
import "./customer.css";
import "./typography.css";

const STORAGE_KEY = "bazi.analysis.task.v1";
const PENDING_ANALYSIS_KEY = "bazi.analysis.pending-login.v1";
const PENDING_CHART_KEY = "bazi.chart.pending-login.v1";
const DRAFT_KEY = "bazi.birth.session-draft.v1";

function preventContentInteraction(event: React.SyntheticEvent) {
  if (event.target instanceof Element && event.target.closest('input, textarea, [contenteditable="true"], [contenteditable=""]')) return;
  event.preventDefault();
}

function saveDraft(payload: ChartRequest | null, chartId?: string | null) {
  try {
    if (payload) sessionStorage.setItem(DRAFT_KEY, JSON.stringify({ payload, chartId, at: Date.now() }));
    else sessionStorage.removeItem(DRAFT_KEY);
  } catch { /* Form and payment remain usable without browser storage. */ }
}

function readDraft(): ChartRequest | null {
  try {
    const value = JSON.parse(sessionStorage.getItem(DRAFT_KEY) || "null");
    const draft = value?.payload;
    if (Date.now() - value?.at < 60 * 60 * 1000 && ["male", "female"].includes(draft?.gender)
      && typeof draft.birth_local_datetime === "string" && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(draft.birth_local_datetime)
      && Number.isInteger(draft.location_id)) return draft as ChartRequest;
  } catch { /* Invalid/expired drafts are never submitted automatically. */ }
  return null;
}

function readDraftChartId(): string | null {
  try {
    const id = JSON.parse(sessionStorage.getItem(DRAFT_KEY) || "null")?.chartId;
    return readDraft() && typeof id === "string" && /^[\w-]{1,100}$/.test(id) ? id : null;
  } catch { return null; }
}

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

function savePendingChart(payload: ChartRequest) {
  try { sessionStorage.setItem(PENDING_CHART_KEY, JSON.stringify(payload)); }
  catch { /* A blocked session store cannot start an unintended paid analysis. */ }
}

function takePendingChart(): ChartRequest | null {
  try {
    const raw = sessionStorage.getItem(PENDING_CHART_KEY);
    sessionStorage.removeItem(PENDING_CHART_KEY);
    return raw ? JSON.parse(raw) as ChartRequest : null;
  } catch { return null; }
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
  const [route, setRoute] = useState(readCustomerRoute);
  const [navigation] = useState(() => new CustomerNavigation());
  const [saved] = useState(readSavedTask);
  const [chart, setChart] = useState<ChartResult | null>(null);
  const [freeChartId, setFreeChartId] = useState<string | null>(readDraftChartId);
  const [chartLoading, setChartLoading] = useState(false);
  const [chartLoadFinishedFor, setChartLoadFinishedFor] = useState("");
  const [jobId, setJobId] = useState(route.reportId || (route.page !== "chart" ? saved?.jobId : "") || "");
  const [chartId, setChartId] = useState(route.page !== "chart" ? saved?.chartId || "" : "");
  const [analysisStatus, setAnalysisStatus] = useState<AnalysisStatus | null>(null);
  const [analysisResult, setAnalysisResult] = useState<AnalysisResult | null>(null);
  const [busy, setBusy] = useState<"chart" | "analysis" | null>(null);
  const [deletingChartId, setDeletingChartId] = useState<string | null>(null);
  const deletionLock = useRef(false);
  const [pollRevision, setPollRevision] = useState(0);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [networkState, setNetworkState] = useState<"online" | "offline" | "weak">(
    navigator.onLine ? "online" : "offline",
  );
  const [networkMessage, setNetworkMessage] = useState("");
  const [confirmDialog, setConfirmDialog] = useState<ConfirmDialogState | null>(null);
  const [authState, setAuthState] = useState<AuthState | null>(null);
  const [authUnavailable, setAuthUnavailable] = useState(false);
  const [sessionExpired, setSessionExpired] = useState(false);
  const expiredSession = useRef(false);
  const authEpoch = useRef(0);
  const [cardRevision, setCardRevision] = useState(0);
  const [accountBusy, setAccountBusy] = useState(false);
  const [historyError, setHistoryError] = useState("");
  const [account, setAccount] = useState<CardAccount | null>(null);
  const [accountError, setAccountError] = useState("");
  const [cardsBusy, setCardsBusy] = useState(false);
  const [pendingPayload, setPendingPayload] = useState<ChartRequest | null>(readDraft);
  const submittedReadingJob = useRef<string | null>(null);
  const accountRequest = useRef(0);
  const historyRequest = useRef(0);
  const [history, setHistory] = useState<SavedReportItem[]>([]);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const submissionLock = useRef(false);
  const version = useVersionCheck();
  useMobileViewport();

  function navigate(page: CustomerRoute, reportId?: string, replace = false) {
    navigation.go(`#/${page}${reportId ? `/${encodeURIComponent(reportId)}` : ""}`, replace);
  }
  function goBack(page: CustomerRoute, reportId?: string) {
    navigation.back(`#/${page}${reportId ? `/${encodeURIComponent(reportId)}` : ""}`);
  }

  useEffect(() => {
    const expire = () => {
      if (expiredSession.current) return;
      expiredSession.current = true; authEpoch.current += 1;
      historyRequest.current += 1; accountRequest.current += 1;
      setSessionExpired(true);
      setAuthState(current => current ? { ...current, authenticated: false, user: null } : current);
      setHistory([]); setHistoryLoaded(false); setHistoryError(""); setAccount(null); setAccountError("");
      setCardsBusy(false); setAccountBusy(false);
      setJobId(""); setChartId(""); setAnalysisStatus(null); setAnalysisResult(null);
      setChart(null); setFreeChartId(null); setChartLoading(false);
      setConfirmDialog(null); setError(""); setMessage("");
      setNetworkState("online"); setNetworkMessage("");
      // Keep the saved report pointer and birth draft for explicit recovery after login.
    };
    window.addEventListener(SESSION_EXPIRED_EVENT, expire);
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, expire);
  }, []);

  useEffect(() => navigation.mount(() => setRoute(readCustomerRoute())), [navigation]);

  useEffect(() => {
    if (route.reportId && route.reportId !== jobId) {
      setAnalysisResult(null); setAnalysisStatus(null); setJobId(route.reportId);
      setError("");
    }
  }, [route.reportId]);

  useEffect(() => {
    if (route.page !== "chart" || !route.chartId || !authState?.authenticated) return;
    let active = true;
    const epoch = authEpoch.current;
    setChartLoading(true);
    api.savedChart(route.chartId).then(savedChart => {
      if (!active || epoch !== authEpoch.current || expiredSession.current) return;
      if (savedChart.job_id) { navigate("report", savedChart.job_id, true); return; }
      setChart(savedChart.chart); setFreeChartId(savedChart.chart_id);
      setPendingPayload(savedChart.request); saveDraft(savedChart.request, savedChart.chart_id);
    }).catch(reason => {
      if (active && epoch === authEpoch.current && !isSessionExpired(reason)) setError((reason as Error).message);
    }).finally(() => { if (active) { setChartLoading(false); setChartLoadFinishedFor(route.chartId!); } });
    return () => { active = false; };
  }, [route.page, route.chartId, authState?.user?.id]);

  // A newly unlocked report opens at its preparation/content area. Reopening
  // an existing report starts at the birth facts, with all content below it.
  useEffect(() => {
    if (route.page !== "report" || submittedReadingJob.current !== route.reportId
      || analysisResult?.job_id !== route.reportId) return;
    const frame = window.requestAnimationFrame(() => {
      document.getElementById("analysis")?.scrollIntoView?.({ block: "start", behavior: "instant" });
      submittedReadingJob.current = null;
    });
    return () => window.cancelAnimationFrame(frame);
  }, [route.page, route.reportId, analysisResult?.job_id]);

  async function refreshHistory() {
    const requestId = ++historyRequest.current;
    setAccountBusy(true); setHistoryError("");
    try { const items = await api.myReports(); if (requestId === historyRequest.current) { setHistory(items); setHistoryLoaded(true); } }
    catch (reason) { if (!isSessionExpired(reason) && requestId === historyRequest.current) setHistoryError((reason as Error).message); }
    finally { if (requestId === historyRequest.current) setAccountBusy(false); }
  }

  async function refreshCards() {
    if (!authState?.payments_enabled || !authState.authenticated) return;
    const requestId = ++accountRequest.current;
    setCardsBusy(true); setAccountError("");
    try { const next = await api.cardAccount(); if (requestId === accountRequest.current) setAccount(next); }
    catch (reason) { if (!isSessionExpired(reason) && requestId === accountRequest.current) setAccountError((reason as Error).message); }
    finally { if (requestId === accountRequest.current) setCardsBusy(false); }
  }

  useEffect(() => {
    if (route.page === "reports" && authState?.authenticated) void refreshHistory();
    return () => { historyRequest.current += 1; };
  }, [route.page, authState?.user?.id, cardRevision]);

  useEffect(() => {
    if (["me", "coupon", "cards", "redeem"].includes(route.page)) void refreshCards();
    const visible = () => { if (document.visibilityState === "visible" && ["me", "coupon"].includes(route.page)) void refreshCards(); };
    const timer = window.setInterval(visible, 60000);
    document.addEventListener("visibilitychange", visible);
    return () => { accountRequest.current += 1; window.clearInterval(timer); document.removeEventListener("visibilitychange", visible); };
  }, [route.page, authState?.authenticated, authState?.payments_enabled, authState?.user?.id, cardRevision]);

  useEffect(() => {
    let active = true;
    const epoch = authEpoch.current;
    api.authState()
      .then((nextAuth) => {
        if (!active || epoch !== authEpoch.current) return;
        setAuthState(nextAuth);
        if (nextAuth.authenticated) {
          completeWechatLogin();
          const pendingChart = takePendingChart();
          if (pendingChart) { void submit(pendingChart, "chart", true); return; }
          const pending = takePendingAnalysis();
          if (pending) void submit(pending, "analysis", true);
        } else if (shouldAutoLogin(nextAuth)) beginWechatLogin(true);
      })
      .catch(() => {
        if (!active || epoch !== authEpoch.current) return;
        setAuthState({ enabled: false, authenticated: false, require_for_analysis: false, analysis_limit_per_24h: 0, user: null });
        setAuthUnavailable(true);
        setError("账户服务暂时无法连接，请刷新页面后重试。");
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
        if (stopped || expiredSession.current) return;
        setAnalysisStatus(status);
        setChartId(status.chart_id);
        const result = await api.getAnalysis(jobId);
        if (stopped || expiredSession.current) return;
        setAnalysisResult(result);
        setMessage("");
        setNetworkState("online");
        setNetworkMessage("");
        failureCount = 0;
        const hasActiveSection = result.sections.some((section) => ["pending", "running"].includes(section.status));
        if (ACTIVE_JOB_STATUSES.has(status.status) || (status.status === "partial" && hasActiveSection)) {
          schedule(2000);
        }
      } catch (reason) {
        if (stopped || isSessionExpired(reason) || expiredSession.current) return;
        const apiError = reason as ApiError;
        setMessage("");
        if (apiError.status === 404 || apiError.status === 401 || apiError.status === 403) {
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
    beginWechatLogin();
  }

  async function logout() {
    setAccountBusy(true);
    try {
      await api.logout();
      pauseAutoLogin();
      authEpoch.current += 1;
      setAuthState((current) => current ? { ...current, authenticated: false, user: null } : current);
      historyRequest.current += 1; accountRequest.current += 1;
      setHistory([]); setHistoryLoaded(false);
      setAccount(null); setJobId(""); setChartId(""); setChart(null); setFreeChartId(null);
      setAnalysisStatus(null); setAnalysisResult(null); setPendingPayload(null); clearSavedTask(); saveDraft(null);
      try { sessionStorage.removeItem(PENDING_ANALYSIS_KEY); sessionStorage.removeItem(PENDING_CHART_KEY); } catch { /* Storage may be disabled. */ }
      setError(""); setMessage("已退出登录。"); navigate("me");
    } catch (reason) {
      if (!isSessionExpired(reason)) setError((reason as Error).message);
    } finally {
      setAccountBusy(false);
    }
  }

  function openHistoryItem(item: SavedReportItem) {
    if (!item.job_id) {
      setJobId(""); setAnalysisStatus(null); setAnalysisResult(null);
      setChart(null); setFreeChartId(null); setPendingPayload(null);
      setChartLoading(true); setChartLoadFinishedFor("");
      setError(""); setMessage("");
      navigate("chart", item.chart_id);
      return;
    }
    saveTask(item.job_id, item.chart_id);
    setJobId(item.job_id);
    setChartId(item.chart_id);
    setAnalysisStatus(null);
    setAnalysisResult(null);
    setError(""); setMessage("");
    navigate("report", item.job_id);
    setPollRevision((value) => value + 1);
  }

  async function submit(
    payload: ChartRequest,
    mode: "chart" | "analysis",
    skipAuthCheck = false,
  ) {
    if (submissionLock.current) return;
    submissionLock.current = true;
    const epoch = authEpoch.current;
    setBusy(mode);
    setError("");
    setMessage("");
    try {
      if (!skipAuthCheck) {
        if (authUnavailable) throw new Error("账户服务暂时无法连接，请刷新页面后重试。");
        const currentAuth = authState || await api.authState();
        if (expiredSession.current || epoch !== authEpoch.current) return;
        if (!authState) setAuthState(currentAuth);
        if (currentAuth.enabled && !currentAuth.authenticated
          && (mode === "chart" || currentAuth.require_for_analysis || currentAuth.payments_enabled)) {
          if (mode === "chart") { savePendingChart(payload); saveDraft(payload); }
          else savePendingAnalysis(payload);
          beginLogin(); return;
        }
      }
      if (mode === "chart") {
        const nextChart = await api.createChart(payload);
        if (expiredSession.current || epoch !== authEpoch.current) return;
        setChart(nextChart);
        setJobId(""); setChartId(""); setAnalysisResult(null); setAnalysisStatus(null);
        setFreeChartId(nextChart.saved_chart_id || null);
        setCardRevision(value => value + 1);
        setPendingPayload(payload); saveDraft(payload, nextChart.saved_chart_id);
        if (nextChart.analysis_job_id) navigate("report", nextChart.analysis_job_id);
        else navigate("chart", nextChart.saved_chart_id);
        setMessage("");
        window.setTimeout(() => document.getElementById("chart-facts")?.scrollIntoView?.({ behavior: "smooth", block: "start" }), 0);
      } else {
        const accepted = freeChartId ? await api.unlockChart(freeChartId) : await api.createAnalysis(payload);
        if (expiredSession.current || epoch !== authEpoch.current) return;
        setCardRevision((value) => value + 1);
        const nextStatus = acceptedStatus(accepted);
        const savedLocally = saveTask(accepted.job_id, accepted.chart_id);
        setAnalysisStatus(nextStatus);
        setAnalysisResult(null);
        setJobId(accepted.job_id);
        setChartId(accepted.chart_id);
        submittedReadingJob.current = accepted.job_id;
        setPendingPayload(null); saveDraft(null); navigate("report", accepted.job_id, true);
        setMessage(
          !savedLocally
            ? "任务已提交；当前微信环境禁止本地存储，关闭页面后可能无法自动恢复。"
            : accepted.deduplicated
              ? "已找到相同任务，正在恢复已有进度。"
              : "",
        );
      }
    } catch (reason) {
      setError((reason as Error).message);
      if (isSessionExpired(reason)) {
        setError("");
        setPendingPayload(payload); saveDraft(payload, mode === "analysis" ? freeChartId : null);
        if (mode === "chart") savePendingChart(payload);
        return;
      }
      if ((reason as ApiError).code === "cards_required") {
        setPendingPayload(payload); saveDraft(payload, freeChartId); navigate("cards");
      }
    } finally {
      setBusy(null);
      submissionLock.current = false;
    }
  }

  function requestDeleteReport(item: SavedReportItem) {
    if (deletionLock.current) return;
    setConfirmDialog({
      title: "删除此报告？",
      description: "删除后此命盘的八字详细解读需再次使用解读卡，此操作无法撤销",
      cancelLabel: "返回",
      confirmLabel: "确认删除",
      danger: true,
      action: () => void deleteReportData(item),
    });
  }

  async function deleteReportData(item: SavedReportItem) {
    if (deletionLock.current) return;
    deletionLock.current = true;
    setDeletingChartId(item.chart_id); setError("");
    try {
      await api.deleteChart(item.chart_id);
      if (expiredSession.current) return;
      if (readSavedTask()?.chartId === item.chart_id) clearSavedTask();
      if (chartId === item.chart_id) {
        setJobId(""); setChartId(""); setAnalysisStatus(null); setAnalysisResult(null);
      }
      if (freeChartId === item.chart_id) {
        setChart(null); setFreeChartId(null); setPendingPayload(null);
      setChartLoading(true); setChartLoadFinishedFor(""); saveDraft(null);
      }
      setHistory(items => items.filter(record => record.chart_id !== item.chart_id));
      setCardRevision(value => value + 1);
      setMessage("");
      await refreshHistory();
    } catch (reason) {
      if (!isSessionExpired(reason)) setError((reason as Error).message);
    } finally {
      deletionLock.current = false;
      setDeletingChartId(null); setConfirmDialog(null);
    }
  }

  function openPaymentPage() {
    if (!pendingPayload || busy) return;
    saveDraft(pendingPayload, freeChartId);
    navigate("cards");
  }

  function unlockFullReport() {
    if (!pendingPayload || busy) return;
    if (!authState?.authenticated || !authState.payments_enabled) {
      openPaymentPage();
      return;
    }
    void submit(pendingPayload, "analysis");
  }

  const page = route.page;
  const detail = page === "report";
  const reportResult = analysisResult?.job_id === route.reportId ? analysisResult : null;
  const reportStatus = analysisStatus?.job_id === route.reportId ? analysisStatus : null;
  const titleFor: Partial<Record<CustomerRoute, string>> = { cards: "解读卡", coupon: "优惠券", redeem: "兑换码", review: "写评价", service: "联系客服", privacy: "隐私与服务说明" };
  return (
    <CustomerNavigationContext.Provider value={navigation}><div className={`app-shell customer-app customer-page-${page}`} onContextMenu={preventContentInteraction} onDragStart={preventContentInteraction}>
      <main className="customer-main" id="top">
        {version.updateAvailable && <div className="update-banner" role="status"><span>发现新版本</span><button onClick={version.refresh}>刷新更新</button></div>}
        {networkState !== "online" && <div className={`network-banner network-${networkState}`} role="status"><p>{networkMessage || "网络较慢，请稍后重试。"}</p></div>}
        {(message || error) && <div className={`global-message ${error ? "global-error" : "global-success"}`} role={error ? "alert" : "status"}><p>{error || message}</p><button type="button" onClick={() => { setError(""); setMessage(""); }} aria-label="关闭提示">×</button></div>}
        {sessionExpired && ["measure", "me", "reports", "report", "chart", "cards", "coupon", "redeem", "review"].includes(page) && <section className="paper-card session-expired" role="alert"><h2>登录已过期</h2><p>请重新登录后继续查看报告和卡券。</p><button type="button" className="button button-primary" onClick={beginLogin}>重新登录</button></section>}

        <div hidden={page !== "measure"}>
          <header className="plum-brand"><h1>四柱知微</h1><p className="brand-caption">四柱观其势 · 五行知其微</p></header>
          <div id="form"><BirthForm busy={busy} onSubmit={submit} requireCards={authState?.payments_enabled} chartOnly active={page === "measure"} /></div>
          <Reviews />
          <p className="customer-footnote">传统文化参考，请结合现实判断。</p>
        </div>

        {page === "chart" && !sessionExpired && <>
          <ReportBack onBack={() => goBack(route.chartId ? "reports" : "measure")} />
          {chart && (!route.chartId || freeChartId === route.chartId) ? <><ChartResultView chart={chart} /><div className="report-reading-section"><h2 className="report-reading-heading">八字解读</h2><ReadingPreview onUnlock={unlockFullReport} busy={busy !== null} usesCard={Boolean(authState?.payments_enabled)} /></div></> : (route.chartId && (!authState || (authState.authenticated && (chartLoading || chartLoadFinishedFor !== route.chartId)))) ? <ReportPlaceholder key={route.chartId} /> : route.chartId ? <div className="paper-card report-empty"><h2>{authState?.authenticated ? "当前无法读取命盘" : "登录后查看报告"}</h2><button className="button button-primary" onClick={() => authState?.authenticated ? navigate("reports") : beginLogin()}>{authState?.authenticated ? "返回报告列表" : "微信登录"}</button></div> : <div className="paper-card report-empty"><h2>请先填写出生资料</h2><button className="button button-primary" onClick={() => pendingPayload ? void submit(pendingPayload, "chart") : navigate("measure")}>{pendingPayload ? "恢复本次排盘" : "去测算"}</button></div>}
        </>}

        {page === "reports" && !sessionExpired && <ReportList auth={authState} items={history} loaded={historyLoaded} busy={accountBusy} error={historyError} onLogin={beginLogin} onMeasure={() => navigate("measure")} onOpen={openHistoryItem} onDelete={requestDeleteReport} deletingChartId={deletingChartId} onRefresh={() => void refreshHistory()} onService={() => navigate("service")} />}

        {detail && !sessionExpired && <>
          <ReportBack onBack={() => goBack("reports")} />
          {reportResult && <ChartResultView chart={reportResult.chart} />}
          {(reportResult || (reportStatus && submittedReadingJob.current === jobId)) && <div className="report-reading-section" id="analysis"><h2 className="report-reading-heading">八字解读</h2><AnalysisPanel status={reportStatus} result={reportResult} /></div>}
          {authState?.authenticated && reportResult?.job_id === jobId && reportResult.status === "completed" && reportResult.sections.length === 8 && reportResult.sections.every(s => s.status === "completed" && s.content?.trim()) && <div className="report-review-entry"><button className="text-button" type="button" onClick={() => navigate("review", reportResult.job_id)}>写评价</button></div>}
          {!reportResult && (!reportStatus || submittedReadingJob.current !== jobId) && (jobId ? <ReportPlaceholder key={route.reportId} /> : <div className="paper-card report-empty" role="alert"><p>该报告当前无法读取，请返回报告列表。</p></div>)}
        </>}

        {page === "me" && !sessionExpired && <MyAccount auth={authState} account={account} loading={cardsBusy} error={accountError} navigate={navigate} onLogin={beginLogin} onLogout={() => void logout()} onRefresh={() => void refreshCards()} />}
        {titleFor[page] && (!sessionExpired || ["service", "privacy"].includes(page)) && <PageTitle title={titleFor[page]!} onBack={() => page === "review" ? goBack(route.reportId ? "report" : "reports", route.reportId) : goBack("me")} />}
        {page === "cards" && !sessionExpired && <>
          {!authState ? <AccountPlaceholder /> : authState.payments_enabled ? <CardShop key={`${authState.user?.id || "guest"}-${page}`} auth={authState} revision={cardRevision} onLogin={beginLogin} onPaid={() => { setCardRevision(r => r + 1); navigation.back("#/me"); }} /> : <div className="paper-card report-empty"><CustomerSymbol /><h2>解读卡购买暂未开放</h2><p>开放后，你可以在这里购买解读卡套餐。</p></div>}
        </>}
        {page === "coupon" && !sessionExpired && <CouponPage account={account} auth={authState} onLogin={beginLogin} error={accountError} onRetry={() => void refreshCards()} />}
        {page === "review" && !sessionExpired && <ReviewPage key={`${authState?.user?.id || "guest"}-${route.reportId || ""}`} reportId={route.reportId} auth={authState} onLogin={beginLogin} onSubmitted={() => setCardRevision(r => r + 1)} onReturn={() => goBack("report", route.reportId)} />}
        {page === "redeem" && !sessionExpired && <RedeemPage key={authState?.user?.id || "guest"} auth={authState} onLogin={beginLogin} onRedeemed={() => setCardRevision(r => r + 1)} />}
        {page === "service" && <ServicePage />}
        {page === "privacy" && <PrivacyPage />}
      </main>
      <BottomTabs page={page === "chart" && route.chartId ? "reports" : page} navigate={page => navigation.tab(`#/${page}`)} />
      <ConfirmDialog dialog={confirmDialog} busy={deletingChartId !== null} onCancel={() => setConfirmDialog(null)} />
    </div></CustomerNavigationContext.Provider>
  );
}

function CustomerSymbol() { return <div className="empty-scroll" aria-hidden="true">知</div>; }
