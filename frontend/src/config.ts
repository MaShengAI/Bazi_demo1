export const APP_VERSION = __APP_VERSION__;
export const WECHAT_JS_SDK_ENABLED = import.meta.env.VITE_WECHAT_JS_SDK_ENABLED === "true";

export const NETWORK_TIMEOUTS = {
  read: 12_000,
  write: 30_000,
} as const;
