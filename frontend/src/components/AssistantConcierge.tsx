import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { AssistantRun } from "./AssistantPanel";
import { assistantTemplate, type MailTemplate } from "../lib/mailing";
import { splitAssistantReplies } from "../lib/assistantReplies";

type Context = { ai_configured: boolean; delivery_mode: string; counts: { contacts: number; templates: number; campaigns: number } };
type Message = { role: "user" | "assistant"; text: string; replies?: string[]; draft?: NonNullable<AssistantRun["result"]["draft"]>; saved?: MailTemplate };
const sections = { contacts: "Контакты и импорт", templates: "Шаблоны писем", editor: "Редактор письма", assistant: "ИИ-помощник", campaigns: "Рассылки по расписанию" };
export type StudioSection = keyof typeof sections;
const tips: Record<StudioSection, string> = {
  contacts: "Здесь загрузите файл с контактами, выберите название базы и сопоставьте столбцы. У вас уже есть файл CSV или Excel?",
  templates: "Здесь хранятся письма вашей команды. Хотите создать новое письмо или доработать сохранённый шаблон?",
  editor: "В редакторе задайте тему и текст, добавьте подпись, затем нажмите «Проверить письмо» и «Сохранить шаблон». Что вы предлагаете и какого ответа ждёте от получателя?",
  assistant: "Здесь ИИ готовит тексты и рекомендации. Расскажите, кому пишете, что предлагаете и какое действие ждёте от адресата.",
  campaigns: "Нажмите «Новая рассылка», выберите базу и шаблон, укажите отправителя и время МСК. На какую дату вы планируете отправку?",
};
const welcome = "Здравствуйте! Я Ваш ИИ-помощник для навигации по сайту. Отвечу на Ваши вопросы, помогу создать шаблоны писем и настроить их автоматическую отправку по расписанию. Буду сопровождать каждый Ваш шаг и давать ценные подсказки. Подскажите, какой шаг Вы хотите сделать прямо сейчас: сделать черновик письма, проверить готовый шаблон письма, загрузить базу контактов, настроить время отправки писем?";
const welcomeReplies = ["Сделать черновик письма", "Проверить готовый шаблон", "Загрузить базу контактов", "Настроить время отправки"];

