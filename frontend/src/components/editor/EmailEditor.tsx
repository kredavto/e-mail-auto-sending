import Placeholder from "@tiptap/extension-placeholder";
import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { closeHistory } from "@tiptap/pm/history";
import { useEffect, useRef, useState, type CSSProperties } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "../../lib/api";
import { baseVariables, contactVariables, generalLetterIssue, getLetterType, initialDocument, interpolate, letterTypes, safeCtaUrl, stages, withLetterType, type Contact, type LetterType, type MailTemplate, type Stage } from "../../lib/mailing";
import { CaseStudyBlock, CTAButton, EmailImage, EmailVideo, SignatureBlock, UnsubscribeBlock, Variable } from "./extensions";
import { ImageUpload } from "./ImageUpload";
import { ctaDestination, moveCta } from "./cta-movement";
import { EmailStylePanel } from "./EmailStylePanel";
import { emailFonts, getEmailStyle, readableText, withEmailStyle } from "../../lib/email-style";

type CompileResult = { html: string; text: string; variables: string[]; quality_score: number; warnings: string[] };
type QualityResult = { score: number; issues: string[]; warnings: string[]; suggestions: string[]; words_count: number };
type Props = { workspaceId: string; template: MailTemplate | null; contact: Contact | null; onSaved: (template: MailTemplate) => void; onDirty: (dirty: boolean) => void; onChooseContact: () => void };

