import { useEffect, useState } from "react";
import { EmailEditor } from "../components/editor/EmailEditor";
import { AccountPanel } from "../components/AccountPanel";
import { ContactsPanel } from "../components/ContactsPanel";
import { TemplatesPanel } from "../components/TemplatesPanel";
import type { Contact, MailTemplate } from "../lib/mailing";

export function EditorPage() {
  const [tab, setTab] = useState("editor");
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
  return <main className="mx-auto max-w-[1480px] px-4 py-6 sm:px-8 sm:py-10">
    <header className="mb-6 border-b border-ink/15 pb-7"><p className="mb-2 text-xs font-semibold uppercase tracking-[.22em] text-clay">Premium B2B Mailer / Studio</p><h1 className="font-display text-4xl font-bold tracking-tight sm:text-5xl">Письмо, которое выглядит лично.</h1><p className="mt-3 text-ink/60">База контактов → шаблон по стадии → персональное письмо</p></header>
    <AccountPanel workspaceId={workspace} onChange={id => { setWorkspace(id); setTemplate(null); setContact(null); setEditorKey(key => key + 1); setDirty(false); }} />
    <nav aria-label="Разделы приложения" className="mb-5 flex flex-wrap gap-2">{[["contacts", "Контакты и импорт"], ["templates", "Шаблоны писем"], ["editor", `Редактор письма${dirty ? " •" : ""}`]].map(([key, label]) => <button key={key} aria-current={tab === key ? "page" : undefined} className={`button ${tab === key ? "primary" : ""}`} onClick={() => setTab(key)}>{label}</button>)}</nav>
    <div hidden={tab !== "contacts"}><ContactsPanel key={`contacts-${workspace}`} workspaceId={workspace} onPreview={item => { setContact(item); setTab("editor"); }} /></div>
    <div hidden={tab !== "templates"}><TemplatesPanel key={`templates-${workspace}`} workspaceId={workspace} onEdit={edit} /></div>
    <div hidden={tab !== "editor"}><EmailEditor key={editorKey} workspaceId={workspace} template={template} contact={contact} onSaved={setTemplate} onDirty={setDirty} onChooseContact={() => setTab("contacts")} /></div>
  </main>;
}
