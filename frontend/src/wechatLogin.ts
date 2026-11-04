import type { AuthState } from "./types";

const AUTO_LOGIN_KEY = "bazi.wechat.auto-login.v1";

export function shouldAutoLogin(auth: AuthState, userAgent = navigator.userAgent): boolean {
  if (!auth.enabled || auth.authenticated || !/MicroMessenger/i.test(userAgent)) return false;
  try {
    // One redirect per tab until successful login; blocked cookies cannot cause a loop.
    if (sessionStorage.getItem(AUTO_LOGIN_KEY)) return false;
    sessionStorage.setItem(AUTO_LOGIN_KEY, "attempted");
    return true;
  } catch { return false; }
}

export function completeWechatLogin() {
  try { sessionStorage.removeItem(AUTO_LOGIN_KEY); } catch { /* Manual login remains available. */ }
}

export function pauseAutoLogin() {
  try { sessionStorage.setItem(AUTO_LOGIN_KEY, "logged-out"); } catch { /* No redirect without storage. */ }
}

export function beginWechatLogin(automatic = false) {
  const returnTo = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  const query = new URLSearchParams({ return_to: returnTo });
  if (automatic) query.set("scope", "snsapi_base");
  window.location.assign(`/api/v1/auth/wechat/start?${query}`);
}