export function EmailEditor({ workspaceId, template, contact, onSaved, onDirty, onChooseContact }: Props) {
  const [subject, setSubject] = useState(template?.subject_template ?? "{{first_name}}, идея для {{company}}");
  const [name, setName] = useState(template?.name ?? "");
  const [stage, setStage] = useState<Stage>(template?.category ?? "first_contact");
  const [letterType, setLetterType] = useState<LetterType>(() => getLetterType(template?.editor_state));
  const [emailStyle, setEmailStyle] = useState(() => getEmailStyle(template?.editor_state));
  const [result, setResult] = useState<CompileResult | null>(null);
  const [quality, setQuality] = useState<QualityResult | null>(null);
  const [preview, setPreview] = useState("");
  const [previewSubject, setPreviewSubject] = useState("");
  const [previewMissing, setPreviewMissing] = useState<string[]>([]);
  const [productName, setProductName] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [checking, setChecking] = useState(false);
  const [saving, setSaving] = useState(false);
  const [showImage, setShowImage] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [showCta, setShowCta] = useState(false);
  const [ctaLabel, setCtaLabel] = useState("Обсудить задачу");
  const [ctaUrl, setCtaUrl] = useState("");
  const [ctaError, setCtaError] = useState("");
  const [ctaTarget, setCtaTarget] = useState<{ from: number; to: number; edit: boolean } | null>(null);
  const [variableName, setVariableName] = useState(getLetterType(template?.editor_state) === "general" ? "product_name" : "first_name");
  const client = useQueryClient();
  const revision = useRef(0);
  function changed() { revision.current++; setResult(null); setQuality(null); setPreview(""); setNotice(""); onDirty(true); }
  const editor = useEditor({
    extensions: [StarterKit, Placeholder.configure({ showOnlyCurrent: false, placeholder: ({ node }) => node.type.name === "heading" ? "Заголовок по тематике письма" : "Напишите короткое, конкретное письмо..." }), Variable, SignatureBlock, CaseStudyBlock, CTAButton, UnsubscribeBlock, EmailImage, EmailVideo],
    content: template?.editor_state ?? initialDocument,
    onUpdate: changed,
  });
  useEffect(() => { setPreview(""); setResult(null); setQuality(null); revision.current++; }, [contact]);
  useEffect(() => { editor?.setEditable(!saving && !uploading && !showCta, false); }, [editor, saving, uploading, showCta]);
  function switchLetterType(next: LetterType) {
    if (!editor || next === letterType) return;
    // Only replace untouched starter content; never remove the user's letter or media.
    if (!template && next === "general") {
      if (subject === "{{first_name}}, идея для {{company}}") setSubject("");
      if (JSON.stringify(editor.getJSON().content) === JSON.stringify(initialDocument.content)) {
        editor.commands.setContent({ type: "doc", content: [{ type: "heading", attrs: { level: 2 } }, { type: "paragraph" }] });
      }
    }
    setLetterType(next); setVariableName(next === "general" ? "product_name" : "first_name"); setError(""); changed();
  }
  async function compile() {
    if (!editor || (letterType === "general" && generalLetterIssue(editor.getJSON(), subject))) return;
    setChecking(true); setError(""); setPreview("");
    const currentRevision = revision.current;
    const state = withEmailStyle(withLetterType(editor.getJSON(), letterType), emailStyle);
    try {
      const compiled = await api<CompileResult>("/editor/compile", { method: "POST", body: JSON.stringify({ editor_state: state }) });
      const variables: Record<string, string> = letterType === "personalized" && contact ? contactVariables(contact, productName) : { product_name: productName };
      const used = [...new Set([...compiled.variables, ...Array.from(subject.matchAll(/{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*}}/g), match => match[1])])];
      const missing = used.filter(key => !variables[key]);
      const values = { ...variables };
      used.forEach(key => { if (!values[key]) values[key] = `{{${key}}}`; });
      const [rendered, report] = await Promise.all([
        api<{ html: string }>("/editor/preview", { method: "POST", body: JSON.stringify({ editor_state: state, variables: values }) }),
        api<QualityResult>("/quality/check", { method: "POST", body: JSON.stringify({ html: compiled.html, text: compiled.text, subject }) }),
      ]);
      if (revision.current !== currentRevision) return;
      setResult(compiled); setQuality(report); setPreview(rendered.html); setPreviewSubject(interpolate(subject, values)); setPreviewMissing(missing);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Не удалось проверить письмо"); }
    finally { setChecking(false); }
  }
  async function save(copy = false) {
    if (!editor || !workspaceId || uploading || showCta) return;
    if (letterType === "general" && generalLetterIssue(editor.getJSON(), subject)) return;
    if (!name.trim() || !subject.trim()) { setError("Заполните название шаблона и тему письма."); return; }
    setSaving(true); setError(""); setNotice("");
    try {
      const saved = await api<MailTemplate>(template && !copy ? `/templates/${template.id}` : "/templates", { workspaceId, method: template && !copy ? "PATCH" : "POST", body: JSON.stringify({ name: name.trim(), category: stage, subject_template: subject, editor_state: withEmailStyle(withLetterType(editor.getJSON(), letterType), emailStyle) }) });
      onDirty(false); onSaved(saved); setNotice(`Шаблон сохранён на сервере · версия ${saved.version}`);
      await client.invalidateQueries({ queryKey: ["templates", workspaceId] });
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Ошибка сохранения"); }
    finally { setSaving(false); }
  }
  function insertCta(event: React.FormEvent) {
    event.preventDefault();
    if (!editor || !ctaTarget || saving || uploading) return;
    const url = safeCtaUrl(ctaUrl);
    if (!url || !ctaLabel.trim()) { setCtaError("Укажите текст и полный адрес ссылки с https:// или http://."); return; }
    const attrs = { label: ctaLabel.trim(), url };
    if (ctaTarget.edit && editor.state.doc.nodeAt(ctaTarget.from)?.type.name !== "ctaButton") { setCtaError("Кнопка изменилась. Закройте форму и выберите её снова."); return; }
    editor.chain().command(({ tr }) => { closeHistory(tr); return true; }).insertContentAt({ from: ctaTarget.from, to: ctaTarget.to }, { type: "ctaButton", attrs }).run();
    setShowCta(false); setCtaError("");
  }
  function openCta(edit = false) {
    if (!editor) return;
    const { from, to } = editor.state.selection;
    setCtaTarget({ from: edit ? from : to, to, edit });
    if (edit) { const attrs = editor.getAttributes("ctaButton"); setCtaLabel(attrs.label); setCtaUrl(attrs.url); }
    else { setCtaLabel("Обсудить задачу"); setCtaUrl(""); }
    setShowCta(true); setCtaError("");
  }
  function downloadHtml() {
    const url = URL.createObjectURL(new Blob([`<!doctype html><html lang="ru"><head><meta charset="UTF-8"><title>Письмо</title></head><body>${preview}</body></html>`], { type: "text/html;charset=utf-8" }));
    const link = document.createElement("a"); link.href = url; link.download = "letter-preview.html"; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  const variables = letterType === "general" ? ["product_name"] : [...new Set([...baseVariables, ...Object.keys(contact?.custom_fields ?? {}).filter(key => /^[a-zA-Z][a-zA-Z0-9_]*$/.test(key))])];
  if (!editor) return null;
  const typeIssue = letterType === "general" ? generalLetterIssue(editor.getJSON(), subject) : "";
  return <div className="space-y-5">
    <section className="panel flex flex-wrap items-end gap-3">
      <fieldset disabled={saving || uploading || showCta} className="w-full space-y-2" aria-describedby="letter-type-help">
        <legend className="mb-2 font-semibold">Тип письма</legend>
        <div className="flex flex-wrap gap-2">{Object.entries(letterTypes).map(([value, label]) => <button key={value} type="button" className={`button ${letterType === value ? "primary" : ""}`} aria-pressed={letterType === value} onClick={() => switchLetterType(value as LetterType)}>{label}</button>)}</div>
        <p id="letter-type-help" className="hint">{letterType === "general" ? "Одинаковый текст для всех: начните с заголовка по тематике письма, без приветствия и ФИО. Подходит для корпоративной почты, когда получатель неизвестен. Для контакта достаточно email." : "Индивидуальное обращение: подставьте имя, компанию и другие известные данные из базы контактов."}</p>
      </fieldset>
      <label className="field grow">Название шаблона<input value={name} maxLength={200} onChange={e => { setName(e.target.value); changed(); }} placeholder="Например: первое предложение директору" disabled={saving} /></label>
      <label className="field">Стадия применения<select value={stage} disabled={saving} onChange={e => { setStage(e.target.value as Stage); changed(); }}>{Object.entries(stages).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
      <button className="button primary" onClick={() => save()} disabled={!workspaceId || saving || uploading || showCta || !!typeIssue}>{saving ? "Сохраняем…" : "Сохранить шаблон"}</button>
      {template && <button className="button" onClick={() => save(true)} disabled={!workspaceId || saving || uploading || showCta || !!typeIssue}>Сохранить копию</button>}
      <p className="hint w-full">{template ? `Версия ${template.version}. ` : "Новый шаблон. "}Сохраняйте изменения кнопкой выше.{!workspaceId && " Для сохранения войдите в рабочее пространство."}</p>
    </section>
    {error && <p role="alert" className="error-box">{error}</p>}{notice && <p role="status" className="success-box">{notice}</p>}
    {typeIssue && <p role="alert" className="error-box">{typeIssue}</p>}
    <EmailStylePanel value={emailStyle} disabled={saving || uploading || showCta} onChange={next => { setEmailStyle(next); changed(); }} />
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
      <section className="overflow-hidden rounded-2xl border border-ink/10 bg-white shadow-[0_18px_60px_rgba(20,32,25,.08)]">
        <div className="border-b border-ink/10 px-6 py-5"><label className="field">Тема письма<input value={subject} maxLength={255} disabled={saving} onChange={e => { setSubject(e.target.value); changed(); }} /></label></div>
        <fieldset disabled={saving || uploading || showCta} className="min-w-0 flex flex-wrap items-center gap-2 border-b border-ink/10 bg-paper/60 px-5 py-3">
          <button onClick={() => editor.chain().focus().toggleBold().run()} className="button" aria-pressed={editor.isActive("bold")}>Жирный</button>
          <button onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()} className="button" aria-pressed={editor.isActive("heading", { level: 2 })}>Заголовок</button>
          <button onClick={() => editor.chain().focus().toggleBulletList().run()} className="button">Список</button>
          <label className="field">Переменная<input list="mail-variables" value={variableName} onChange={e => setVariableName(e.target.value)} /><datalist id="mail-variables">{variables.map(v => <option key={v} value={v} />)}</datalist></label>
          <button className="button" disabled={!/^[a-zA-Z][a-zA-Z0-9_]*$/.test(variableName) || (letterType === "general" && variableName !== "product_name")} onClick={() => editor.chain().focus().insertContent({ type: "variable", attrs: { name: variableName } }).run()}>+ Переменная</button>
          <button onClick={() => { setShowImage(false); openCta(); }} className="button primary">+ CTA</button>
          <button onClick={() => { setShowCta(false); setShowImage(!showImage); }} className="button">+ Фото / видео</button>
          <button className="button" disabled={!editor.can().undo()} onClick={() => editor.chain().focus().undo().run()}>Отменить действие</button>
          <button className="button" disabled={!editor.can().redo()} onClick={() => editor.chain().focus().redo().run()}>Повторить действие</button>
          {editor.isActive("ctaButton") && <div className="flex w-full flex-wrap items-center gap-2" role="group" aria-label="Выбранная кнопка">
            <span className="w-full break-words text-sm">Выбрана: {editor.getAttributes("ctaButton").label}</span>
            <button type="button" className="button" onClick={() => { setShowImage(false); openCta(true); }}>Изменить кнопку</button>
            <button type="button" className="button" disabled={ctaDestination(editor, -1) === null} onClick={() => moveCta(editor, -1)}>↑ Выше</button>
            <button type="button" className="button" disabled={ctaDestination(editor, 1) === null} onClick={() => moveCta(editor, 1)}>↓ Ниже</button>
            <button type="button" className="button" onClick={() => editor.chain().focus().command(({ tr }) => { closeHistory(tr); return true; }).deleteSelection().run()}>Удалить кнопку</button>
          </div>}
        </fieldset>
        {showImage && <ImageUpload editor={editor} workspaceId={workspaceId} onBusy={setUploading} onClose={() => setShowImage(false)} />}
        {showCta && <form onSubmit={insertCta} className="space-y-3 border-b border-ink/10 bg-acid/10 p-5">
          <p className="font-semibold">Кликабельная кнопка: адрес скрыт за текстом</p><label className="field">Текст кнопки<input value={ctaLabel} onChange={e => setCtaLabel(e.target.value)} required maxLength={200} /></label><label className="field">Адрес ссылки<input type="url" value={ctaUrl} onChange={e => setCtaUrl(e.target.value)} placeholder="https://ваш-сайт.ru/встреча" required /></label>
          <p className="hint">{ctaTarget?.edit ? "Изменяется только выбранная кнопка." : "Добавляется новая кнопка в позицию курсора или после выделенной кнопки. У каждой кнопки своя ссылка."}</p>
          {ctaError && <p role="alert" className="error-box">{ctaError}</p>}<button className="button primary" disabled={saving || uploading}>{ctaTarget?.edit ? "Сохранить изменения кнопки" : "Вставить CTA"}</button> <button type="button" className="button" onClick={() => setShowCta(false)}>Отмена</button>
        </form>}
        <div className="email-canvas" style={{ background: emailStyle.background, color: readableText(emailStyle.background), fontFamily: emailFonts[emailStyle.font], fontSize: emailStyle.fontSize, "--email-button-bg": emailStyle.buttonBackground, "--email-button-text": readableText(emailStyle.buttonBackground), "--email-button-radius": `${emailStyle.radius}px` } as CSSProperties}>
          <EditorContent editor={editor} className="editor-content px-7 py-7" />
          <div className="px-7 pb-6"><a href={`${import.meta.env.VITE_API_URL ?? "/api/v1"}/unsubscribe/preview`} target="_blank" rel="noopener noreferrer" className="text-xs underline" style={{ color: "inherit" }}>Отписаться от рассылки</a><p className="mt-2 text-sm opacity-80">Добавляется автоматически в конец каждого письма. Персональная ссылка создаётся при отправке; здесь — безопасный предпросмотр.</p></div>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-ink/10 px-6 py-4"><span className="hint">Добавляйте сколько нужно CTA с разными ссылками. Перетаскивайте за ⠿ в нужное место текста. Или нажмите на кнопку в письме и используйте «Выше / Ниже» на панели. Переход по ссылкам — в предпросмотре.</span><button onClick={compile} disabled={checking || saving || uploading || showCta || !!typeIssue} className="button primary">{checking ? "Проверяем…" : "Проверить письмо"}</button></div>
      </section>
      <aside className="rounded-2xl bg-ink p-6 text-white"><p className="text-xs font-semibold uppercase tracking-[.2em] text-acid">Контроль качества</p><div className="my-7 font-display text-6xl font-bold">{quality?.score ?? "—"}<span className="text-lg text-white/75"> / 100</span></div>
        {quality ? <div className="space-y-3">{[...quality.issues, ...quality.warnings, ...quality.suggestions].map((message, index) => <p key={index} className="rounded-lg border border-white/15 p-3 text-sm">{message}</p>)}<p className="text-sm text-white/80">{quality.words_count} слов</p></div> : <p className="text-sm text-white/80">Проверьте письмо, чтобы увидеть оценку и HTML-предпросмотр.</p>}
        {result && <p className="mt-5 break-words font-mono text-xs text-acid">{result.variables.join(" · ")}</p>}
      </aside>
    </div>
    <section className="panel space-y-4"><h2 className="font-display text-2xl font-bold">Предпросмотр письма</h2>
      <div className="flex flex-wrap items-end gap-3"><div className="grow"><p className="hint">Получатель</p><p>{letterType === "general" ? "Общее письмо — для предпросмотра контакт не нужен. Адреса выбираются при создании рассылки." : contact ? `${contact.full_name || contact.email} · ${contact.company} · ${contact.email}` : "Не выбран — переменные останутся в виде {{имя_поля}}"}</p></div>{letterType === "personalized" && <button className="button" onClick={onChooseContact}>Выбрать контакт из базы</button>}<label className="field">Название продукта<input value={productName} onChange={e => { setProductName(e.target.value); revision.current++; setPreview(""); }} placeholder="Для {{product_name}}" /></label></div>
      {preview ? <><p className="font-semibold">Тема: {previewSubject}</p>{!!previewMissing.length && <p className="error-box">Не заполнены переменные: {previewMissing.join(", ")}. Заполните данные перед использованием шаблона в рассылке.</p>}<iframe title="HTML-предпросмотр письма" srcDoc={preview} sandbox="allow-popups allow-popups-to-escape-sandbox" className="min-h-[480px] w-full rounded-xl border border-ink/15 bg-white" /><button className="button" onClick={downloadHtml}>Скачать HTML письма</button><p className="hint">Это HTML-версия с кликабельным CTA. В обычном текстовом письме скрытые ссылки не поддерживаются.</p></> : <p className="hint">Нажмите «Проверить письмо», чтобы увидеть подстановку данных и проверить ссылку.</p>}
    </section>
  </div>;
}
