import type { JobStatus, SectionStatus } from "../types";

const labels: Record<JobStatus | SectionStatus, string> = {
  pending: "等待中",
  running: "分析中",
  partial: "部分完成",
  completed: "已完成",
  failed: "失败",
  cancelled: "已取消",
};

export function StatusBadge({ status }: { status: JobStatus | SectionStatus }) {
  return (
    <span className={`status-badge status-${status}`} data-testid={`status-${status}`}>
      <span className="status-dot" aria-hidden="true" />
      {labels[status]}
    </span>
  );
}

export const STATUS_LABELS = labels;
