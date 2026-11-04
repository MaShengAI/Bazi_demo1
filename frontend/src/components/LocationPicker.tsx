import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { City, Province } from "../types";
import { PickerSheet, WheelPicker } from "./WheelPicker";

export interface BirthLocation { province: string; city: string; id: number }
export function LocationPicker({ value, onChange, disabled }: { value: BirthLocation | null; onChange: (value: BirthLocation) => void; disabled?: boolean }) {
  const [open, setOpen] = useState(false);
  const [provinces, setProvinces] = useState<Province[]>([]);
  const [cities, setCities] = useState<City[]>([]);
  const [province, setProvince] = useState("");
  const [city, setCity] = useState("");
  const [loadedProvince, setLoadedProvince] = useState("");
  const [loading, setLoading] = useState(true);
  const [cityLoading, setCityLoading] = useState(false);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const cityRequests = useRef(new Map<string, Promise<City[]>>());
  useEffect(() => {
    let active = true; setLoading(true); setError("");
    api.provinces().then(items => { if (active) { setProvinces(items); setProvince(current => current || items[0]?.name || ""); } })
      .catch(() => { if (active) setError("出生地点暂时无法读取，请重试。"); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [revision]);
  useEffect(() => { if (disabled) setOpen(false); }, [disabled]);
  useEffect(() => {
    if (!open || !province) return;
    let active = true; setCityLoading(true); setError("");
    let request = cityRequests.current.get(province);
    if (!request) {
      request = api.cities(province).catch(cause => {
        cityRequests.current.delete(province);
        throw cause;
      });
      cityRequests.current.set(province, request);
    }
    request.then(items => {
      if (!active) return;
      setCities(items); setLoadedProvince(province);
      setCity(String(items.find(item => value?.province === province && item.code === value.id)?.code || items[0]?.code || ""));
    }).catch(() => { if (active) setError("城市暂时无法读取，请重试。"); })
      .finally(() => { if (active) setCityLoading(false); });
    return () => { active = false; };
  }, [province, open, revision]);
  const selected = cities.find(item => String(item.code) === city);
  const valid = !cityLoading && loadedProvince === province && !!selected;
  function confirm() {
    if (!valid || !selected) return;
    onChange({ province, city: selected.name, id: selected.code }); setOpen(false);
  }
  return <>
    <button className={`date-picker-trigger location-picker-trigger${value ? " has-value" : ""}`} type="button" aria-haspopup="dialog" aria-expanded={open} disabled={disabled || loading} onClick={() => { setProvince(value?.province || provinces[0]?.name || ""); setOpen(true); }}>
      <span>{loading ? "出生地点正在载入…" : value ? `${value.province} · ${value.city}` : "请选择出生地点"}</span>
    </button>
    {error && !open && <p className="inline-error" role="alert">{error}<button type="button" className="text-button" onClick={() => setRevision(n => n + 1)}>重新读取</button></p>}
    {open && <PickerSheet title="请选择出生地" onClose={() => setOpen(false)} onConfirm={confirm} confirmDisabled={!valid}>
      <div className="plum-location-wheels">
        <WheelPicker label="出生省份" value={province} options={provinces.map(item => ({ value: item.name, label: item.name }))} onChange={setProvince} />
        <div className="location-city-wheel" aria-busy={cityLoading || loadedProvince !== province} inert={cityLoading || loadedProvince !== province}>
          <WheelPicker label="出生城市" value={city} options={cities.map(item => ({ value: String(item.code), label: item.name }))} onChange={setCity} />
        </div>
      </div>
      {error && <p className="plum-picker-error" role="alert">{error}<button type="button" className="text-button" onClick={() => setRevision(n => n + 1)}>重试</button></p>}
      {!cityLoading && !error && loadedProvince === province && !cities.length && <p className="plum-picker-error">该省份暂没有可选城市，请选择其他省份。</p>}
    </PickerSheet>}
  </>;
}
