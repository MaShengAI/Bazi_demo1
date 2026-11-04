import { useEffect, useState } from "react";
import { AccountPlaceholder } from "./AccountPlaceholder";

/** Fast reads stay quiet; a slower read gets a stable skeleton, never a text flash. */
export function ReportPlaceholder({ label = "正在读取报告" }: { label?: string }) {
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    const timer = window.setTimeout(() => setVisible(true), 450);
    return () => window.clearTimeout(timer);
  }, []);
  return <div className="report-loading-space" aria-busy="true">
    {visible && <AccountPlaceholder label={label} />}
  </div>;
}
