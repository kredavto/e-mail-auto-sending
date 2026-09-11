import { useEffect, useRef, useState } from "react";
import { defaultEmailStyle, paletteFromPixels, readableText, stylePresets, type EmailStyle } from "../../lib/email-style";

export function EmailStylePanel({ value, onChange, disabled }: { value: EmailStyle; onChange: (style: EmailStyle) => void; disabled: boolean }) {
  const [reference, setReference] = useState<{ url: string; name: string; colors: string[] } | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const generation = useRef(0);
  useEffect(() => () => { generation.current++; }, []);
  useEffect(() => () => { if (reference) URL.revokeObjectURL(reference.url); }, [reference]);
  async function loadReference(file?: File) {
    const current = ++generation.current;
    setError(""); setLoading(false);
    if (!file) return;
    if (!["image/png", "image/jpeg", "image/webp"].includes(file.type) || file.size > 5 * 1024 * 1024) { setError("Выберите PNG, JPEG или WebP размером до 5 МБ."); return; }
    setLoading(true);
    const url = URL.createObjectURL(file);
    let retained = false;
    try {
      const img = new Image(); img.src = url;
      await img.decode();
      if (img.naturalWidth * img.naturalHeight > 20_000_000) throw new Error("Референс должен быть не больше 20 мегапикселей.");
      const canvas = document.createElement("canvas");
      const scale = Math.min(1, 160 / Math.max(img.naturalWidth, img.naturalHeight));
      canvas.width = Math.max(1, Math.round(img.naturalWidth * scale)); canvas.height = Math.max(1, Math.round(img.naturalHeight * scale));
      const context = canvas.getContext("2d", { willReadFrequently: true });
      if (!context) throw new Error("Браузер не поддерживает анализ изображения.");
      context.drawImage(img, 0, 0, canvas.width, canvas.height);
      const colors = paletteFromPixels(context.getImageData(0, 0, canvas.width, canvas.height).data);
      if (!colors.length) throw new Error("В референсе нет непрозрачных цветов.");
      if (current !== generation.current) return;
      setReference({ url, name: file.name, colors }); retained = true;
    } catch (reason) { if (current === generation.current) setError(reason instanceof Error ? reason.message : "Не удалось прочитать изображение."); }
    finally { if (!retained) URL.revokeObjectURL(url); if (current === generation.current) setLoading(false); }
  }
  const update = (patch: Partial<EmailStyle>) => onChange({ ...value, ...patch });
  return <section className="panel space-y-4" aria-label="Оформление письма">
    <h2 className="font-display text-2xl font-bold">Оформление письма</h2>
    <p className="hint">Фон применяется к области текста письма. Цвет букв подбирается автоматически для контраста. Текст, кнопки и ссылки сохраняются.</p>
    <fieldset disabled={disabled} className="min-w-0 space-y-4">
      <legend className="mb-2 font-semibold">Палитра фонов</legend>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">{stylePresets.map(([name, background, buttonBackground]) => <button key={name} type="button" className="rounded-xl border border-stone-400 p-3 text-left text-sm" aria-pressed={value.background === background && value.buttonBackground === buttonBackground} style={{ background, color: readableText(background) }} onClick={() => update({ background, buttonBackground })}>{name}{value.background === background && value.buttonBackground === buttonBackground ? " ✓" : ""}</button>)}</div>
      <div className="flex flex-wrap items-end gap-4">
        <label className="field">Свой фон<input aria-label="Свой фон" type="color" style={{ width: 72, height: 44, padding: 4 }} value={value.background} onChange={e => update({ background: e.target.value })} /></label>
        <label className="field">Цвет CTA-кнопок<input aria-label="Цвет CTA-кнопок" type="color" style={{ width: 72, height: 44, padding: 4 }} value={value.buttonBackground} onChange={e => update({ buttonBackground: e.target.value })} /></label>
        <label className="field">Шрифт письма<select value={value.font} onChange={e => update({ font: e.target.value as EmailStyle["font"] })}><option value="sans">Arial — нейтральный</option><option value="serif">Georgia — классический</option><option value="modern">Verdana — современный</option></select></label>
        <label className="field">Размер текста<select value={value.fontSize} onChange={e => update({ fontSize: Number(e.target.value) })}>{[14, 16, 18, 20].map(size => <option key={size} value={size}>{size} px</option>)}</select></label>
        <label className="field">Скругление кнопок<select value={value.radius} onChange={e => update({ radius: Number(e.target.value) })}>{[0, 6, 12, 24].map(size => <option key={size} value={size}>{size} px</option>)}</select></label>
        <button type="button" className="button" onClick={() => onChange({ ...defaultEmailStyle })}>Сбросить оформление</button>
      </div>
      <div className="space-y-3 rounded-xl border border-ink/15 p-4">
        <h3 className="font-semibold">Референс оформления</h3>
        <p className="hint">Загрузите скриншот письма или изображение: PNG, JPEG, WebP, до 5 МБ и 20 Мп. Анализ цветов выполняется локально. Файл не отправляется на сервер и не вставляется в письмо. После закрытия редактора его нужно загрузить снова; применённые настройки сохраняются с шаблоном.</p>
        <label className="field">Загрузить референс<input type="file" accept="image/png,image/jpeg,image/webp" onChange={e => { void loadReference(e.target.files?.[0]); e.target.value = ""; }} /></label>
        {loading && <p role="status">Извлекаем палитру…</p>}
        {error && <p role="alert" className="error-box">{error}</p>}
        {reference && <div className="space-y-3">
          <img src={reference.url} alt="Референс оформления письма" className="max-h-64 max-w-full rounded-lg object-contain" />
          <p className="break-all text-sm">{reference.name}</p>
          <p className="hint">Найденные цвета: нажмите оттенок, чтобы сделать его фоном. Это перенос палитры, не копирование вёрстки или текста.</p>
          <div className="flex flex-wrap gap-2">{reference.colors.map(color => <button type="button" key={color} aria-label={`Фон из референса ${color}`} className="rounded-lg border border-stone-400 p-3 text-sm" style={{ background: color, color: readableText(color) }} onClick={() => update({ background: color })}>{color}</button>)}</div>
          <div className="flex flex-wrap gap-2"><button type="button" className="button primary" disabled={loading} onClick={() => update({ background: reference.colors[0], buttonBackground: reference.colors[1] ?? readableText(reference.colors[0]) })}>Применить палитру референса</button><button type="button" className="button" onClick={() => { generation.current++; setLoading(false); setReference(null); setError(""); }}>Убрать референс</button></div>
        </div>}
      </div>
    </fieldset>
  </section>;
}
