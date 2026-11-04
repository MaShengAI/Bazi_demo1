import { useEffect, useMemo, useState } from "react";
import { flushSync } from "react-dom";
import { PickerSheet, WheelPicker } from "./WheelPicker";
import { LUNAR_YEARS, lunarDayLabel, lunarMonthLabel, lunarToSolar, selectableLunarDays, selectableLunarMonths, solarToLunar } from "../calendar";

interface ChineseDateTimePickerProps {
  value: string;
  onChange: (value: string, calendar: "solar" | "lunar") => void;
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
  const [mode, setMode] = useState<"solar" | "lunar">("solar");
  const [savedMode, setSavedMode] = useState<"solar" | "lunar">("solar");
  const months = useMemo(() => mode === "solar" ? MONTHS : selectableLunarMonths(draft.year).map(item => item.month), [mode, draft.year]);
  const days = useMemo(() => mode === "solar" ? range(1, daysInMonth(draft.year, draft.month)) : selectableLunarDays(draft.year, draft.month), [mode, draft.year, draft.month]);

  useEffect(() => { if (disabled) setOpen(false); }, [disabled]);

  function update(key: keyof DateParts, next: number) {
    setDraft((current) => {
      const updated = { ...current, [key]: next };
      if (mode === "lunar") {
        const available = selectableLunarMonths(updated.year).map(item => item.month);
        if (!available.includes(updated.month)) updated.month = available.includes(Math.abs(updated.month)) ? Math.abs(updated.month) : available[0];
        const validDays = selectableLunarDays(updated.year, updated.month);
        updated.day = Math.max(validDays[0], Math.min(updated.day, validDays[validDays.length - 1]));
      } else updated.day = Math.min(updated.day, daysInMonth(updated.year, updated.month));
      return updated;
    });
  }

  function showPicker() {
    const solar = parseValue(value);
    setMode(savedMode);
    setDraft(savedMode === "lunar" ? { ...solar, ...solarToLunar(solar) } : solar);
    setOpen(true);
  }

  function confirm() {
    const solar = mode === "lunar" ? { ...draft, ...lunarToSolar(draft) } : draft;
    onChange(formatValue(solar), mode);
    setSavedMode(mode);
    setOpen(false);
  }

  function switchMode(next: "solar" | "lunar") {
    if (next === mode) return;
    flushSync(() => window.dispatchEvent(new Event("commit-picker-wheels")));
    setDraft(current => ({ ...current, ...(next === "lunar" ? solarToLunar(current) : lunarToSolar(current)) }));
    setMode(next);
  }
  const lunarLabel = (parts: DateParts) => `农历 ${parts.year}年${lunarMonthLabel(parts.month)}${lunarDayLabel(parts.day)} ${pad(parts.hour)}:${pad(parts.minute)}`;
  const triggerText = value && savedMode === "lunar" ? lunarLabel({ ...parseValue(value), ...solarToLunar(parseValue(value)) }) : value ? formatChinese(value) : "请选择出生日期";
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
        <span>{triggerText}</span>
      </button>

      {open && <PickerSheet title="请选择出生时间" onClose={() => setOpen(false)} onConfirm={confirm}>
        <div className="plum-calendar-switch" role="group" aria-label="历法">
          <button type="button" aria-pressed={mode === "solar"} onClick={() => switchMode("solar")}>公历</button>
          <button type="button" aria-pressed={mode === "lunar"} onClick={() => switchMode("lunar")}>农历</button>
        </div>
        <div className="plum-date-wheels">
          {([['year', '年', mode === 'solar' ? YEARS : LUNAR_YEARS], ['month', '月', months], ['day', '日', days], ['hour', '时', HOURS], ['minute', '分', MINUTES]] as const).map(([key, label, values]) =>
            <WheelPicker key={key} label={label} value={String(draft[key])} options={values.map(n => ({ value: String(n), label: mode === 'lunar' && key === 'month' ? lunarMonthLabel(n) : mode === 'lunar' && key === 'day' ? lunarDayLabel(n) : `${key === 'hour' || key === 'minute' ? pad(n) : n}${label}` }))} onChange={value => update(key, Number(value))} />)}
        </div>
      </PickerSheet>}
    </>
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
