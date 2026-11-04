import { useState } from "react";
import type { ChartRequest } from "../types";
import { ChineseDateTimePicker } from "./ChineseDateTimePicker";
import { LocationPicker, type BirthLocation } from "./LocationPicker";

interface BirthFormProps {
  active?: boolean;
  chartOnly?: boolean;
  requireCards?: boolean;
  busy: "chart" | "analysis" | null;
  onSubmit: (payload: ChartRequest, mode: "chart" | "analysis") => void;
}

export function BirthForm({ busy, onSubmit, requireCards = false, chartOnly = false, active = true }: BirthFormProps) {
  const [location, setLocation] = useState<BirthLocation | null>(null);
  const [birthDateTime, setBirthDateTime] = useState("");
  const [birthCalendar, setBirthCalendar] = useState<"solar" | "lunar">("solar");
  const [formError, setFormError] = useState("");

  function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!birthDateTime) {
      setFormError("请选择完整的出生日期与时间。");
      return;
    }
    if (!location) { setFormError("请选择出生地点。"); return; }
    const form = new FormData(event.currentTarget);
    const action = (event.nativeEvent as SubmitEvent).submitter as HTMLButtonElement | null;
    const payload: ChartRequest = {
      name: String(form.get("name") || "").trim() || undefined,
      gender: form.get("gender") as "male" | "female",
      birth_local_datetime: birthDateTime,
      location_id: location.id,
      birth_calendar: birthCalendar,
    };
    onSubmit(payload, action?.value === "analysis" ? "analysis" : "chart");
  }

  return (
    <section className={`birth-card${chartOnly ? " chart-only" : ""}`} aria-labelledby="birth-title">
      {chartOnly ? <h2 id="birth-title" className="sr-only">出生资料</h2> : <>
        <div className="section-kicker">出生资料</div>
        <div className="section-heading-row">
          <div>
            <h2 id="birth-title">起一张你的命盘</h2>
            <p>时间以出生地当时的当地钟表时间填写，精确到分钟。</p>
          </div>
          <span className="privacy-note">仅提交排盘必需信息</span>
        </div>
      </>}

      <form onSubmit={submit} className="birth-form">
        <label className="field field-name">
          <span>姓名</span>
          <input name="name" autoComplete="name" maxLength={100} placeholder="选填" />
        </label>

        <fieldset className="field gender-field">
          <legend>性别</legend>
          <div className="segmented">
            <label>
              <input type="radio" name="gender" value="male" defaultChecked />
              <span>男</span>
            </label>
            <label>
              <input type="radio" name="gender" value="female" />
              <span>女</span>
            </label>
          </div>
        </fieldset>

        <div className="field field-time">
          <span>出生日期</span>
          <ChineseDateTimePicker
            value={birthDateTime}
            onChange={(value, calendar) => {
              setBirthDateTime(value);
              setBirthCalendar(calendar);
              setFormError("");
            }}
            disabled={busy !== null || !active}
            error={formError}
          />
        </div>

        <div className="field field-location form-wide"><span>出生地点</span>
          <LocationPicker value={location} onChange={next => { setLocation(next); setFormError(""); }} disabled={busy !== null || !active} />
        </div>
        {formError && <p className="inline-error form-wide" role="alert">{formError}</p>}

        <div className="privacy-consent form-wide">
          <label>
            <input type="checkbox" name="privacy_consent" required />
            <span>我已阅读并同意<a href="#/privacy">隐私与服务说明</a></span>
          </label>
        </div>

        <div className="form-actions form-wide">
          <button className="button button-primary" type="submit" value="chart" disabled={busy !== null}>
            {busy === "chart" ? <span className="spinner" aria-hidden="true" /> : null}
            {busy === "chart" ? "正在排盘" : "开始排盘"}
          </button>
          {!chartOnly && <button className="button button-ai" type="submit" value="analysis" disabled={busy !== null}>
            {busy === "analysis" ? <span className="spinner" aria-hidden="true" /> : <span aria-hidden="true">✦</span>}
            {busy === "analysis" ? "正在创建" : requireCards ? "生成 AI 分析（新报告扣 1 张卡）" : "排盘并生成 AI 分析"}
          </button>}
        </div>
      </form>
    </section>
  );
}