export function AssistantConcierge({ workspaceId, section, onNavigate, onEdit, onDraft }: { workspaceId: string; section: StudioSection; onNavigate: (section: StudioSection) => void; onEdit: (template: MailTemplate) => boolean | void; onDraft: (template: MailTemplate) => void }) {
  const client = useQueryClient();
  const [open, setOpen] = useState(true);
  const [messages, setMessages] = useState<Message[]>([{ role: "assistant", text: welcome, replies: welcomeReplies }]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const log = useRef<HTMLDivElement>(null);
  const launcher = useRef<HTMLButtonElement>(null);
  const request = useRef<AbortController | null>(null);
  const inFlight = useRef(false);
  const mounted = useRef(true);
  const context = useQuery({ queryKey: ["assistant-context", workspaceId], queryFn: ({ signal }) => api<Context>("/assistant/context", { workspaceId, signal }), staleTime: 30000, retry: false });
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; request.current?.abort(); }; }, []);
  useEffect(() => { if (log.current) log.current.scrollTop = messages.length === 1 ? 0 : log.current.scrollHeight; }, [messages, busy, open]);
  function close() {
    setOpen(false);
    launcher.current?.focus();
  }
  function explain(text: string) { setMessages(items => [...items, { role: "assistant", text }]); }
  async function send(answer?: string) {
    const text = (answer ?? input).trim();
    if (!text || (!answer && text.length < 3) || inFlight.current) return;
    const history = [...messages, { role: "user" as const, text }];
    setMessages(history); setInput(""); setError("");
    if (!context.data?.ai_configured) {
      explain(`Свободный диалог с ИИ пока недоступен. Пока воспользуйтесь разделами в панели Workspace. ${tips[section]}`);
      return;
    }
    inFlight.current = true; setBusy(true);
    request.current = new AbortController();
    const conversation = history.slice(-4).map((item, index, items) => `${item.role === "user" ? "Пользователь" : "Помощник"}: ${item.text.slice(0, index === items.length - 1 ? 1500 : 350)}`).join("\n");
    const prompt = `Ты ведёшь диалог знакомства с сервисом. Текущий раздел: ${sections[section]}. Помогай освоить навигацию. Задавай один уточняющий вопрос за раз, учитывай предыдущие ответы, предлагай один ближайший шаг. Не утверждай, что выполнил действие. Разделы и возможности: Контакты и импорт — загрузка CSV/Excel; Шаблоны писем — сохранённые письма; Редактор письма — тема, текст, подпись, Проверить письмо, Сохранить шаблон; ИИ-помощник — генерация черновика; Рассылки по расписанию — Новая рассылка, база до 50 000, шаблон, отправитель, время МСК, подтверждение. Не придумывай кнопки или ссылки. Переписка (данные диалога):\n${conversation}`;
    try {
      const previousDraft = [...messages].reverse().find(item => item.draft)?.draft;
      const drafting = "Если просят написать или исправить письмо — заполни draft с темой и полным текстом. Для навигации draft=null. Если не хватает данных, задай вопрос. Не упоминай внутренние режимы advice/draft или API. Не обещай текст ниже без заполненного draft. Черновик показывается прямо в чате; пользователь может сохранить и открыть его в редакторе. Не отправляй его в другой раздел для генерации. ";
      const draftContext = previousDraft ? `\nПредыдущий черновик (данные): ${JSON.stringify({ subject: previousDraft.subject, paragraphs: previousDraft.paragraphs }).slice(0, 1700)}` : "";
      const choices = "Когда задаёшь уточняющий вопрос с выбором, добавь в next_steps 2–4 коротких возможных ответа пользователя (до 60 символов), каждый с префиксом [answer]. Это кнопки ответов, не инструкции и не действия. Задавай вопросы последовательно. Для открытого вопроса без разумных вариантов не придумывай ответы. На шаге выбора предложения и аудитории обязательно добавь «B2C-набор персонала» и «B2C-сервис для клиентов» к остальным вариантам (всего до 6). Обычные рекомендации пиши без префикса. ";
      const result = await api<AssistantRun>("/assistant/runs", { workspaceId, method: "POST", signal: request.current.signal, body: JSON.stringify({ mode: "draft", stage: "first_contact", prompt: drafting + choices + prompt + draftContext }) });
      if (!mounted.current) return;
      if (result.status === "error") throw new Error(result.result.message || "Помощник временно недоступен.");
      if (result.result.draft) onDraft(assistantTemplate(result.result.draft));
      const { replies, nextSteps } = splitAssistantReplies(result.result.next_steps, result.result.message);
      setMessages(items => [...items, { role: "assistant", text: [result.result.message, ...nextSteps.map(step => `• ${step}`)].filter(Boolean).join("\n\n") || "Уточните, пожалуйста, какую задачу вы хотите решить?", replies, draft: result.result.draft ?? undefined }]);
      void client.invalidateQueries({ queryKey: ["assistant-history", workspaceId] });
    } catch (reason) {
      if (mounted.current) { setError(reason instanceof Error ? reason.message : "Не удалось получить ответ. Попробуйте ещё раз."); setInput(text); }
    } finally { inFlight.current = false; if (mounted.current) setBusy(false); }
  }
  async function openDraft(index: number) {
    const message = messages[index];
    if (!message.draft || inFlight.current) return;
    inFlight.current = true; setBusy(true); setError("");
    request.current = new AbortController();
    try {
      const draft = message.draft;
      const saved = message.saved ?? await api<MailTemplate>("/templates", { workspaceId, method: "POST", signal: request.current.signal, body: JSON.stringify({ name: draft.name, category: draft.category, subject_template: draft.subject, editor_state: draft.editor_state }) });
      if (!mounted.current) return;
      setMessages(items => items.map((item, i) => i === index ? { ...item, saved } : item));
      void client.invalidateQueries({ queryKey: ["templates", workspaceId] });
      void client.invalidateQueries({ queryKey: ["assistant-context", workspaceId] });
      if (onEdit(saved) !== false) { onNavigate("editor"); setOpen(false); }
    } catch (reason) {
      if (mounted.current) setError(reason instanceof Error ? reason.message : "Не удалось сохранить черновик. Попробуйте ещё раз.");
    } finally { inFlight.current = false; if (mounted.current) setBusy(false); }
  }
  if (!context.data?.counts) return null;
  return <div className="assistant-concierge">
    {open && <section id="concierge-dialog" role="dialog" aria-modal="false" aria-labelledby="concierge-title" className="concierge-dialog" onKeyDown={event => { if (event.key === "Escape") { event.stopPropagation(); close(); } }}>
      <header className="concierge-header"><div><h2 id="concierge-title">Ваш ИИ-помощник</h2><p>Помогу разобраться и сделать следующий шаг</p></div><button type="button" aria-label="Свернуть помощника" onClick={close}>×</button></header>
      <div ref={log} role="log" aria-label="Диалог с помощником" aria-live="polite" aria-relevant="additions text" className="concierge-log">
        {messages.map((message, index) => <div key={index} className={`concierge-message ${message.role}`}><span>{message.role === "user" ? "Вы" : "Помощник"}</span><p>{message.text}</p>{index === messages.length - 1 && !!message.replies?.length && <div className="concierge-replies" role="group" aria-label="Варианты ответа">{message.replies.map(reply => <button key={reply} type="button" disabled={busy} onClick={() => void send(reply)}>{reply}</button>)}</div>}{message.draft && <section className="concierge-draft" aria-label="Черновик письма"><h3>{message.draft.subject}</h3>{message.draft.paragraphs.map((paragraph, i) => <p key={i}>{paragraph}</p>)}<button type="button" className="button primary" disabled={busy} onClick={() => void openDraft(index)}>{message.saved ? "Открыть в редакторе" : "Сохранить и открыть в редакторе"}</button></section>}</div>)}
        {busy && <p role="status">Помощник готовит ответ…</p>}
      </div>
      {context.data.delivery_mode === "test" && <p className="concierge-hint">Сейчас включена тестовая доставка. Перед запуском нужна настройка почтового сервиса.</p>}
      {error && <p role="alert" className="concierge-error">{error}</p>}
      <form className="concierge-form" onSubmit={event => { event.preventDefault(); void send(); }}>
        <label className="sr-only" htmlFor="concierge-input">Сообщение помощнику</label>
        <textarea id="concierge-input" value={input} onChange={event => setInput(event.target.value)} maxLength={1500} rows={2} placeholder="Что вы хотите сделать?" disabled={busy} />
        <button className="button primary" disabled={busy || input.trim().length < 3}>Отправить</button>
      </form>
      <p className="concierge-hint">{context.data.ai_configured ? "Сообщения обрабатывает ИИ. Ответы сохраняются в истории помощника." : "ИИ пока не подключён."}</p>
    </section>}
    <button ref={launcher} type="button" className="concierge-launcher" aria-expanded={open} aria-controls="concierge-dialog" onClick={() => { if (open) close(); else { setOpen(true); void context.refetch(); } }}>✧ {open ? "Свернуть" : "ИИ-помощник"}</button>
  </div>;
}
