import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { stages, type MailTemplate } from "../lib/mailing";

export function TemplatesPanel({ workspaceId, onEdit }: { workspaceId: string; onEdit: (template: MailTemplate | null) => void }) {
  const [stage, setStage] = useState("");
  const [search, setSearch] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [deleteId, setDeleteId] = useState("");
  const client = useQueryClient();
  const templates = useQuery({ queryKey: ["templates", workspaceId], enabled: !!workspaceId, queryFn: () => api<MailTemplate[]>("/templates", { workspaceId }) });
  async function remove(id: string) {
    setBusy(true); setError("");
    try { await api(`/templates/${id}`, { workspaceId, method: "DELETE" }); setDeleteId(""); await client.invalidateQueries({ queryKey: ["templates", workspaceId] }); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Не удалось удалить шаблон"); }
    finally { setBusy(false); }
  }
  const filtered = (templates.data ?? []).filter(item => (!stage || item.category === stage) && `${item.name} ${item.subject_template}`.toLowerCase().includes(search.toLowerCase()));
  return <section className="panel space-y-4">
    <div className="flex flex-wrap items-center justify-between gap-3"><h2 className="font-display text-2xl font-bold">Шаблоны писем</h2><button className="button primary" onClick={() => onEdit(null)}>+ Новый шаблон</button></div>
    <p className="hint">У каждого шаблона своя стадия применения. Выберите шаблон для редактирования и проверки на данных контакта. Сохранение не запускает отправку и не изменяет существующие цепочки.</p>
    <div className="flex flex-wrap gap-3"><label className="field">Стадия рассылки<select value={stage} onChange={e => setStage(e.target.value)}><option value="">Все стадии</option>{Object.entries(stages).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label><label className="field">Поиск шаблона<input value={search} onChange={e => setSearch(e.target.value)} placeholder="Название или тема" /></label></div>
    {(error || templates.error) && <p role="alert" className="error-box">{error || templates.error?.message}</p>}
    {!workspaceId && <p className="hint">Войдите и выберите рабочее пространство для доступа к библиотеке.</p>}
    {templates.isFetching && <p>Загрузка…</p>}
    {workspaceId && !templates.isFetching && !filtered.length && <p className="hint">Шаблонов не найдено. Нажмите «Новый шаблон», заполните письмо и сохраните.</p>}
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{filtered.map(item => <article key={item.id} className="rounded-xl border border-ink/15 p-5">
      <span className="rounded-full bg-acid/40 px-3 py-1 text-xs font-semibold">{stages[item.category] ?? item.category}</span><h3 className="mb-2 mt-4 text-lg font-semibold">{item.name}</h3><p className="break-words text-sm">{item.subject_template}</p><p className="hint my-3">Версия {item.version} · {item.variables.length} переменных</p>
      <div className="flex flex-wrap gap-2"><button className="button primary" onClick={() => onEdit(item)}>Открыть в редакторе</button><button className="button" onClick={() => setDeleteId(item.id)}>Удалить</button></div>
      {deleteId === item.id && <div role="alert" className="mt-3 space-y-2"><p>Удалить «{item.name}»? Это действие нельзя отменить.</p><button className="button" disabled={busy} onClick={() => remove(item.id)}>Да, удалить</button> <button className="button" disabled={busy} onClick={() => setDeleteId("")}>Отмена</button></div>}
    </article>)}</div>
  </section>;
}
