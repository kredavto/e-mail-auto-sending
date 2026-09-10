import type { Editor } from "@tiptap/react";
import { useEffect, useRef, useState } from "react";
import { api } from "../../lib/api";

type Props = { editor: Editor; workspaceId: string; onBusy: (busy: boolean) => void; onClose: () => void };

export function ImageUpload({ editor, workspaceId, onBusy, onClose }: Props) {
  const [file, setFile] = useState<File | null>(null);
  const selectedType = editor.isActive("emailVideo") ? "emailVideo" : "emailImage";
  const [alt, setAlt] = useState(editor.isActive(selectedType) ? editor.getAttributes(selectedType).alt : "");
  const [preview, setPreview] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const request = useRef<AbortController | null>(null);
  const selected = editor.isActive(selectedType);
  const isVideo = file ? file.type === "video/mp4" || /\.mp4$/i.test(file.name) : selected && selectedType === "emailVideo";
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
    const replacing = editor.isActive(selectedType);
    if (!file && !replacing) { setError("Выберите изображение или MP4."); return; }
    setError(""); setBusy(true); onBusy(true);
    const controller = new AbortController(); request.current = controller;
    const selection = { from: editor.state.selection.from, to: editor.state.selection.to };
    try {
      let { src, poster } = editor.getAttributes(selectedType);
      if (file) {
        const form = new FormData(); form.append("file", file);
        const uploaded = await api<{ url: string; poster_url?: string }>(isVideo ? "/files/videos" : "/files/images", { workspaceId, method: "POST", body: form, signal: controller.signal });
        src = uploaded.url;
        poster = uploaded.poster_url;
      }
      if (controller.signal.aborted || editor.isDestroyed) return;
      const attrs = { src, alt: alt.trim(), ...(isVideo ? { poster } : {}) };
      // Restore the selection held while the upload was in progress.
      editor.chain().focus().insertContentAt(selection, { type: isVideo ? "emailVideo" : "emailImage", attrs }).run();
      onClose();
    } catch (reason) {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Не удалось загрузить файл");
    } finally {
      if (!controller.signal.aborted) { setBusy(false); onBusy(false); }
    }
  }

  return <form onSubmit={insert} className="space-y-3 border-b border-ink/10 bg-acid/10 p-5" aria-label="Загрузка фото или видео">
    <h3 className="font-semibold">Фото или видео в письме · ¼ ширины текста</h3>
    <p className="hint">JPEG, PNG или WebP — до 5 МБ и 20 мегапикселей. MP4 — до 20 МБ, 60 секунд и 4K. Пропорции сохраняются. Файлы доступны получателям по ссылке; не загружайте конфиденциальные материалы.</p>
    <label className="field">Файл изображения или видео<input type="file" accept="image/jpeg,image/png,image/webp,video/mp4,.mp4" disabled={busy || !workspaceId} onChange={event => {
      const next = event.target.files?.[0]; setFile(null); setError("");
      if (!next) return;
      const video = next.type === "video/mp4" || /\.mp4$/i.test(next.name);
      if (next.size > (video ? 20 : 5) * 1024 * 1024) { setError(video ? "Максимальный размер MP4 — 20 МБ." : "Максимальный размер изображения — 5 МБ."); event.target.value = ""; return; }
      if (!video && !["image/jpeg", "image/png", "image/webp"].includes(next.type)) { setError("Выберите JPEG, PNG или WebP, либо видео MP4."); event.target.value = ""; return; }
      setFile(next);
    }} /></label>
    {!workspaceId && <p className="error-box">Для загрузки войдите в рабочее пространство.</p>}
    <label className="field">Описание изображения или видео<input value={alt} maxLength={300} disabled={busy} onChange={event => setAlt(event.target.value)} placeholder="Например: обзор продукта" /></label>
    <p className="hint">В письме видео выглядит как превью с кнопкой ▶ и открывается в браузере по нажатию. Описание видно, даже если почтовая программа блокирует картинки. Для замены выделите блок и нажмите «+ Фото / видео».</p>
    {(preview || selected) && (isVideo
      ? <video key={preview || editor.getAttributes(selectedType).src} src={preview || editor.getAttributes(selectedType).src} controls playsInline preload="metadata" aria-label="Предпросмотр видео" className="max-h-64 max-w-full rounded-lg" />
      : <img src={preview || editor.getAttributes(selectedType).src} alt={alt || "Предпросмотр выбранного изображения"} className="max-h-48 max-w-full rounded-lg object-contain" />)}
    {error && <p role="alert" className="error-box">{error}</p>}
    <div className="flex flex-wrap gap-2">
      <button className="button primary" disabled={busy || !workspaceId || (!file && !selected)}>{busy ? "Загружаем и обрабатываем…" : selected ? "Обновить файл" : "Загрузить и вставить"}</button>
      {selected && <button type="button" className="button" disabled={busy} onClick={() => { editor.chain().focus().deleteSelection().run(); onClose(); }}>Удалить файл</button>}
      <button type="button" className="button" disabled={busy} onClick={onClose}>Закрыть</button>
    </div>
  </form>;
}
