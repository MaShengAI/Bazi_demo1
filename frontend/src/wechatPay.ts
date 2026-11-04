interface PayResult { err_msg: string }
interface PayBridge {
  invoke(name: string, parameters: Record<string, string>, callback: (result: PayResult) => void): void;
}

declare global {
  interface Window { WeixinJSBridge?: PayBridge }
}

export function paymentAttemptKey(): string {
  // getRandomValues is supported by older WeChat WebViews that lack randomUUID.
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  return Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
}

export async function invokeWeChatPay(parameters: Record<string, string>): Promise<void> {
  if (!/MicroMessenger/i.test(navigator.userAgent)) {
    throw new Error("请在手机微信内打开本站后支付。");
  }
  if (!window.WeixinJSBridge) {
    await new Promise<void>((resolve, reject) => {
      const ready = () => {
        window.clearTimeout(timer);
        document.removeEventListener("WeixinJSBridgeReady", ready);
        resolve();
      };
      const timer = window.setTimeout(() => {
        document.removeEventListener("WeixinJSBridgeReady", ready);
        reject(new Error("微信支付尚未就绪，请重新打开页面后继续原订单。"));
      }, 10000);
      document.addEventListener("WeixinJSBridgeReady", ready);
    });
  }
  return new Promise<void>((resolve, reject) => {
    const timer = window.setTimeout(() => reject(new Error("支付结果尚未确认，请稍后重新打开购买页确认状态，勿重复购买。")), 120000);
    if (!window.WeixinJSBridge) {
      window.clearTimeout(timer);
      reject(new Error("微信支付不可用，请稍后重试。"));
      return;
    }
    try { window.WeixinJSBridge.invoke("getBrandWCPayRequest", parameters, (result) => {
      window.clearTimeout(timer);
      if (result.err_msg === "get_brand_wcpay_request:ok") resolve();
      else if (result.err_msg === "get_brand_wcpay_request:cancel") reject(new Error("已取消收银台支付，订单仍待支付；可继续支付或关闭订单释放优惠券。"));
      else reject(new Error("收银台未确认支付，请稍后重新打开购买页确认状态，勿重复购买。"));
    }); } catch {
      window.clearTimeout(timer);
      reject(new Error("无法调起微信支付，请重新打开原订单。"));
    }
  });
}
