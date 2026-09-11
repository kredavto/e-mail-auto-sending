import { useEffect, useState } from "react";
import { EmailEditor } from "../components/editor/EmailEditor";
import { AccountPanel } from "../components/AccountPanel";
import { ContactsPanel } from "../components/ContactsPanel";
import { TemplatesPanel } from "../components/TemplatesPanel";
import { AssistantPanel } from "../components/AssistantPanel";
import type { Contact, MailTemplate } from "../lib/mailing";
import { StudioHero } from "../components/StudioHero";

export function EditorPage() {
  const [tab, setTab] = useState(window.location.hash.startsWith("#assistant=") ? "assistant" : "editor");
  const [workspace, setWorkspace] = useState(localStorage.getItem("workspace_id") ?? "");
  const [template, setTemplate] = useState<MailTemplate | null>(null);
  const [contact, setContact] = useState<Contact | null>(null);
  const [editorKey, setEditorKey] = useState(0);
  const [dirty, setDirty] = useState(false);
  useEffect(() => {
    const prevent = (event: BeforeUnloadEvent) => { if (dirty) event.preventDefault(); };
    window.addEventListener("beforeunload", prevent);
    return () => window.removeEventListener("beforeunload", prevent);
  }, [dirty]);
  function edit(item: MailTemplate | null) {
    if (dirty && !window.confirm("В редакторе есть несохранённые изменения. Открыть другой шаблон без их сохранения?")) return;
    setTemplate(item); setEditorKey(key => key + 1); setDirty(false); setTab("editor");
  }
  return <div className="premium-shell">
    <a href="#studio" className="skip-link">Перейти к рабочей области</a>
    <StudioHero onStudio={() => setTab("editor")} />
    <main id="studio" className="studio-workspace" tabIndex={-1}>
      <aside className="studio-sidebar"><div className="sidebar-heading"><span className="sidebar-monogram" aria-hidden="true">M /</span><p>WORKSPACE<small>Ваша студия</small></p></div>
        <nav aria-label="Разделы приложения" className="studio-nav">{[["contacts", "Контакты и импорт", "01", "База для новых диалогов"], ["templates", "Шаблоны писем", "02", "Библиотека вашего голоса"], ["editor", `Редактор письма${dirty ? " •" : ""}`, "03", "Текст, стиль и детали"], ["assistant", "ИИ-помощник", "04", "Идеи и расписание"]].map(([key, label, number, description]) => <button key={key} aria-label={label} aria-current={tab === key ? "page" : undefined} className="studio-nav-item" onClick={() => setTab(key)}><span className="nav-number" aria-hidden="true">{number}</span><span>{label}<small aria-hidden="true">{description}</small></span><span className="nav-arrow" aria-hidden="true">↗</span></button>)}</nav>
        <div className="sidebar-note"><span aria-hidden="true">✧</span><p>Внимание к деталям.<small>Проверьте письмо перед отправкой. Сильное впечатление начинается с точности.</small></p></div>
      </aside>
      <div className="studio-content"><div className="workspace-heading"><div><p>PREMIUM B2B MAILER</p><h2>Пространство ваших идей</h2></div><span className="workspace-tag">Творчество. Под контролем.</span></div>
    <AccountPanel workspaceId={workspace} onChange={id => { setWorkspace(id); setTemplate(null); setContact(null); setEditorKey(key => key + 1); setDirty(false); }} />
    <div className="workspace-view" hidden={tab !== "assistant"}><AssistantPanel key={`assistant-${workspace}`} workspaceId={workspace} active={tab === "assistant"} onEdit={edit} /></div>
    <div className="workspace-view" hidden={tab !== "contacts"}><ContactsPanel key={`contacts-${workspace}`} workspaceId={workspace} onPreview={item => { setContact(item); setTab("editor"); }} /></div>
    <div className="workspace-view" hidden={tab !== "templates"}><TemplatesPanel key={`templates-${workspace}`} workspaceId={workspace} onEdit={edit} /></div>
    <div className="workspace-view" hidden={tab !== "editor"}><EmailEditor key={editorKey} workspaceId={workspace} template={template} contact={contact} onSaved={setTemplate} onDirty={setDirty} onChooseContact={() => setTab("contacts")} /></div>
      </div>
    </main>
    <footer className="studio-footer"><span>PREMIUM B2B MAILER</span><p>Ваш бизнес заслуживает красивых писем.</p><a href="#studio">Вернуться в студию ↑</a></footer>
  </div>;
}
