import { createContext, useContext, useEffect, useRef } from "react";

type Point = { key: string; path: string; y: number };
type Entry = Point & { version: 1; parents: Point[]; overlay?: string };
const stateKey = "baziCustomerNavigation";
const key = () => `${Date.now()}-${Math.random().toString(36).slice(2)}`;
const path = () => window.location.hash || "#/measure";
const point = (entry: Entry): Point => ({ key: entry.key, path: entry.path, y: entry.y });
const read = (): Entry | null => {
  const value = history.state?.[stateKey];
  return value?.version === 1 && Array.isArray(value.parents) && value.path === path() ? value : null;
};

/** One same-tab history stack for header Back, native Back and nested sheets. */
export class CustomerNavigation {
  private current!: Entry;
  private notify = () => {};
  private positions = new Map<string, number>();
  private pagePositions = new Map<string, number>();
  private cancelRestore = () => {};
  private pending: (() => void) | null = null;
  private travelling = false;
  private overlay: { token: string; close: () => void; blocked: () => boolean } | null = null;
  private mounted = false;

  mount(notify: () => void) {
    this.notify = notify;
    this.mounted = true;
    this.current = read() || this.fresh(path(), []);
    this.write(this.current, true);
    const oldRestoration = history.scrollRestoration;
    history.scrollRestoration = "manual";
    window.addEventListener("popstate", this.popped);
    window.addEventListener("hashchange", this.hashChanged);
    window.addEventListener("pagehide", this.save);
    return () => {
      this.mounted = false;
      this.cancelRestore();
      window.removeEventListener("popstate", this.popped);
      window.removeEventListener("hashchange", this.hashChanged);
      window.removeEventListener("pagehide", this.save);
      history.scrollRestoration = oldRestoration;
    };
  }

  private fresh(target: string, parents: Point[]): Entry {
    return { version: 1, key: key(), path: target, y: 0, parents };
  }
  private write(entry: Entry, replace: boolean) {
    history[replace ? "replaceState" : "pushState"]({ ...history.state, [stateKey]: entry }, "", entry.path);
    this.current = entry;
  }
  private remember() {
    this.current.y = window.scrollY;
    this.positions.set(this.current.key, window.scrollY);
    this.pagePositions.set(this.current.path, window.scrollY);
  }
  private save = () => {
    this.remember(); this.write(this.current, true);
  };
  private changed(y: number) {
    this.notify(); this.restore(y);
  }
  private restore(y: number) {
    this.cancelRestore();
    let timer: ReturnType<typeof setTimeout>;
    let stopped = false;
    const stop = () => {
      stopped = true; clearTimeout(timer);
      for (const event of ["touchstart", "wheel", "pointerdown", "keydown"]) window.removeEventListener(event, stop);
    };
    this.cancelRestore = stop;
    for (const event of ["touchstart", "wheel", "pointerdown", "keydown"]) window.addEventListener(event, stop, { passive: true });
    const end = Date.now() + 8000;
    const attempt = () => {
      if (stopped || !this.mounted) return;
      const available = document.documentElement.scrollHeight - window.innerHeight;
      window.scrollTo({ top: Math.min(y, Math.max(0, available)), behavior: "instant" });
      if (available >= y || Date.now() >= end) { stop(); return; }
      timer = setTimeout(attempt, 50);
    };
    timer = setTimeout(attempt, 0);
  }

  go(target: string, replace = false) {
    if (!this.mounted || this.travelling || target === this.current.path) return;
    if (this.overlay) { this.afterSheet(() => this.go(target, replace)); return; }
    this.save();
    this.write(this.fresh(target, replace ? this.current.parents : [...this.current.parents, point(this.current)]), replace);
    this.changed(0);
  }
  tab(target: string) {
    if (!this.mounted || this.travelling) return;
    if (this.overlay) { this.afterSheet(() => this.tab(target)); return; }
    if (this.current.path === target && !this.current.parents.length) return;
    this.save();
    const replaceRoot = () => {
      this.write(this.fresh(target, []), true);
      this.changed(this.pagePositions.get(target) || 0);
    };
    if (this.current.parents.length) {
      this.pending = replaceRoot; this.travelling = true;
      history.go(-this.current.parents.length);
    } else replaceRoot();
  }
  back(fallback: string) {
    if (!this.mounted || this.travelling) return;
    this.save();
    if (this.current.parents.length) { this.travelling = true; history.back(); }
    else this.go(fallback, true);
  }

  sheet(close: () => void, blocked: () => boolean) {
    if (!this.mounted || this.travelling) return () => {};
    this.save();
    const token = key();
    this.overlay = { token, close, blocked };
    this.write({ ...this.fresh(this.current.path, [...this.current.parents, point(this.current)]), y: window.scrollY, overlay: token }, false);
    return () => {
      if (this.overlay?.token !== token) return;
      this.overlay = null;
      if (this.mounted && this.current.overlay === token && !this.travelling) {
        this.travelling = true; history.back();
      }
    };
  }
  private afterSheet(action: () => void) {
    if (!this.overlay || this.overlay.blocked()) return;
    const sheet = this.overlay; this.overlay = null; this.pending = action;
    sheet.close(); this.travelling = true; history.back();
  }
  private popped = () => {
    const incoming = read();
    if (incoming?.key === this.current.key) return;
    this.remember();
    if (this.overlay?.blocked()) {
      // Keep the same operation visible while a destructive/payment write runs.
      this.write(this.current, false); this.travelling = false; return;
    }
    const sheet = this.overlay; this.overlay = null;
    const previousPath = this.current.path;
    this.current = incoming || this.fresh(path(), []);
    this.travelling = false;
    sheet?.close();
    if (this.pending) { const next = this.pending; this.pending = null; next(); return; }
    // A closed sheet in browser Forward history must never become a phantom modal.
    if (this.current.overlay) {
      const parent = this.current.parents.at(-1);
      this.current = { ...this.current, key: parent?.key || key(), parents: this.current.parents.slice(0, -1), overlay: undefined };
      this.write(this.current, true);
    }
    if (previousPath !== this.current.path) this.changed(this.positions.get(this.current.key) ?? this.current.y);
  };
  private hashChanged = () => {
    if (path() === this.current.path) return;
    // Handle external hash links without treating native Back as a fresh visit.
    if (read()) { this.popped(); return; }
    this.remember();
    this.write(this.fresh(path(), [...this.current.parents, point(this.current)]), true);
    this.changed(0);
  };
}

export const CustomerNavigationContext = createContext<CustomerNavigation | null>(null);
export function useBackDismiss(open: boolean, onClose: () => void, blocked = false) {
  const navigation = useContext(CustomerNavigationContext);
  const latest = useRef({ onClose, blocked }); latest.current = { onClose, blocked };
  useEffect(() => {
    if (open && navigation) return navigation.sheet(() => latest.current.onClose(), () => latest.current.blocked);
  }, [open, navigation]);
}
