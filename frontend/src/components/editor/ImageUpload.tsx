import type { Editor } from "@tiptap/react";
import { useEffect, useRef, useState } from "react";
import { api } from "../../lib/api";

type Props = { editor: Editor; workspaceId: string; onBusy: (busy: boolean) => void; onClose: () => void };

export function ImageUpload({ editor, workspaceId, onBusy, onClose }: Props) {
  const [file, setFile] = useState<File | null>(null);
  const [alt, setAlt] = useState(editor.isActive("emailImage") ? editor.getAttributes("emailImage").alt : "");
  const [preview, setPreview] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const request = useRef<AbortController | null>(null);
  const selected = editor.isActive("emailImage");
  useEffect(() => () => { request.current?.abort(); }, []);
  useEffect(() => {
    if (!file) { setPreview(""); return; }
    const url = URL.createObjectURL(file);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  async function insert(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    const replacing = editor.isActive("emailImage");
    if (!file && !replacing) { setError("Выберите изображение."); return; }
    setError(""); setBusy(true); onBusy(true);
    const controller = new AbortController(); request.current = controller;
    const selection = { from: editor.state.selection.from, to: editor.state.selection.to };
    try {
      let src = editor.getAttributes("emailImage").src;
      if (file) {
        const form = new FormData(); form.append("file", file);
        const uploaded = await api<{ url: string }>("/files/images", { workspaceId, method: "POST", body: form, signal: controller.signal });
        src = uploaded.url;
      }
      if (controller.signal.aborted || editor.isDestroyed) return;
      const attrs = { src, alt: alt.trim() };
      // Restore the selection held while the upload was in progress.
      editor.chain().focus().insertContentAt(selection, { type: "emailImage", attrs }).run();
      onClose();
    } catch (reason) {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Не удалось загрузить изображение");
    } finally {
      if (!controller.signal.aborted) { setBusy(false); onBusy(false); }
    }
  }

  return <form onSubmit={insert} className="space-y-3 border-b border-ink/10 bg-acid/10 p-5" aria-label="Загрузка изображения">
    <h3 className="font-semibold">Изображение в письме · ¼ ширины текста</h3>
    <p className="hint">JPEG, PNG или WebP, до 5 МБ и 20 мегапикселей. Пропорции сохраняются. Фотография будет доступна получателям по ссылке; не загружайте конфиденциальные изображения.</p>
    <label className="field">Файл изображения<input type="file" accept="image/jpeg,image/png,image/webp" disabled={busy || !workspaceId} onChange={event => {
      const next = event.target.files?.[0]; setFile(null); setError("");
      if (!next) return;
      if (next.size > 5 * 1024 * 1024) { setError("Максимальный размер изображения — 5 МБ."); event.target.value = ""; return; }
      if (!["image/jpeg", "image/png", "image/webp"].includes(next.type)) { setError("Выберите JPEG, PNG или WebP."); event.target.value = ""; return; }
      setFile(next);
    }} /></label>
    {!workspaceId && <p className="error-box">Для загрузки войдите в рабочее пространство.</p>}
    <label className="field">Описание изображения<input value={alt} maxLength={300} disabled={busy} onChange={event => setAlt(event.target.value)} placeholder="Например: фотография продукта" /></label>
    <p className="hint">Описание отображается, если почтовая программа блокирует картинки. Выберите изображение в письме и нажмите «+ Изображение», чтобы заменить его.</p>
    {(preview || selected) && <img src={preview || editor.getAttributes("emailImage").src} alt={alt || "Предпросмотр выбранного изображения"} className="max-h-48 max-w-full rounded-lg object-contain" />}
    {error && <p role="alert" className="error-box">{error}</p>}
    <div className="flex flex-wrap gap-2">
      <button className="button primary" disabled={busy || !workspaceId || (!file && !selected)}>{busy ? "Загружаем…" : selected ? "Обновить изображение" : "Загрузить и вставить"}</button>
      {selected && <button type="button" className="button" disabled={busy} onClick={() => { editor.chain().focus().deleteSelection().run(); onClose(); }}>Удалить изображение</button>}
      <button type="button" className="button" disabled={busy} onClick={onClose}>Закрыть</button>
    </div>
  </form>;
}
