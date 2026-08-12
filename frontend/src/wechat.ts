import { WECHAT_JS_SDK_ENABLED } from "./config";

/**
 * 微信 JS-SDK 的边界定义。当前版本不加载 SDK、不请求签名，也不持有 AppID。
 * 后续接入时，签名只能由同源后端生成，前端不得保存 AppSecret。
 */
export const WECHAT_JS_SDK_SIGNATURE_PATH = "/api/v1/wechat/js-sdk-signature";

export interface WeChatSharePayload {
  title: string;
  description: string;
  link: string;
  imageUrl: string;
}

export interface WeChatSdkAdapter {
  configureForUrl(url: string): Promise<void>;
  setSharePayload(payload: WeChatSharePayload): Promise<void>;
}

export function isWeChatWebView(userAgent = navigator.userAgent) {
  return /MicroMessenger/i.test(userAgent);
}

export function getWeChatIntegrationState() {
  return {
    isWeChat: isWeChatWebView(),
    sdkEnabled: WECHAT_JS_SDK_ENABLED,
    signaturePath: WECHAT_JS_SDK_SIGNATURE_PATH,
  };
}
