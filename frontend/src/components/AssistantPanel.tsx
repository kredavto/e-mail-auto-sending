import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { JSONContent } from "@tiptap/core";
import { api } from "../lib/api";
import { stages, type MailTemplate, type Stage } from "../lib/mailing";
import { CampaignComposer } from "./CampaignComposer";

type Action = { kind: "start" | "pause" | "reschedule"; campaign_id: string; campaign_name: string; send_at: string; recipients: number; sender_email: string; warning: string };
export type AssistantRun = { id: string; prompt: string; model: string; status: string; created_at: string; applied_at: string | null; input_tokens: number; output_tokens: number; result: { message: string; estimated_cost_usd?: number | null; next_steps?: string[]; draft?: { name: string; subject: string; category: Stage; paragraphs: string[]; editor_state: JSONContent } | null; action?: Action | null } };
type Campaign = { id: string; name: string; status: string; schedule_start: string; sender_email: string };
type Context = { ai_configured: boolean; can_manage: boolean; delivery_mode: string; daily_limit: number; counts: { contacts: number; templates: number; campaigns: number } };
const actionNames = { start: "Запустить / возобновить", pause: "Приостановить", reschedule: "Перенести начало" };
const statusNames: Record<string, string> = { draft: "Черновик", running: "Планировщик активен", paused: "На паузе", scheduled: "Запланирована", completed: "Завершена" };
const dateLabel = (date: string) => new Date(date).toLocaleString("ru-RU", { timeZone: "Europe/Moscow" }) + " МСК";

