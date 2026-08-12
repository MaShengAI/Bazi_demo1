import { useEffect } from "react";

export interface ConfirmDialogState {
  title: string;
  description: string;
  confirmLabel: string;
  danger?: boolean;
  action: () => void;
}

export function ConfirmDialog({
  dialog,
  busy,
  onCancel,
}: {
  dialog: ConfirmDialogState | null;
  busy: boolean;
  onCancel: () => void;
}) {
  useEffect(() => {
    if (!dialog) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) onCancel();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      document.body.style.overflow = previous;
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [dialog, busy, onCancel]);

  if (!dialog) return null;
  return (
    <div className="modal-backdrop confirm-backdrop" role="presentation">
      <section className="confirm-dialog" role="alertdialog" aria-modal="true" aria-labelledby="confirm-title" aria-describedby="confirm-description">
        <span className={`confirm-symbol${dialog.danger ? " danger" : ""}`} aria-hidden="true">!</span>
        <h3 id="confirm-title">{dialog.title}</h3>
        <p id="confirm-description">{dialog.description}</p>
        <div className="confirm-actions">
          <button className="button button-outline" type="button" onClick={onCancel} disabled={busy}>暂不操作</button>
          <button className={`button ${dialog.danger ? "button-danger" : "button-primary"}`} type="button" onClick={dialog.action} disabled={busy}>
            {busy && <span className="spinner" aria-hidden="true" />}{busy ? "正在处理" : dialog.confirmLabel}
          </button>
        </div>
      </section>
    </div>
  );
}
