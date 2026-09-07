import Placeholder from "@tiptap/extension-placeholder";
import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { useState } from "react";
import { api } from "../../lib/api";
import { CaseStudyBlock, CTAButton, SignatureBlock, UnsubscribeBlock, Variable } from "./extensions";

type CompileResult = { html: string; text: string; variables: string[]; quality_score: number; warnings: string[] };
type QualityResult = { score: number; issues: string[]; warnings: string[]; suggestions: string[]; words_count: number };

const variables = ["first_name", "company", "product_name", "position"];

export function EmailEditor() {
  const [subject, setSubject] = useState("{{first_name}}, идея для {{company}}");
  const [result, setResult] = useState<CompileResult | null>(null);
  const [quality, setQuality] = useState<QualityResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);
  const editor = useEditor({
    extensions: [StarterKit, Placeholder.configure({ placeholder: "Напишите короткое, конкретное письмо..." }), Variable, SignatureBlock, CaseStudyBlock, CTAButton, UnsubscribeBlock],
    content: { type: "doc", content: [{ type: "paragraph", content: [{ type: "text", text: "Здравствуйте, " }, { type: "variable", attrs: { name: "first_name" } }, { type: "text", text: "!" }] }] },
  });

  async function compile() {
    if (!editor) return;
    setChecking(true);
    setError(null);
    try {
      const compiled = await api<CompileResult>("/editor/compile", { method: "POST", body: JSON.stringify({ editor_state: editor.getJSON() }) });
      const report = await api<QualityResult>("/quality/check", { method: "POST", body: JSON.stringify({ html: compiled.html, text: compiled.text, subject }) });
      setResult(compiled);
      setQuality(report);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Не удалось проверить письмо");
    } finally {
      setChecking(false);
    }
  }

  if (!editor) return null;
  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_380px]">
      <section className="overflow-hidden rounded-2xl border border-ink/10 bg-white shadow-[0_18px_60px_rgba(20,32,25,.08)]">
        <div className="border-b border-ink/10 px-6 py-5">
          <label className="mb-2 block text-xs font-semibold uppercase tracking-[.18em] text-ink/50">Тема письма</label>
          <input value={subject} onChange={(event) => setSubject(event.target.value)} className="w-full border-0 bg-transparent font-display text-xl font-semibold outline-none" />
        </div>
        <div className="flex flex-wrap gap-2 border-b border-ink/10 bg-paper/60 px-5 py-3">
          <button onClick={() => editor.chain().focus().toggleBold().run()} className="rounded px-3 py-1.5 text-sm font-semibold hover:bg-white">Жирный</button>
          <button onClick={() => editor.chain().focus().toggleBulletList().run()} className="rounded px-3 py-1.5 text-sm font-semibold hover:bg-white">Список</button>
          {variables.map((name) => <button key={name} onClick={() => editor.chain().focus().insertContent({ type: "variable", attrs: { name } }).run()} className="rounded-full border border-ink/15 bg-white px-3 py-1.5 font-mono text-xs">{`{{${name}}}`}</button>)}
          <button onClick={() => editor.chain().focus().insertContent({ type: "ctaButton", attrs: { label: "Обсудить задачу", url: "https://example.com" } }).run()} className="rounded bg-ink px-3 py-1.5 text-xs font-semibold text-white">+ CTA</button>
        </div>
        <EditorContent editor={editor} className="editor-content px-7 py-7" />
        <div className="flex items-center justify-between border-t border-ink/10 px-6 py-4">
          <span className="text-sm text-ink/55">Автосохранение версии при публикации</span>
          <button onClick={compile} disabled={checking} className="rounded-lg bg-acid px-5 py-2.5 font-display text-sm font-bold text-ink shadow-[3px_3px_0_#142019] transition-transform active:translate-x-0.5 active:translate-y-0.5 disabled:cursor-wait disabled:opacity-60">{checking ? "Проверяем…" : "Проверить письмо"}</button>
        </div>
      </section>
      <aside className="rounded-2xl bg-ink p-6 text-white">
        <p className="text-xs font-semibold uppercase tracking-[.2em] text-acid">Контроль качества</p>
        <div className="my-7 flex items-end gap-2"><span className="font-display text-6xl font-bold">{quality?.score ?? result?.quality_score ?? "—"}</span><span className="pb-2 text-white/45">/ 100</span></div>
        {error && <div className="mb-3 rounded-lg border border-red-300/30 bg-red-400/10 p-3 text-sm text-red-100">{error}</div>}
        <div className="space-y-3">{quality ? <>
          {quality.issues.map((message) => <div key={message} className="rounded-lg border border-red-300/30 bg-red-400/10 p-3 text-sm">Ошибка · {message}</div>)}
          {quality.warnings.map((message) => <div key={message} className="rounded-lg border border-amber-200/25 bg-amber-200/10 p-3 text-sm">Риск · {message}</div>)}
          {quality.suggestions.map((message) => <div key={message} className="rounded-lg border border-white/10 bg-white/5 p-3 text-sm">Совет · {message}</div>)}
          {!quality.issues.length && !quality.warnings.length && <div className="rounded-lg border border-acid/25 bg-acid/10 p-3 text-sm text-acid">Критичных рисков не найдено</div>}
        </> : <p className="text-sm leading-6 text-white/55">Запустите проверку, чтобы увидеть переменные, plain text и риски deliverability.</p>}</div>
        {quality && <p className="mt-4 text-xs text-white/40">{quality.words_count} слов · рекомендуемый диапазон 50–400</p>}
        {result && <div className="mt-6 border-t border-white/10 pt-5"><p className="mb-2 text-xs uppercase tracking-wider text-white/40">Переменные</p><p className="font-mono text-xs text-acid">{result.variables.join(" · ") || "нет"}</p></div>}
      </aside>
    </div>
  );
}
