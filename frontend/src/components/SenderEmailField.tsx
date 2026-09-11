import { useId, useRef, useState } from "react";

export function SenderEmailField({ value, onChange, addresses, loading, error }: { value: string; onChange: (value: string) => void; addresses: string[]; loading: boolean; error?: string }) {
  const id = useId();
  const input = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const options = [...new Set(addresses.map(email => email.trim().toLowerCase()).filter(Boolean))].sort();
  function select(email: string) { onChange(email); setOpen(false); setActive(-1); input.current?.focus(); }
  return <div className="relative min-w-0 space-y-2" onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) { setOpen(false); setActive(-1); } }}>
    <label className="field" htmlFor={id}>Email отправителя</label>
    <div className="flex gap-2">
      <input ref={input} id={id} type="email" required maxLength={254} autoComplete="off" role="combobox" aria-expanded={open} aria-controls={`${id}-options`} aria-autocomplete="none" aria-activedescendant={open && active >= 0 && active < options.length ? `${id}-option-${active}` : undefined} aria-describedby={`${id}-help`} value={value} placeholder="Выберите или введите новый email" className="min-w-0 flex-1 rounded-lg border border-ink/20 px-3 py-2 text-base" onChange={event => { onChange(event.target.value); setActive(-1); }} onKeyDown={event => {
        if (event.key === "Escape") { setOpen(false); setActive(-1); }
        if (event.key === "ArrowDown" || event.key === "ArrowUp") { event.preventDefault(); setOpen(true); setActive(previous => !options.length ? -1 : previous < 0 ? (event.key === "ArrowDown" ? 0 : options.length - 1) : (previous + (event.key === "ArrowDown" ? 1 : -1) + options.length) % options.length); }
        if (event.key === "Enter" && open) { event.preventDefault(); if (options[active]) select(options[active]); else setOpen(false); }
      }} />
      <button type="button" className="button" aria-label="Выбрать адрес отправителя" aria-expanded={open} aria-controls={`${id}-options`} onClick={() => { setOpen(!open); setActive(-1); input.current?.focus(); }}>▾</button>
    </div>
    {open && <div className="absolute z-10 w-full rounded-lg border border-ink/20 bg-white p-2 shadow-lg">
      <ul id={`${id}-options`} role="listbox" aria-label="Адреса отправителя" className="max-h-48 overflow-y-auto">{options.map((email, index) => <li key={email} id={`${id}-option-${index}`} role="option" aria-selected={active === index} className={`cursor-pointer break-all rounded px-3 py-2 text-sm hover:bg-paper ${active === index ? "bg-paper" : ""}`} onMouseDown={event => event.preventDefault()} onClick={() => select(email)}>{email}</li>)}</ul>
      {!options.length && <p className="hint p-2">{loading ? "Загружаем адреса…" : "Сохранённых адресов пока нет. Введите новый email в поле выше."}</p>}
    </div>}
    <p id={`${id}-help`} className="hint">Можно выбрать адрес из прошлых рассылок или ввести новый. После сохранения черновика он появится в списке. Используйте адрес, разрешённый вашим SMTP/SES; это поле не подключает почтовый ящик.</p>
    {error && <p role="status" className="hint">Не удалось загрузить список адресов. Можно ввести email вручную.</p>}
  </div>;
}
