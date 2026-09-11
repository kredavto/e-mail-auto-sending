import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { Editor } from "@tiptap/core";
import { closeHistory } from "@tiptap/pm/history";
import { api } from "../../lib/api";

type Signature = { id: string; name: string; html_template: string };
function plainText(html: string) {
  const doc = new DOMParser().parseFromString(html, "text/html");
  doc.querySelectorAll("br").forEach(node => node.replaceWith("\n"));
  doc.querySelectorAll("p").forEach(node => node.append("\n"));
  return doc.body.textContent?.trim() ?? "";
}
function toHtml(text: string) {
  return text.split("\n").map(line => `<p>${line.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;") || "<br>"}</p>`).join("");
}

export function SignaturePanel({ editor, workspaceId, disabled, onBusy }: { editor: Editor; workspaceId: string; disabled: boolean; onBusy: (busy: boolean) => void }) {
  const client = useQueryClient();
  const [editing, setEditing] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const signatures = useQuery({ queryKey: ["signatures", workspaceId], enabled: !!workspaceId, queryFn: () => api<Signature[]>("/signatures", { workspaceId }) });
  const items = Array.isArray(signatures.data) ? signatures.data : [];
  const selected = editor.getJSON().content?.find(node => node.type === "signatureBlock")?.attrs?.signatureId ?? "";
  function apply(signature?: Signature) {
    const ranges: { from: number; to: number }[] = [];
    editor.state.doc.descendants((node, pos) => {
      if (node.type.name === "signatureBlock") { ranges.push({ from: pos, to: pos + node.nodeSize }); return false; }
    });
    editor.chain().command(({ tr }) => {
      closeHistory(tr);
      ranges.reverse().forEach(range => tr.delete(range.from, range.to));
      if (signature) {
        const content = plainText(signature.html_template).split("\n").map(line => ({ type: "paragraph", ...(line ? { content: [{ type: "text", text: line }] } : {}) }));
        tr.insert(tr.doc.content.size, editor.schema.nodeFromJSON({ type: "signatureBlock", attrs: { signatureId: signature.id }, content }));
      }
      return true;
    }).run();
  }
  async function save() {
    if (!name.trim() || !text.trim() || busy || disabled || !workspaceId) return;
    setBusy(true); onBusy(true); setError("");
    try {
      const saved = await api<Signature>(editing ? `/signatures/${editing}` : "/signatures", { workspaceId, method: editing ? "PATCH" : "POST", body: JSON.stringify({ name: name.trim(), html_template: toHtml(text.trim()) }) });
      client.setQueryData<Signature[]>(["signatures", workspaceId], previous => [...(Array.isArray(previous) ? previous : []).filter(item => item.id !== saved.id), saved]);
      apply(saved); setEditing(null);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Не удалось сохранить подпись"); }
    finally { setBusy(false); onBusy(false); }
  }
  return <section className="panel space-y-3" aria-label="Подпись письма">
    <h2 className="font-display text-xl font-bold">Подпись письма</h2>
    <fieldset disabled={disabled || busy || !workspaceId} className="space-y-3">
      <div className="flex flex-wrap items-end gap-3">
        <label className="field grow">Выбрать подпись<select aria-label="Выбрать подпись" value={selected} onChange={e => { apply(items.find(item => item.id === e.target.value)); setEditing(null); }}>
          <option value="">Без сохранённой подписи</option>
          {selected && !items.some(item => item.id === selected) && <option value={selected}>Подпись из шаблона</option>}
          {items.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select></label>
        <button type="button" className="button" onClick={() => { setEditing(""); setName(""); setText(""); setError(""); }}>Создать подпись</button>
        <button type="button" className="button" disabled={!items.some(item => item.id === selected)} onClick={() => { const item = items.find(item => item.id === selected); if (item) { setEditing(item.id); setName(item.name); setText(plainText(item.html_template)); setError(""); } }}>Изменить подпись</button>
      </div>
      {editing !== null && <div className="space-y-3">
        <label className="field">Название подписи<input value={name} maxLength={200} onChange={e => setName(e.target.value)} placeholder="Например: рабочая подпись" /></label>
        <label className="field">Текст подписи<textarea aria-label="Текст подписи" rows={5} maxLength={10000} value={text} onChange={e => setText(e.target.value)} placeholder={"С уважением, Юрий\nКомпания\nТелефон · Email"} /></label>
        <button type="button" className="button primary" disabled={!name.trim() || !text.trim()} onClick={save}>{busy ? "Сохраняем…" : "Сохранить и вставить подпись"}</button>{" "}
        <button type="button" className="button" onClick={() => setEditing(null)}>Отмена</button>
      </div>}
    </fieldset>
    <p className="hint">Подписи сохраняются в рабочем пространстве. Выбранная подпись вставляется в конец письма перед отпиской. Сохраните шаблон письма, чтобы сохранить выбор. Изменение подписи не меняет ранее сохранённые письма.</p>
    {!workspaceId && <p className="hint">Для сохранения подписей войдите в рабочее пространство.</p>}
    {(error || signatures.error) && <p role="alert" className="error-box">{error || "Не удалось загрузить подписи. Обновите страницу."}</p>}
  </section>;
}
