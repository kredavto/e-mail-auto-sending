import Placeholder from "@tiptap/extension-placeholder";
import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "../../lib/api";
import { baseVariables, contactVariables, initialDocument, interpolate, safeCtaUrl, stages, type Contact, type MailTemplate, type Stage } from "../../lib/mailing";
import { CaseStudyBlock, CTAButton, EmailImage, SignatureBlock, UnsubscribeBlock, Variable } from "./extensions";
import { ImageUpload } from "./ImageUpload";

type CompileResult = { html: string; text: string; variables: string[]; quality_score: number; warnings: string[] };
type QualityResult = { score: number; issues: string[]; warnings: string[]; suggestions: string[]; words_count: number };
type Props = { workspaceId: string; template: MailTemplate | null; contact: Contact | null; onSaved: (template: MailTemplate) => void; onDirty: (dirty: boolean) => void; onChooseContact: () => void };

export function EmailEditor({ workspaceId, template, contact, onSaved, onDirty, onChooseContact }: Props) {
  const [subject, setSubject] = useState(template?.subject_template ?? "{{first_name}}, идея для {{company}}");
  const [name, setName] = useState(template?.name ?? "");
  const [stage, setStage] = useState<Stage>(template?.category ?? "first_contact");
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
  const [variableName, setVariableName] = useState("first_name");
  const client = useQueryClient();
  const revision = useRef(0);
  function changed() { revision.current++; setResult(null); setQuality(null); setPreview(""); setNotice(""); onDirty(true); }
  const editor = useEditor({
    extensions: [StarterKit, Placeholder.configure({ placeholder: "Напишите короткое, конкретное письмо..." }), Variable, SignatureBlock, CaseStudyBlock, CTAButton, UnsubscribeBlock, EmailImage],
    content: template?.editor_state ?? initialDocument,
    onUpdate: changed,
  });
  useEffect(() => { setPreview(""); setResult(null); setQuality(null); revision.current++; }, [contact]);
  useEffect(() => { editor?.setEditable(!saving && !uploading, false); }, [editor, saving, uploading]);
  async function compile() {
    if (!editor) return;
    setChecking(true); setError(""); setPreview("");
    const currentRevision = revision.current;
    const state = editor.getJSON();
    try {
      const compiled = await api<CompileResult>("/editor/compile", { method: "POST", body: JSON.stringify({ editor_state: state }) });
      const variables: Record<string, string> = contact ? contactVariables(contact, productName) : { product_name: productName };
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
    if (!editor || !workspaceId || uploading) return;
    if (!name.trim() || !subject.trim()) { setError("Заполните название шаблона и тему письма."); return; }
    setSaving(true); setError(""); setNotice("");
    try {
      const saved = await api<MailTemplate>(template && !copy ? `/templates/${template.id}` : "/templates", { workspaceId, method: template && !copy ? "PATCH" : "POST", body: JSON.stringify({ name: name.trim(), category: stage, subject_template: subject, editor_state: editor.getJSON() }) });
      onDirty(false); onSaved(saved); setNotice(`Шаблон сохранён на сервере · версия ${saved.version}`);
      await client.invalidateQueries({ queryKey: ["templates", workspaceId] });
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Ошибка сохранения"); }
    finally { setSaving(false); }
  }
  function insertCta(event: React.FormEvent) {
    event.preventDefault();
    const url = safeCtaUrl(ctaUrl);
    if (!url || !ctaLabel.trim()) { setCtaError("Укажите текст и полный адрес ссылки с https:// или http://."); return; }
    const attrs = { label: ctaLabel.trim(), url };
    if (editor?.isActive("ctaButton")) editor.chain().focus().updateAttributes("ctaButton", attrs).run();
    else editor?.chain().focus().insertContent({ type: "ctaButton", attrs }).run();
    setShowCta(false); setCtaError("");
  }
  function openCta() {
    if (editor?.isActive("ctaButton")) { const attrs = editor.getAttributes("ctaButton"); setCtaLabel(attrs.label); setCtaUrl(attrs.url); }
    setShowCta(true); setCtaError("");
  }
  function downloadHtml() {
    const url = URL.createObjectURL(new Blob([`<!doctype html><html lang="ru"><head><meta charset="UTF-8"><title>Письмо</title></head><body>${preview}</body></html>`], { type: "text/html;charset=utf-8" }));
    const link = document.createElement("a"); link.href = url; link.download = "letter-preview.html"; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  const variables = [...new Set([...baseVariables, ...Object.keys(contact?.custom_fields ?? {}).filter(key => /^[a-zA-Z][a-zA-Z0-9_]*$/.test(key))])];
  if (!editor) return null;
  return <div className="space-y-5">
    <section className="panel flex flex-wrap items-end gap-3">
      <label className="field grow">Название шаблона<input value={name} maxLength={200} onChange={e => { setName(e.target.value); changed(); }} placeholder="Например: первое предложение директору" disabled={saving} /></label>
      <label className="field">Стадия применения<select value={stage} disabled={saving} onChange={e => { setStage(e.target.value as Stage); changed(); }}>{Object.entries(stages).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
      <button className="button primary" onClick={() => save()} disabled={!workspaceId || saving || uploading}>{saving ? "Сохраняем…" : "Сохранить шаблон"}</button>
      {template && <button className="button" onClick={() => save(true)} disabled={!workspaceId || saving || uploading}>Сохранить копию</button>}
      <p className="hint w-full">{template ? `Версия ${template.version}. ` : "Новый шаблон. "}Сохраняйте изменения кнопкой выше.{!workspaceId && " Для сохранения войдите в рабочее пространство."}</p>
    </section>
    {error && <p role="alert" className="error-box">{error}</p>}{notice && <p role="status" className="success-box">{notice}</p>}
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
      <section className="overflow-hidden rounded-2xl border border-ink/10 bg-white shadow-[0_18px_60px_rgba(20,32,25,.08)]">
        <div className="border-b border-ink/10 px-6 py-5"><label className="field">Тема письма<input value={subject} maxLength={255} disabled={saving} onChange={e => { setSubject(e.target.value); changed(); }} /></label></div>
        <fieldset disabled={saving || uploading} className="flex flex-wrap items-center gap-2 border-b border-ink/10 bg-paper/60 px-5 py-3">
          <button onClick={() => editor.chain().focus().toggleBold().run()} className="button" aria-pressed={editor.isActive("bold")}>Жирный</button>
          <button onClick={() => editor.chain().focus().toggleBulletList().run()} className="button">Список</button>
          <label className="field">Переменная<input list="mail-variables" value={variableName} onChange={e => setVariableName(e.target.value)} /><datalist id="mail-variables">{variables.map(v => <option key={v} value={v} />)}</datalist></label>
          <button className="button" disabled={!/^[a-zA-Z][a-zA-Z0-9_]*$/.test(variableName)} onClick={() => editor.chain().focus().insertContent({ type: "variable", attrs: { name: variableName } }).run()}>+ Переменная</button>
          <button onClick={() => { setShowImage(false); openCta(); }} className="button primary">+ CTA</button>
          <button onClick={() => { setShowCta(false); setShowImage(!showImage); }} className="button">+ Изображение</button>
        </fieldset>
        {showImage && <ImageUpload editor={editor} workspaceId={workspaceId} onBusy={setUploading} onClose={() => setShowImage(false)} />}
        {showCta && <form onSubmit={insertCta} className="space-y-3 border-b border-ink/10 bg-acid/10 p-5">
          <p className="font-semibold">Кликабельная кнопка: адрес скрыт за текстом</p><label className="field">Текст кнопки<input value={ctaLabel} onChange={e => setCtaLabel(e.target.value)} required maxLength={200} /></label><label className="field">Адрес ссылки<input type="url" value={ctaUrl} onChange={e => setCtaUrl(e.target.value)} placeholder="https://ваш-сайт.ru/встреча" required /></label>
          {ctaError && <p role="alert" className="error-box">{ctaError}</p>}<button className="button primary">Вставить / обновить CTA</button> <button type="button" className="button" onClick={() => setShowCta(false)}>Отмена</button>
        </form>}
        <EditorContent editor={editor} className="editor-content px-7 py-7" />
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-ink/10 px-6 py-4"><span className="hint">Переход по CTA доступен в предпросмотре ниже.</span><button onClick={compile} disabled={checking || saving || uploading} className="button primary">{checking ? "Проверяем…" : "Проверить письмо"}</button></div>
      </section>
      <aside className="rounded-2xl bg-ink p-6 text-white"><p className="text-xs font-semibold uppercase tracking-[.2em] text-acid">Контроль качества</p><div className="my-7 font-display text-6xl font-bold">{quality?.score ?? "—"}<span className="text-lg text-white/45"> / 100</span></div>
        {quality ? <div className="space-y-3">{[...quality.issues, ...quality.warnings, ...quality.suggestions].map((message, index) => <p key={index} className="rounded-lg border border-white/15 p-3 text-sm">{message}</p>)}<p className="text-sm text-white/60">{quality.words_count} слов</p></div> : <p className="text-sm text-white/60">Проверьте письмо, чтобы увидеть оценку и HTML-предпросмотр.</p>}
        {result && <p className="mt-5 break-words font-mono text-xs text-acid">{result.variables.join(" · ")}</p>}
      </aside>
    </div>
    <section className="panel space-y-4"><h2 className="font-display text-2xl font-bold">Предпросмотр письма</h2>
      <div className="flex flex-wrap items-end gap-3"><div className="grow"><p className="hint">Получатель</p><p>{contact ? `${contact.full_name || contact.email} · ${contact.company} · ${contact.email}` : "Не выбран — переменные останутся в виде {{имя_поля}}"}</p></div><button className="button" onClick={onChooseContact}>Выбрать контакт из базы</button><label className="field">Название продукта<input value={productName} onChange={e => { setProductName(e.target.value); revision.current++; setPreview(""); }} placeholder="Для {{product_name}}" /></label></div>
      {preview ? <><p className="font-semibold">Тема: {previewSubject}</p>{!!previewMissing.length && <p className="error-box">Не заполнены переменные: {previewMissing.join(", ")}. Заполните данные перед использованием шаблона в рассылке.</p>}<iframe title="HTML-предпросмотр письма" srcDoc={preview} sandbox="allow-popups allow-popups-to-escape-sandbox" className="min-h-[480px] w-full rounded-xl border border-ink/15 bg-white" /><button className="button" onClick={downloadHtml}>Скачать HTML письма</button><p className="hint">Это HTML-версия с кликабельным CTA. В обычном текстовом письме скрытые ссылки не поддерживаются.</p></> : <p className="hint">Нажмите «Проверить письмо», чтобы увидеть подстановку данных и проверить ссылку.</p>}
    </section>
  </div>;
}
