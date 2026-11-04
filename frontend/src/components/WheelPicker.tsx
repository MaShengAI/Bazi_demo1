import { useBackDismiss } from "../customerNavigation";
import { useEffect, useId, useRef, type ReactNode } from "react";
import { flushSync } from "react-dom";

export interface WheelOption { value: string; label: string }
const ROW = 44;

export function WheelPicker({ label, options, value, onChange }: {
  label: string; options: WheelOption[]; value: string; onChange: (value: string) => void;
}) {
  const id = useId();
  const ref = useRef<HTMLDivElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const index = Math.max(0, options.findIndex(option => option.value === value));
  const latest = useRef({ options, value, onChange }); latest.current = { options, value, onChange };
  useEffect(() => {
    const commit = () => {
      clearTimeout(timer.current);
      const { options: items, value: current, onChange: change } = latest.current;
      const option = items[Math.max(0, Math.min(items.length - 1, Math.round((ref.current?.scrollTop || 0) / ROW)))];
      if (option && option.value !== current) change(option.value);
    };
    window.addEventListener("commit-picker-wheels", commit);
    return () => window.removeEventListener("commit-picker-wheels", commit);
  }, []);
  useEffect(() => {
    if (ref.current) ref.current.scrollTop = index * ROW;
    return () => clearTimeout(timer.current);
  }, [value, options.length]);
  const choose = (next: number) => {
    const option = options[Math.max(0, Math.min(options.length - 1, next))];
    if (option) {
      clearTimeout(timer.current);
      if (ref.current) ref.current.scrollTop = options.indexOf(option) * ROW;
      if (option.value !== value) onChange(option.value);
    }
  };
  return <div className="wheel-column"><span className="wheel-label">{label}</span><div className="wheel-frame">
    <div className="wheel-list" ref={ref} role="listbox" aria-label={label} tabIndex={0}
      aria-activedescendant={options.length ? `${id}-${index}` : undefined}
      onKeyDown={event => {
        const next = event.key === "ArrowDown" ? index + 1 : event.key === "ArrowUp" ? index - 1 : event.key === "Home" ? 0 : event.key === "End" ? options.length - 1 : event.key === "PageDown" ? index + 5 : event.key === "PageUp" ? index - 5 : null;
        if (next !== null) { event.preventDefault(); choose(next); }
      }}
      onScroll={event => {
        const element = event.currentTarget;
        clearTimeout(timer.current);
        timer.current = setTimeout(() => {
          const next = Math.max(0, Math.min(options.length - 1, Math.round(element.scrollTop / ROW)));
          if (options[next] && options[next].value !== value) onChange(options[next].value);
        }, 120);
      }}>
      {options.map((option, i) => <div id={`${id}-${i}`} key={option.value} role="option" aria-selected={option.value === value}
        className={`wheel-option${option.value === value ? " is-selected" : ""}`} onClick={() => choose(i)}>{option.label}</div>)}
    </div>
    <span className="wheel-selection" aria-hidden="true" />
  </div></div>;
}

export function PickerSheet({ title, description, onClose, onConfirm, confirmDisabled = false, children }: {
  title: string; description?: string; onClose: () => void; onConfirm: () => void; confirmDisabled?: boolean; children: ReactNode;
}) {
  useBackDismiss(true, onClose);
  const id = useId();
  const sheet = useRef<HTMLElement>(null);
  const close = useRef(onClose); close.current = onClose;
  const confirm = useRef(onConfirm); confirm.current = onConfirm;
  useEffect(() => {
    const original = document.body.style.overflow;
    const focused = document.activeElement as HTMLElement | null;
    document.body.style.overflow = "hidden";
    sheet.current?.focus();
    const keydown = (event: KeyboardEvent) => {
      if (event.key === "Escape") close.current();
      if (event.key !== "Tab") return;
      const controls = [...(sheet.current?.querySelectorAll<HTMLElement>('button:not(:disabled), [tabindex="0"]') || [])];
      if (!controls.length) return;
      const first = controls[0], last = controls[controls.length - 1];
      if (event.shiftKey && (document.activeElement === first || document.activeElement === sheet.current)) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    window.addEventListener("keydown", keydown);
    return () => { document.body.style.overflow = original; window.removeEventListener("keydown", keydown); focused?.focus({ preventScroll: true }); };
  }, []);
  return <div className="modal-backdrop plum-picker-backdrop" onClick={event => { if (event.target === event.currentTarget) onClose(); }}>
    <section ref={sheet} tabIndex={-1} className="plum-picker-sheet" role="dialog" aria-modal="true" aria-labelledby={id}>
      <div className="picker-handle" aria-hidden="true" />
      <header className="plum-picker-header"><button type="button" onClick={onClose}>取消</button><h3 id={id}>{title}</h3><span aria-hidden="true">❀</span></header>
      {description && <p className="plum-picker-description">{description}</p>}
      {children}
      <button type="button" className="button button-primary plum-picker-confirm" onClick={() => { flushSync(() => window.dispatchEvent(new Event("commit-picker-wheels"))); confirm.current(); }} disabled={confirmDisabled}>确定</button>
    </section>
  </div>;
}
