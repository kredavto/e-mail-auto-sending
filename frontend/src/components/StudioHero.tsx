import { useEffect, useRef, useState } from "react";

function storedMotion() { try { return localStorage.getItem("studio-motion") !== "off"; } catch { return true; } }

export function StudioHero({ onStudio }: { onStudio: () => void }) {
  const hero = useRef<HTMLElement>(null);
  const [motion, setMotion] = useState(storedMotion);
  const [reduced, setReduced] = useState(() => window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  useEffect(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduced(query.matches);
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);
  const active = motion && !reduced;
  useEffect(() => {
    const element = hero.current;
    if (!element) return;
    // Passive events + one frame per input burst; no render loop or React updates on scroll.
    if (!active || !window.matchMedia("(pointer: fine)").matches) {
      element.style.setProperty("--parallax-x", "0px"); element.style.setProperty("--parallax-y", "0px"); return;
    }
    let frame = 0, x = 0, y = 0;
    const paint = () => { frame = 0; const rect = element.getBoundingClientRect(); if (rect.bottom < 0) return; element.style.setProperty("--parallax-x", `${x}px`); element.style.setProperty("--parallax-y", `${y + Math.min(window.scrollY, 700) * .08}px`); };
    const schedule = () => { if (!frame) frame = requestAnimationFrame(paint); };
    const pointer = (event: PointerEvent) => { const rect = element.getBoundingClientRect(); x = ((event.clientX - rect.left) / rect.width - .5) * 22; y = ((event.clientY - rect.top) / rect.height - .5) * 16; schedule(); };
    const leave = () => { x = 0; y = 0; schedule(); };
    element.addEventListener("pointermove", pointer, { passive: true });
    element.addEventListener("pointerleave", leave, { passive: true });
    window.addEventListener("scroll", schedule, { passive: true });
    schedule();
    return () => { cancelAnimationFrame(frame); element.removeEventListener("pointermove", pointer); element.removeEventListener("pointerleave", leave); window.removeEventListener("scroll", schedule); };
  }, [active]);
  function toggleMotion() { const next = !motion; setMotion(next); try { localStorage.setItem("studio-motion", next ? "on" : "off"); } catch { /* Optional preference; work without storage too. */ } }
  return <div className="studio-intro" data-motion={active ? "on" : "off"}>
    <div className="studio-topbar">
      <a className="studio-brand" href="#studio" onClick={onStudio} aria-label="Premium B2B Mailer — открыть студию"><span className="brand-mark" aria-hidden="true">M<span /></span><span>PREMIUM<span className="brand-subtitle">B2B MAILER</span></span></a>
      <div className="topbar-end"><span className="topbar-note">Деловая переписка. Новый уровень.</span><button type="button" className="motion-toggle" onClick={toggleMotion} disabled={reduced} aria-pressed={active} aria-label="Анимация интерфейса" title={reduced ? "Движение отключено в настройках устройства" : "Включить или выключить анимацию"}><span aria-hidden="true">{active ? "◉" : "○"}</span> {active ? "Моушн вкл." : "Без движения"}</button></div>
    </div>
    <header ref={hero} className="studio-hero">
      <div className="hero-glow" aria-hidden="true" />
      <div className="hero-copy">
        <p className="hero-eyebrow"><span /> СТУДИЯ ДЕЛОВЫХ КОММУНИКАЦИЙ</p>
        <h1>Ваши письма.<br />Достойное <em>впечатление.</em></h1>
        <p className="hero-description">От первого обращения до нового диалога.<br className="hidden sm:block" /> Контакты, выразительные письма и ИИ-помощник —<br className="hidden sm:block" /> в одном рабочем пространстве.</p>
        <a href="#studio" className="hero-cta" onClick={onStudio}>Перейти в студию <span aria-hidden="true">↗</span></a>
        <div className="hero-capabilities"><span>Персонализация</span><i /><span>Дизайн писем</span><i /><span>Расписание</span></div>
      </div>
      <div className="hero-art" aria-hidden="true">
        <div className="orbit orbit-one" /><div className="orbit orbit-two" />
        <div className="letter-stack">
          <div className="letter-back"><span>СОЗДАНО ДЛЯ ДИАЛОГА</span><div /><div /><div /></div>
          <div className="letter-front"><div className="letter-meta"><span>PRIVATE EDITION</span><span>↗</span></div><div className="letter-rule" /><p className="letter-kicker">Новый повод для знакомства</p><p className="letter-title">Хорошие идеи<br />начинаются<br /><em>с письма.</em></p><div className="letter-lines"><i /><i /><i /></div><span className="letter-action">Давайте обсудим <b>↗</b></span><div className="letter-signature"><span className="signature-seal">M</span><span>Ваш бизнес.<br />Ваш голос.</span></div></div>
          <div className="floating-note"><span>✧</span><div>От идеи — к диалогу<small>Текст · стиль · точный момент</small></div></div>
        </div>
        <p className="art-caption">THE ART OF BUSINESS COMMUNICATION</p>
      </div>
      <div className="hero-bottom"><span>01 / ВАША РАБОЧАЯ СТУДИЯ</span><span>Прокрутите, чтобы начать <b>↓</b></span></div>
    </header>
  </div>;
}
