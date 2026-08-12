import { useCallback, useEffect, useState } from "react";
import { APP_VERSION } from "../config";

export function useVersionCheck() {
  const [updateAvailable, setUpdateAvailable] = useState(false);

  const check = useCallback(async () => {
    if (!navigator.onLine) return;
    try {
      const response = await fetch(`/version.json?t=${Date.now()}`, { cache: "no-store" });
      if (!response.ok) return;
      const data = await response.json() as { version?: string };
      if (data.version && data.version !== APP_VERSION) setUpdateAvailable(true);
    } catch {
      // Version checks must never block chart usage on weak networks.
    }
  }, []);

  useEffect(() => {
    void check();
    const timer = window.setInterval(check, 5 * 60 * 1000);
    const onVisible = () => {
      if (document.visibilityState === "visible") void check();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [check]);

  return {
    updateAvailable,
    refresh: () => window.location.reload(),
  };
}
