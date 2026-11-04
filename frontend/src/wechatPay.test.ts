import { afterEach, vi } from "vitest";
import { invokeWeChatPay } from "./wechatPay";

afterEach(() => { delete window.WeixinJSBridge; });

test("普通浏览器不调起 JSAPI 收银台", async () => {
  await expect(invokeWeChatPay({})).rejects.toThrow("请在手机微信内");
});

test("微信成功及取消回调区分处理", async () => {
  vi.spyOn(navigator, "userAgent", "get").mockReturnValue("MicroMessenger/8");
  window.WeixinJSBridge = { invoke: vi.fn((_, params, callback) => {
    expect(params.package).toBe("prepay_id=test");
    callback({ err_msg: "get_brand_wcpay_request:ok" });
  }) };
  await expect(invokeWeChatPay({ package: "prepay_id=test" })).resolves.toBeUndefined();
  window.WeixinJSBridge = { invoke: (_, __, callback) => callback({ err_msg: "get_brand_wcpay_request:cancel" }) };
  await expect(invokeWeChatPay({})).rejects.toThrow("已取消收银台支付");
});

test("JSBridge 等待有超时，不会永久卡住页面", async () => {
  vi.useFakeTimers();
  vi.spyOn(navigator, "userAgent", "get").mockReturnValue("MicroMessenger/8");
  const attempt = expect(invokeWeChatPay({})).rejects.toThrow("尚未就绪");
  await vi.advanceTimersByTimeAsync(10000);
  await attempt;
});
