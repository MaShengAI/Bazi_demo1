import { nextPollingDelay } from "./polling";

test("弱网轮询使用指数退避并封顶30秒", () => {
  expect([1, 2, 3, 4, 5, 6].map(nextPollingDelay)).toEqual([2000, 4000, 8000, 16000, 30000, 30000]);
});
