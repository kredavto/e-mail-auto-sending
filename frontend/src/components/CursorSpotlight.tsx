import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";

// Interface surfaces only; never alter the email canvas or its preview.
const surfaces = ".studio-intro, .studio-sidebar, .bg-ink, .button.primary";

export function CursorSpotlight({ active }: { active: boolean }) {
  const spotlight = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const light = spotlight.current;
    if (!light || !active) return;
    let frame = 0, x = 0, y = 0;
    let hasPointer = false;
    const hide = () => { light.style.opacity = "0"; };
    const paint = () => {
      frame = 0;
      const hit = hasPointer ? document.elementFromPoint(x, y) : null;
      const surface = hit?.closest<HTMLElement>(surfaces);
      if (!surface || !surface.closest(".premium-shell") || hit?.closest(".email-canvas")) { hide(); return; }
      // Viewport coordinates also track sticky panels and nested scrolling.
      const rect = surface.getBoundingClientRect();
      Object.assign(light.style, {
        left: `${rect.left}px`, top: `${rect.top}px`,
        width: `${rect.width}px`, height: `${rect.height}px`,
        borderRadius: getComputedStyle(surface).borderRadius,
        opacity: "1",
      });
      light.style.setProperty("--light-x", `${x - rect.left}px`);
      light.style.setProperty("--light-y", `${y - rect.top}px`);
    };
    const schedule = () => { if (!frame) frame = requestAnimationFrame(paint); };
    const move = (event: PointerEvent) => {
      hasPointer = event.pointerType === "mouse";
      x = event.clientX; y = event.clientY;
      schedule();
    };
    const leave = () => { hasPointer = false; cancelAnimationFrame(frame); frame = 0; hide(); };
    document.addEventListener("pointermove", move, { passive: true });
    document.documentElement.addEventListener("pointerleave", leave);
    window.addEventListener("blur", leave);
    window.addEventListener("scroll", schedule, { passive: true, capture: true });
    window.addEventListener("resize", schedule);
    return () => {
      leave();
      document.removeEventListener("pointermove", move);
      document.documentElement.removeEventListener("pointerleave", leave);
      window.removeEventListener("blur", leave);
      window.removeEventListener("scroll", schedule, true);
      window.removeEventListener("resize", schedule);
    };
  }, [active]);
  return active ? createPortal(<div ref={spotlight} className="cursor-spotlight" aria-hidden="true" />, document.body) : null;
}
