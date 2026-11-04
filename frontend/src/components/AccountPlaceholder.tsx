export function AccountPlaceholder({ label = "正在读取卡券…", profile = false }: { label?: string; profile?: boolean }) {
  return <div className={`paper-card account-placeholder${profile ? " placeholder-profile" : ""}`} role="status" aria-label={label}>
    <span className="sr-only">{label}</span>
    <div aria-hidden="true">{profile && <span className="skeleton-avatar" />}<span className="skeleton-line skeleton-title" /><span className="skeleton-line" /><span className="skeleton-block" /><span className="skeleton-block" /></div>
  </div>;
}
