import { useEffect } from "react";

export function useMobileViewport() {
  useEffect(() => {
    const viewport = window.visualViewport;
    const updateHeight = () => {
      const height = viewport?.height ?? window.innerHeight;
      document.documentElement.style.setProperty("--app-height", `${Math.round(height)}px`);
      document.documentElement.style.setProperty("--keyboard-offset", `${Math.max(0, window.innerHeight - height)}px`);
    };
    const revealFocusedControl = (event: FocusEvent) => {
      const target = event.target;
      if (
        !(target instanceof HTMLElement) ||
        !target.matches('input:not([type="checkbox"]):not([type="radio"]), textarea') ||
        target.closest(".modal-backdrop")
      ) return;
      window.setTimeout(() => target.scrollIntoView?.({ block: "center", behavior: "smooth" }), 280);
    };

    updateHeight();
    viewport?.addEventListener("resize", updateHeight);
    viewport?.addEventListener("scroll", updateHeight);
    window.addEventListener("resize", updateHeight);
    document.addEventListener("focusin", revealFocusedControl);
    return () => {
      viewport?.removeEventListener("resize", updateHeight);
      viewport?.removeEventListener("scroll", updateHeight);
      window.removeEventListener("resize", updateHeight);
      document.removeEventListener("focusin", revealFocusedControl);
    };
  }, []);
}
