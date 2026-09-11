import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { ContactPage, MailTemplate } from "../lib/mailing";
import { SenderEmailField } from "./SenderEmailField";

export function CampaignComposer({ workspaceId, templates, onCreated }: { workspaceId: string; templates: MailTemplate[]; onCreated: (id: string) => void }) {
  const [name, setName] = useState("");
  const [product, setProduct] = useState("");
  const [sender, setSender] = useState("");
  const [senderName, setSenderName] = useState("");
  const [start, setStart] = useState("");
  const [steps, setSteps] = useState<string[]>([""]);
  const [delay, setDelay] = useState(3);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [consent, setConsent] = useState(false);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [listId, setListId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const alive = useRef(true);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => { alive.current = true; return () => { alive.current = false; controller.current?.abort(); }; }, []);
  const lists = useQuery({ queryKey: ["contact-lists", workspaceId], enabled: !!workspaceId, queryFn: () => api<{ id: string; name: string }[]>("/contacts/lists", { workspaceId }) });
  const contacts = useQuery({ queryKey: ["campaign-contacts", workspaceId, page, search, listId], queryFn: ({ signal }) => api<ContactPage>(`/assistant/contacts?page=${page}&page_size=25&search=${encodeURIComponent(search)}${listId ? `&list_id=${listId}` : ""}`, { workspaceId, signal }) });
  const campaigns = useQuery({ queryKey: ["campaigns", workspaceId], enabled: !!workspaceId, queryFn: ({ signal }) => api<{ sender_email: string }[]>("/campaigns", { workspaceId, signal }) });
  async function submit(event: React.FormEvent) {
    event.preventDefault(); if (busy || !consent || !selected.size) return;
    setBusy(true); setError(""); controller.current = new AbortController();
    try {
      const result = await api<{ id: string }>("/assistant/campaigns", { workspaceId, method: "POST", signal: controller.current.signal, body: JSON.stringify({ name, product_name: product, sender_email: sender.trim().toLowerCase(), sender_name: senderName, schedule_start: `${start}:00+03:00`, template_ids: steps, contact_ids: [...selected], delay_days: delay, consent_confirmed: true }) });
      if (alive.current) onCreated(result.id);
    } catch (reason) { if (alive.current) setError(reason instanceof Error ? reason.message : "Не удалось создать рассылку"); }
    finally { if (alive.current) setBusy(false); }
  }
  return <form onSubmit={submit} className="space-y-4 rounded-xl border border-ink/20 p-4" aria-label="Новая рассылка">
    <p>Создаётся только черновик. Отправка не начнётся без отдельного запуска.</p>
    <fieldset disabled={busy} className="min-w-0 space-y-4">
      <div className="grid gap-3 sm:grid-cols-2"><label className="field">Название рассылки<input required minLength={2} maxLength={200} value={name} onChange={e => setName(e.target.value)} /></label><label className="field">Продукт / услуга<input required minLength={2} maxLength={200} value={product} onChange={e => setProduct(e.target.value)} /></label><SenderEmailField value={sender} onChange={setSender} addresses={(campaigns.data ?? []).map(campaign => campaign.sender_email)} loading={campaigns.isLoading} error={campaigns.error?.message} /><label className="field">Имя отправителя<input required maxLength={100} value={senderName} onChange={e => setSenderName(e.target.value)} /></label><label className="field">Первое письмо (МСК)<input type="datetime-local" required value={start} onChange={e => setStart(e.target.value)} /></label><label className="field">Дней между повторными письмами<input type="number" min={1} max={30} value={delay} onChange={e => setDelay(Number(e.target.value))} /></label></div>
      {steps.map((step, index) => <div className="flex items-end gap-2" key={index}><label className="field grow">Письмо {index + 1}<select required value={step} onChange={e => setSteps(previous => previous.map((s, i) => i === index ? e.target.value : s))}><option value="">Выберите проверенный шаблон</option>{templates.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}</select></label>{index > 0 && <button type="button" className="button" onClick={() => setSteps(previous => previous.filter((_, i) => i !== index))}>Убрать шаг {index + 1}</button>}</div>)}
      <button type="button" className="button" disabled={steps.length >= 5} onClick={() => setSteps(previous => [...previous, ""])}>Добавить повторное письмо</button>
      <p className="hint">Первое письмо — в указанное время. Повторные — по будням с 09:00 до 18:00 МСК. После ответа, отписки или возврата цепочка останавливается.</p>
      <label className="field">Найти получателей<input value={search} onChange={e => { setSearch(e.target.value); setPage(1); }} /></label>
      <label className="field">База получателей<select value={listId} onChange={e => { setListId(e.target.value); setPage(1); setSelected(new Set()); setConsent(false); }}><option value="">Все контакты</option>{lists.data?.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
      {lists.error && <p role="alert" className="error-box">{lists.error.message}</p>}
      <p className="font-semibold">Выбрано получателей: {selected.size} / 1000</p>
      <div className="max-h-64 space-y-2 overflow-y-auto rounded-xl border border-ink/15 p-3">{contacts.data?.items.map(contact => <label key={contact.id} className="flex gap-2 break-all"><input type="checkbox" checked={selected.has(contact.id)} disabled={!selected.has(contact.id) && selected.size >= 1000} onChange={e => setSelected(previous => { const next = new Set(previous); if (e.target.checked) next.add(contact.id); else next.delete(contact.id); return next; })} /><span>{contact.full_name || contact.email} · {contact.company} · {contact.email}</span></label>)}{contacts.isLoading && <p>Загрузка контактов…</p>}{contacts.data && !contacts.data.items.length && <p>Контакты не найдены. Импортируйте базу в разделе контактов.</p>}</div>
      <div className="flex gap-3"><button type="button" className="button" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>Назад</button><span>Страница {page}</span><button type="button" className="button" disabled={!contacts.data || page * 25 >= contacts.data.total} onClick={() => setPage(p => p + 1)}>Далее</button><button type="button" className="button" onClick={() => setSelected(new Set())}>Снять выбор</button></div>
      <label className="flex gap-2"><input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)} /><span>Проверил получателей и имею основание для отправки им этих писем.</span></label>
      <button className="button primary" disabled={!consent || !selected.size || busy}>{busy ? "Создаём…" : "Создать черновик рассылки"}</button>
    </fieldset>
    {(error || contacts.error) && <p role="alert" className="error-box">{error || contacts.error?.message}</p>}
  </form>;
}
