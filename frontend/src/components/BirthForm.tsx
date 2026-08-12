import { useEffect, useState } from "react";
import { api } from "../api";
import type { ChartRequest, City, Province } from "../types";
import { ChineseDateTimePicker } from "./ChineseDateTimePicker";

interface BirthFormProps {
  busy: "chart" | "analysis" | null;
  onSubmit: (payload: ChartRequest, mode: "chart" | "analysis") => void;
}

export function BirthForm({ busy, onSubmit }: BirthFormProps) {
  const [provinces, setProvinces] = useState<Province[]>([]);
  const [cities, setCities] = useState<City[]>([]);
  const [province, setProvince] = useState("");
  const [cityCode, setCityCode] = useState("");
  const [locationsBusy, setLocationsBusy] = useState(true);
  const [locationError, setLocationError] = useState("");
  const [birthDateTime, setBirthDateTime] = useState("");
  const [formError, setFormError] = useState("");

  useEffect(() => {
    let active = true;
    setLocationsBusy(true);
    api
      .provinces()
      .then((items) => {
        if (active) setProvinces(items);
      })
      .catch((error: Error) => {
        if (active) setLocationError(error.message);
      })
      .finally(() => {
        if (active) setLocationsBusy(false);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!province) {
      setCities([]);
      setCityCode("");
      return;
    }
    let active = true;
    setLocationsBusy(true);
    setLocationError("");
    setCityCode("");
    api
      .cities(province)
      .then((items) => {
        if (active) setCities(items);
      })
      .catch((error: Error) => {
        if (active) setLocationError(error.message);
      })
      .finally(() => {
        if (active) setLocationsBusy(false);
      });
    return () => {
      active = false;
    };
  }, [province]);

  function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!birthDateTime) {
      setFormError("请选择完整的出生日期与时间。");
      return;
    }
    const form = new FormData(event.currentTarget);
    const action = (event.nativeEvent as SubmitEvent).submitter as HTMLButtonElement | null;
    const payload: ChartRequest = {
      name: String(form.get("name") || "").trim() || undefined,
      gender: form.get("gender") as "male" | "female",
      birth_local_datetime: birthDateTime,
      location_id: Number(form.get("location_id")),
    };
    onSubmit(payload, action?.value === "analysis" ? "analysis" : "chart");
  }

  return (
    <section className="birth-card" aria-labelledby="birth-title">
      <div className="section-kicker">出生资料</div>
      <div className="section-heading-row">
        <div>
          <h2 id="birth-title">起一张你的命盘</h2>
          <p>时间以出生地当时的当地钟表时间填写，精确到分钟。</p>
        </div>
        <span className="privacy-note">仅提交排盘必需信息</span>
      </div>

      <form onSubmit={submit} className="birth-form">
        <label className="field field-name">
          <span>姓名 <small>选填</small></span>
          <input name="name" autoComplete="name" maxLength={100} placeholder="如何称呼你" />
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
          <span>出生日期时间</span>
          <ChineseDateTimePicker
            value={birthDateTime}
            onChange={(value) => {
              setBirthDateTime(value);
              setFormError("");
            }}
            disabled={busy !== null}
            error={formError}
          />
        </div>

        <label className="field field-province">
          <span>出生省份</span>
          <select
            aria-label="出生省份"
            value={province}
            onChange={(event) => setProvince(event.target.value)}
            disabled={!provinces.length && locationsBusy}
            required
          >
            <option value="">{locationsBusy && !provinces.length ? "正在载入…" : "请选择省份"}</option>
            {provinces.map((item) => (
              <option key={item.code || item.name} value={item.name}>
                {item.name}
              </option>
            ))}
          </select>
        </label>

        <label className="field field-city">
          <span>出生城市</span>
          <select
            aria-label="出生城市"
            name="location_id"
            value={cityCode}
            onChange={(event) => setCityCode(event.target.value)}
            disabled={!province || locationsBusy}
            required
          >
            <option value="">{locationsBusy && province ? "正在载入…" : "请选择城市"}</option>
            {cities.map((item) => (
              <option key={item.code} value={item.code}>
                {item.name}
              </option>
            ))}
          </select>
        </label>

        {(locationError || formError) && <p className="inline-error form-wide" role="alert">{locationError || formError}</p>}

        <div className="privacy-consent form-wide">
          <label>
            <input type="checkbox" name="privacy_consent" required />
            <span>我已阅读并同意出生信息和 AI 分析数据的处理说明</span>
          </label>
          <details>
            <summary>查看处理说明</summary>
            <p>出生信息用于后端排盘；选择 AI 分析时，后端只向模型发送经过裁剪的命盘事实，不发送姓名、经纬度、模型密钥或数据库密码。你可以随时删除分析，或删除出生信息及全部关联记录。</p>
          </details>
        </div>

        <div className="form-actions form-wide">
          <button className="button button-primary" type="submit" value="chart" disabled={busy !== null}>
            {busy === "chart" ? <span className="spinner" aria-hidden="true" /> : null}
            {busy === "chart" ? "正在排盘" : "开始排盘"}
          </button>
          <button className="button button-ai" type="submit" value="analysis" disabled={busy !== null}>
            {busy === "analysis" ? <span className="spinner" aria-hidden="true" /> : <span aria-hidden="true">✦</span>}
            {busy === "analysis" ? "正在创建" : "排盘并生成 AI 分析"}
          </button>
        </div>
      </form>
    </section>
  );
}
