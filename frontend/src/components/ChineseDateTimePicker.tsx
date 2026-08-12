import { useEffect, useMemo, useState } from "react";

interface ChineseDateTimePickerProps {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  error?: string;
}

interface DateParts {
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
}

const YEARS = range(1901, 2100);
const MONTHS = range(1, 12);
const HOURS = range(0, 23);
const MINUTES = range(0, 59);

export function ChineseDateTimePicker({ value, onChange, disabled, error }: ChineseDateTimePickerProps) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<DateParts>(() => parseValue(value));
  const days = useMemo(() => range(1, daysInMonth(draft.year, draft.month)), [draft.year, draft.month]);

  useEffect(() => {
    if (!open) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      document.body.style.overflow = previous;
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  function update(key: keyof DateParts, next: number) {
    setDraft((current) => {
      const updated = { ...current, [key]: next };
      updated.day = Math.min(updated.day, daysInMonth(updated.year, updated.month));
      return updated;
    });
  }

  function showPicker() {
    setDraft(parseValue(value));
    setOpen(true);
  }

  function confirm() {
    onChange(formatValue(draft));
    setOpen(false);
  }

  return (
    <>
      <button
        type="button"
        className={`date-picker-trigger${value ? " has-value" : ""}`}
        onClick={showPicker}
        disabled={disabled}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-invalid={Boolean(error)}
      >
        <span>{value ? formatChinese(value) : "请选择出生日期与时间"}</span>
        <i aria-hidden="true">日历</i>
      </button>

      {open && (
        <div className="modal-backdrop picker-backdrop" role="presentation" onMouseDown={(event) => {
          if (event.target === event.currentTarget) setOpen(false);
        }}>
          <section className="bottom-sheet date-picker-sheet" role="dialog" aria-modal="true" aria-labelledby="date-picker-title">
            <header className="sheet-header">
              <button type="button" onClick={() => setOpen(false)}>取消</button>
              <div>
                <h3 id="date-picker-title">选择出生时间</h3>
                <p>当地钟表时间，精确到分钟</p>
              </div>
              <button type="button" className="sheet-confirm" onClick={confirm}>确定</button>
            </header>
            <div className="picker-summary" aria-live="polite">{formatChinese(formatValue(draft))}</div>
            <div className="picker-grid">
              <PickerSelect label="年" value={draft.year} options={YEARS} onChange={(next) => update("year", next)} />
              <PickerSelect label="月" value={draft.month} options={MONTHS} onChange={(next) => update("month", next)} />
              <PickerSelect label="日" value={draft.day} options={days} onChange={(next) => update("day", next)} />
              <PickerSelect label="时" value={draft.hour} options={HOURS} onChange={(next) => update("hour", next)} pad />
              <PickerSelect label="分" value={draft.minute} options={MINUTES} onChange={(next) => update("minute", next)} pad />
            </div>
            <p className="picker-range">支持 1901年1月1日 00:00 至 2100年12月31日 23:59</p>
          </section>
        </div>
      )}
    </>
  );
}

function PickerSelect({
  label,
  value,
  options,
  onChange,
  pad = false,
}: {
  label: string;
  value: number;
  options: number[];
  onChange: (value: number) => void;
  pad?: boolean;
}) {
  return (
    <label className="picker-column">
      <span>{label}</span>
      <select aria-label={label} value={value} onChange={(event) => onChange(Number(event.target.value))}>
        {options.map((option) => <option key={option} value={option}>{pad ? String(option).padStart(2, "0") : option}</option>)}
      </select>
    </label>
  );
}

function parseValue(value: string): DateParts {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(value);
  if (!match) return { year: 1990, month: 1, day: 1, hour: 12, minute: 0 };
  return {
    year: Number(match[1]),
    month: Number(match[2]),
    day: Number(match[3]),
    hour: Number(match[4]),
    minute: Number(match[5]),
  };
}

function formatValue(parts: DateParts) {
  return `${parts.year}-${pad(parts.month)}-${pad(parts.day)}T${pad(parts.hour)}:${pad(parts.minute)}`;
}

function formatChinese(value: string) {
  const parts = parseValue(value);
  return `${parts.year}年${parts.month}月${parts.day}日 ${pad(parts.hour)}:${pad(parts.minute)}`;
}

function daysInMonth(year: number, month: number) {
  return new Date(year, month, 0).getDate();
}

function range(start: number, end: number) {
  return Array.from({ length: end - start + 1 }, (_, index) => start + index);
}

function pad(value: number) {
  return String(value).padStart(2, "0");
}