export function AssistantPanel({ workspaceId, active, onEdit }: { workspaceId: string; active: boolean; onEdit: (template: MailTemplate) => void }) {
  const client = useQueryClient();
  const [mode, setMode] = useState("draft");
  const [stage, setStage] = useState<Stage>("first_contact");
  const [prompt, setPrompt] = useState("");
  const [templateId, setTemplateId] = useState("");
  const [campaignId, setCampaignId] = useState("");
  const [sendAt, setSendAt] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [run, setRun] = useState<AssistantRun | null>(null);
  const [approve, setApprove] = useState(false);
  const [showComposer, setShowComposer] = useState(false);
  const alive = useRef(true);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => { alive.current = true; return () => { alive.current = false; controller.current?.abort(); }; }, []);
  const enabled = active && !!workspaceId;
  const context = useQuery({ queryKey: ["assistant-context", workspaceId], enabled, queryFn: ({ signal }) => api<Context>("/assistant/context", { workspaceId, signal }) });
  const templates = useQuery({ queryKey: ["templates", workspaceId], enabled, queryFn: ({ signal }) => api<MailTemplate[]>("/templates", { workspaceId, signal }) });
  const campaigns = useQuery({ queryKey: ["campaigns", workspaceId], enabled, queryFn: ({ signal }) => api<Campaign[]>("/campaigns", { workspaceId, signal }), refetchInterval: enabled ? 30000 : false });
  const history = useQuery({ queryKey: ["assistant-history", workspaceId], enabled, queryFn: ({ signal }) => api<AssistantRun[]>("/assistant/runs", { workspaceId, signal }) });
  const target = campaigns.data?.find(item => item.id === campaignId);
  function selectRun(item: AssistantRun) {
    setRun(item); setApprove(false);
    window.history.replaceState(null, "", `#assistant=${item.id}`);
  }
  useEffect(() => {
    if (!run && history.data) {
      const id = new URLSearchParams(window.location.hash.slice(1)).get("assistant");
      const saved = history.data.find(item => item.id === id);
      if (saved) setRun(saved);
    }
  }, [history.data, run]);
  async function refresh() {
    await Promise.all(["assistant-history", "assistant-context", "campaigns", "templates"].map(key => client.invalidateQueries({ queryKey: [key, workspaceId] })));
  }
  async function request(path: string, body: unknown) {
    if (busy) return;
    setBusy(true); setError(""); setApprove(false);
    controller.current = new AbortController();
    try {
      const result = await api<AssistantRun>(path, { workspaceId, method: "POST", body: JSON.stringify(body), signal: controller.current.signal });
      if (!alive.current) return;
      selectRun(result); await refresh();
    } catch (reason) {
      if (alive.current) setError(reason instanceof Error ? reason.message : "Запрос не выполнен. Обновите историю перед повтором.");
    } finally { if (alive.current) setBusy(false); }
  }
  async function openDraft() {
    if (!run?.result.draft || busy) return;
    const draft = run.result.draft;
    setBusy(true); setError(""); controller.current = new AbortController();
    try {
      const saved = await api<MailTemplate>("/templates", { workspaceId, method: "POST", signal: controller.current.signal, body: JSON.stringify({ name: draft.name, category: draft.category, subject_template: draft.subject, editor_state: draft.editor_state }) });
      if (alive.current) { await refresh(); onEdit(saved); }
    } catch (reason) { if (alive.current) setError(reason instanceof Error ? reason.message : "Не удалось сохранить шаблон"); }
    finally { if (alive.current) setBusy(false); }
  }
  if (!workspaceId) return <section className="panel">Войдите и выберите рабочее пространство для работы с ИИ.</section>;
  const failure = context.error || templates.error || campaigns.error || history.error;
  return <div className="space-y-5">
    <section className="panel space-y-4">
      <h2 className="font-display text-2xl font-bold">ИИ-помощник</h2>
      <p className="hint">Создаёт черновики писем, подсказывает следующие шаги и готовит изменения расписания. Реальная отправка включается только после отдельного подтверждения.</p>
      {failure && <p role="alert" className="error-box">{failure.message}</p>}
      {context.data && <><p>Контактов: {context.data.counts.contacts} · Шаблонов: {context.data.counts.templates} · Кампаний: {context.data.counts.campaigns}</p>
        {!context.data.ai_configured && <p className="error-box">OpenAI ещё не подключён на сервере.</p>}
        {context.data.delivery_mode === "test" && <p className="error-box">Тестовая доставка: сервер использует Mailpit. Письма не доставляются реальным адресатам. Для внешней отправки администратор должен подключить SMTP/SES.</p>}
        {!context.data.counts.contacts && <p className="hint">Следующий шаг: импортируйте базу в разделе «Контакты и импорт».</p>}
        {!context.data.counts.templates && <p className="hint">Создайте первый шаблон здесь, проверьте его в редакторе, затем подготовьте рассылку.</p>}
      </>}
      <form className="space-y-4" onSubmit={event => { event.preventDefault(); void request("/assistant/runs", { prompt, mode, stage, template_id: templateId || null, campaign_id: mode === "schedule" ? campaignId || null : null }); }}>
        <fieldset disabled={busy} className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-3">
            <label className="field">Задача помощника<select value={mode} onChange={e => setMode(e.target.value)}><option value="draft">Создать / улучшить письмо</option><option value="advice">Что делать дальше?</option><option value="schedule">Помочь с расписанием</option></select></label>
            <label className="field">Стадия нового письма<select value={stage} onChange={e => setStage(e.target.value as Stage)}>{Object.entries(stages).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
            <label className="field">Шаблон для улучшения<select value={templateId} onChange={e => setTemplateId(e.target.value)}><option value="">Не использовать</option>{templates.data?.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
          </div>
          <label className="field">Задание для ИИ<textarea value={prompt} onChange={e => setPrompt(e.target.value)} minLength={3} maxLength={6000} rows={4} required placeholder="Например: напиши первое письмо директору автосалона. Предлагаем внедрение CRM. Цель — договориться о 15-минутном знакомстве." /></label>
          <p className="hint">В OpenAI передаются ваш запрос, выбранный сохранённый шаблон и краткие сведения о кампании. База контактов целиком не передаётся. Не вводите пароли и конфиденциальные сведения. Лимит: {context.data?.daily_limit ?? "—"} запросов на пространство в сутки.</p>
          <button className="button primary" disabled={!context.data?.ai_configured || busy}>{busy ? "Обрабатываем…" : "Спросить ИИ"}</button>
        </fieldset>
      </form>
    </section>
    {error && <p role="alert" className="error-box">{error}</p>}
    {run && <section className="panel space-y-4" aria-label="Ответ помощника">
      <div className="flex flex-wrap justify-between gap-2"><h3 className="font-display text-xl font-bold">Результат</h3><a className="hint underline" href={`#assistant=${run.id}`}>Сохранённый запрос · {dateLabel(run.created_at)}</a></div>
      <p className={run.status === "error" ? "error-box" : "whitespace-pre-wrap"}>{run.result.message || "Запрос ещё обрабатывается. Обновите историю позже."}</p>
      {!!run.result.next_steps?.length && <ol className="list-decimal space-y-2 pl-5">{run.result.next_steps.map((step, i) => <li key={i}>{step}</li>)}</ol>}
      {run.result.draft && <div className="space-y-3 rounded-xl border border-ink/15 p-4"><p className="font-semibold">{run.result.draft.subject}</p>{run.result.draft.paragraphs.map((p, i) => <p key={i} className="whitespace-pre-wrap">{p}</p>)}<button className="button primary" onClick={openDraft} disabled={busy}>Сохранить как новый шаблон и открыть</button><p className="hint">Существующий шаблон не перезаписывается. В редакторе проверьте факты, переменные и CTA.</p></div>}
      {run.result.action && <div className="space-y-3 rounded-xl border-2 border-clay p-4">
        <h4 className="font-bold">На подтверждение: {actionNames[run.result.action.kind]}</h4>
        <p>{run.result.action.campaign_name} · {run.result.action.recipients} получателей · От: {run.result.action.sender_email}</p>
        <p>Начало: {dateLabel(run.result.action.send_at)}</p><p className="hint">{run.result.action.warning}</p>
        {run.applied_at ? <p role="status" className="success-box">Действие выполнено {dateLabel(run.applied_at)}. Повторное подтверждение не требуется.</p> : <><label className="flex items-start gap-2"><input type="checkbox" checked={approve} onChange={e => setApprove(e.target.checked)} disabled={busy} /><span>Параметры проверены. Подтверждаю это действие для указанной кампании.</span></label><button className="button primary" disabled={!approve || busy || !context.data?.can_manage} onClick={() => request(`/assistant/runs/${run.id}/confirm`, { confirmed: true })}>Подтвердить действие</button><p className="hint">Предложение действует 15 минут. При изменении кампании потребуется новое подтверждение.</p></>}
      </div>}
      <p className="hint">{run.model === "manual" ? "Без обращения к ИИ" : `${run.model} · Вход: ${run.input_tokens} токенов · Выход: ${run.output_tokens} токенов`}</p>
      {run.result.estimated_cost_usd != null && <p className="hint">Оценка API: ${run.result.estimated_cost_usd.toFixed(6)} (без скидки за кэш; итог — в биллинге OpenAI).</p>}
    </section>}
    <section className="panel space-y-4">
      <div className="flex flex-wrap justify-between gap-2"><h2 className="font-display text-2xl font-bold">Рассылки и расписание</h2><button className="button" disabled={!context.data?.can_manage || busy} onClick={() => setShowComposer(!showComposer)}>Новая рассылка</button></div>
      {!context.data?.can_manage && <p className="hint">Изменения доступны владельцу, администратору или менеджеру.</p>}
      {showComposer && <CampaignComposer workspaceId={workspaceId} templates={templates.data ?? []} onCreated={id => { setCampaignId(id); setShowComposer(false); void refresh(); }} />}
      <label className="field">Кампания для управления<select value={campaignId} onChange={e => { setCampaignId(e.target.value); setApprove(false); }} disabled={busy}><option value="">Выберите кампанию</option>{campaigns.data?.map(item => <option key={item.id} value={item.id}>{item.name} — {statusNames[item.status] ?? item.status}</option>)}</select></label>
      {target ? <><p>{statusNames[target.status] ?? target.status} · Начало: {dateLabel(target.schedule_start)} · {target.sender_email}</p>
        <fieldset disabled={busy || !context.data?.can_manage} className="flex flex-wrap items-end gap-3">
          <button className="button" disabled={!["draft", "paused", "scheduled"].includes(target.status)} onClick={() => request(`/assistant/campaigns/${target.id}/propose`, { action: "start" })}>Подготовить запуск</button>
          <button className="button" disabled={!["running", "scheduled"].includes(target.status)} onClick={() => request(`/assistant/campaigns/${target.id}/propose`, { action: "pause" })}>Подготовить паузу</button>
          <label className="field">Новое время начала (МСК)<input type="datetime-local" value={sendAt} onChange={e => setSendAt(e.target.value)} /></label>
          <button className="button" disabled={!sendAt || !["draft", "paused"].includes(target.status)} onClick={() => request(`/assistant/campaigns/${target.id}/propose`, { action: "reschedule", send_at: `${sendAt}:00+03:00` })}>Подготовить перенос</button>
        </fieldset><p className="hint">Эти кнопки только готовят предложение. Изменение произойдёт после подтверждения выше. После запуска сервер работает по расписанию даже при закрытом браузере.</p></> : <p className="hint">Выберите кампанию или создайте черновик рассылки из шаблонов и контактов.</p>}
    </section>
    <section className="panel space-y-3"><h2 className="font-display text-xl font-bold">Моя история запросов</h2><button className="button" onClick={() => history.refetch()} disabled={busy}>Обновить историю</button>{!history.data?.length && <p className="hint">Здесь появятся последние 30 запросов текущего пользователя.</p>}<div className="space-y-2">{history.data?.map(item => <button key={item.id} className="block w-full rounded-lg border border-ink/15 p-3 text-left" disabled={busy} onClick={() => selectRun(item)}>{item.prompt.slice(0, 130)} <span className="hint">· {dateLabel(item.created_at)} · {item.status === "error" ? "Ошибка" : item.applied_at ? "Подтверждено" : item.status === "pending" ? "Обрабатывается" : "Готово"}</span></button>)}</div></section>
  </div>;
}
