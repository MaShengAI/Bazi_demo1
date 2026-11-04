import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { waitFor } from "@testing-library/react";
import { CustomerNavigation } from "./customerNavigation";

let navigation: CustomerNavigation;
let dispose: () => void;
beforeEach(() => {
  history.replaceState(null, "", "/#/reports");
  Object.defineProperty(document.documentElement, "scrollHeight", { configurable: true, value: 10000 });
  navigation = new CustomerNavigation(); dispose = navigation.mount(vi.fn());
});
afterEach(() => dispose());
const at = (hash: string) => waitFor(() => expect(location.hash).toBe(hash));

test("top tabs replace the root rather than accumulating history", () => {
  const length = history.length;
  navigation.tab("#/me"); navigation.tab("#/measure"); navigation.tab("#/reports");
  expect(history.length).toBe(length);
  expect(location.hash).toBe("#/reports");
});

test("header and native back follow the source page and keep scroll positions", async () => {
  Object.defineProperty(window, "scrollY", { configurable: true, value: 420 });
  navigation.go("#/report/test");
  Object.defineProperty(window, "scrollY", { configurable: true, value: 1800 });
  navigation.go("#/review/test");
  const scroll = vi.spyOn(window, "scrollTo");
  navigation.back("#/reports"); await at("#/report/test");
  await waitFor(() => expect(scroll).toHaveBeenCalledWith({ top: 1800, behavior: "instant" }));
  history.back(); await at("#/reports");
  await waitFor(() => expect(scroll).toHaveBeenCalledWith({ top: 420, behavior: "instant" }));
});

test("unlock redirects replace the locked chart and cannot bounce back to it", async () => {
  navigation.go("#/chart/test"); navigation.go("#/report/test", true);
  history.back(); await at("#/reports");
});

test("switching tabs from a child removes its branch from the active back stack", async () => {
  navigation.go("#/report/test"); navigation.go("#/review/test");
  navigation.tab("#/me"); await at("#/me");
  navigation.go("#/coupon"); navigation.back("#/me"); await at("#/me");
  expect(history.state.baziCustomerNavigation.parents).toEqual([]);
});

test("direct links have a safe parent fallback without leaving the website", () => {
  navigation.back("#/me"); expect(location.hash).toBe("#/me");
  expect(history.state.baziCustomerNavigation.parents).toEqual([]);
});

test("native Back closes a sheet first; closing via its button consumes the same entry", async () => {
  navigation.go("#/report/test"); const close = vi.fn();
  const cleanup = navigation.sheet(close, () => false);
  history.back(); await waitFor(() => expect(close).toHaveBeenCalledTimes(1));
  expect(location.hash).toBe("#/report/test"); cleanup();
  navigation.back("#/reports"); await at("#/reports");
  const close2 = vi.fn(); const cleanup2 = navigation.sheet(close2, () => false);
  cleanup2(); await waitFor(() => expect(history.state.baziCustomerNavigation.overlay).toBeUndefined());
  expect(close2).not.toHaveBeenCalled(); expect(location.hash).toBe("#/reports");
});

test("an in-flight operation cannot be dismissed by native Back", async () => {
  let blocked = true; const close = vi.fn(); const cleanup = navigation.sheet(close, () => blocked);
  history.back(); await new Promise(resolve => setTimeout(resolve, 30));
  expect(close).not.toHaveBeenCalled(); expect(history.state.baziCustomerNavigation.overlay).toBeTruthy();
  blocked = false; history.back(); await waitFor(() => expect(close).toHaveBeenCalledOnce()); cleanup();
});
