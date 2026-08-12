export const ACTIVE_JOB_STATUSES = new Set(["pending", "running"]);

export function nextPollingDelay(failureCount: number) {
  return Math.min(2000 * (2 ** Math.max(0, failureCount - 1)), 30_000);
}
