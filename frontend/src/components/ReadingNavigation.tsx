import { useBackDismiss } from "../customerNavigation";
import { useCallback, useEffect, useRef, useState } from "react";

interface Topic { code: string; title: string }
const scrollBehavior = () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? "auto" as const : "smooth" as const;

function DirectorySheet({ sections, currentCode, onClose, onSelect }: { sections: Topic[]; currentCode: string; onClose: () => void; onSelect: (code: string) => void }) {
  useBackDismiss(true, onClose);
  const sheet = useRef<HTMLElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    sheet.current?.querySelector<HTMLButtonElement>("button")?.focus();
    const keydown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
      if (event.key !== "Tab") return;
      const buttons = [...(sheet.current?.querySelectorAll<HTMLButtonElement>("button") || [])];
      const first = buttons[0], last = buttons[buttons.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    };
    window.addEventListener("keydown", keydown);
    return () => { document.body.style.overflow = overflow; window.removeEventListener("keydown", keydown); previous?.focus({ preventScroll: true }); };
  }, [onClose]);
  return <div className="modal-backdrop reading-menu-backdrop" onClick={event => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="reading-menu" ref={sheet} role="dialog" aria-modal="true" aria-labelledby="reading-menu-title">
      <header><h3 id="reading-menu-title">阅读目录</h3><button type="button" onClick={onClose} aria-label="关闭阅读目录">×</button></header>
      <nav aria-label="选择解读板块">{sections.map((section, index) => <button key={section.code} type="button" aria-current={currentCode === section.code ? "location" : undefined} onClick={() => onSelect(section.code)}><span>{String(index + 1).padStart(2, "0")}</span>{section.title}</button>)}</nav>
    </section>
  </div>;
}

export function ReadingNavigation({ sections, active }: { sections: Topic[]; active: boolean }) {
  const directory = useRef<HTMLElement>(null);
  const [floating, setFloating] = useState(false);
  const [open, setOpen] = useState(false);
  const [currentCode, setCurrentCode] = useState(sections[0]?.code || "");
  const sectionCodes = sections.map(section => section.code).join("|");
  const closeMenu = useCallback(() => setOpen(false), []);
  useEffect(() => {
    if (!active) { setFloating(false); setOpen(false); return; }
    const update = () => {
      setFloating((directory.current?.getBoundingClientRect().bottom ?? 0) < 0);
      let current = sections[0]?.code || "";
      const readingLine = Math.max(80, Math.min(160, window.innerHeight * .25));
      for (const section of sections) {
        const element = document.getElementById(`reading-${section.code}`);
        if (element && element.getBoundingClientRect().top <= readingLine) current = section.code;
      }
      setCurrentCode(current);
    };
    update();
    window.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update);
    return () => { window.removeEventListener("scroll", update); window.removeEventListener("resize", update); };
  }, [active, sectionCodes]);
  function select(code: string) {
    setOpen(false);
    setCurrentCode(code);
    // Close the sheet and release the body scroll lock before moving the page.
    window.requestAnimationFrame(() => {
      const target = document.getElementById(`reading-${code}`);
      target?.scrollIntoView?.({ behavior: scrollBehavior(), block: "start" });
      target?.querySelector<HTMLElement>("h4")?.focus({ preventScroll: true });
    });
  }
  return <>
    <nav className="reading-directory" aria-label="解读目录" ref={directory}>
      {sections.map((section, index) => <a key={section.code} href={`#reading-${section.code}`} aria-current={currentCode === section.code ? "location" : undefined} onClick={event => { event.preventDefault(); select(section.code); }}><span>{String(index + 1).padStart(2, "0")}</span>{section.title.split("与")[0]}</a>)}
    </nav>
    {active && floating && <div className="reading-shortcuts" role="group" aria-label="阅读快捷操作">
      <button type="button" onClick={() => setOpen(true)} aria-haspopup="dialog" aria-expanded={open}>目录</button>
      <button type="button" aria-label="返回顶部" onClick={() => window.scrollTo({ top: 0, behavior: scrollBehavior() })}><span aria-hidden="true">↑</span>顶部</button>
    </div>}
    {active && open && <DirectorySheet sections={sections} currentCode={currentCode} onClose={closeMenu} onSelect={select} />}
  </>;
}
