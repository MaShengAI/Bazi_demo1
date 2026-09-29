import type { AnalysisHistoryItem, AuthState } from "../types";

interface AccountPanelProps {
  auth: AuthState;
  open: boolean;
  busy: boolean;
  history: AnalysisHistoryItem[];
  onToggle: () => void;
  onLogin: () => void;
  onLogout: () => void;
  onOpenReport: (item: AnalysisHistoryItem) => void;
}

const STATUS_LABELS: Record<string, string> = {
  pending: "等待中",
  running: "分析中",
  partial: "部分完成",
  completed: "已完成",
  failed: "失败",
  cancelled: "已取消",
};

export function AccountPanel({
  auth,
  open,
  busy,
  history,
  onToggle,
  onLogin,
  onLogout,
  onOpenReport,
}: AccountPanelProps) {
  if (!auth.enabled) return null;
  if (!auth.authenticated) {
    return (
      <button className="account-trigger login-trigger" type="button" onClick={onLogin}>
        微信登录
      </button>
    );
  }

  return (
    <div className="account-menu">
      <button className="account-trigger" type="button" onClick={onToggle} aria-expanded={open}>
        {auth.user?.avatar_url ? (
          <img src={auth.user.avatar_url} alt="" referrerPolicy="no-referrer" />
        ) : (
          <span className="account-avatar">微</span>
        )}
        <span>{auth.user?.display_name || "我的报告"}</span>
      </button>
      {open && (
        <div className="account-popover">
          <div className="account-popover-head">
            <div>
              <b>{auth.user?.display_name || "微信用户"}</b>
              <small>
                {auth.analysis_limit_per_24h > 0
                  ? `每 24 小时最多 ${auth.analysis_limit_per_24h} 份分析`
                  : "报告已安全关联到当前微信账号"}
              </small>
            </div>
            <button type="button" onClick={onLogout}>退出</button>
          </div>
          <div className="account-report-list">
            {busy ? <p className="account-empty">正在读取报告…</p> : null}
            {!busy && history.length === 0 ? (
              <p className="account-empty">还没有 AI 分析报告</p>
            ) : null}
            {history.map((item) => (
              <button
                className="account-report"
                type="button"
                key={item.job_id}
                onClick={() => onOpenReport(item)}
              >
                <span>
                  <b>{item.name || "未命名命盘"}</b>
                  <small>{item.birth_local_datetime?.replace("T", " ") || "出生时间未记录"}</small>
                </span>
                <span>
                  {STATUS_LABELS[item.status] || item.status}
                  <small>{item.completed_sections}/{item.total_sections}</small>
                </span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
