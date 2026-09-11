import { useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { cellText, contactImportBatches, guessMapping, importFields, MAX_IMPORT_CONTACTS, MAX_IMPORT_FILE_MB, parseCsv, prepareContacts, validateContactFileSize, type ImportedContact } from "../lib/contact-import";
import type { Contact, ContactPage } from "../lib/mailing";

type ImportResult = { created: number; skipped: number; errors: string[] };
export function ContactsPanel({ workspaceId, onPreview }: { workspaceId: string; onPreview: (contact: Contact) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [sheets, setSheets] = useState<string[]>([]);
  const [sheet, setSheet] = useState("");
  const [rows, setRows] = useState<string[][]>([]);
  const [headerRow, setHeaderRow] = useState(1);
  const [mapping, setMapping] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<ImportResult | null>(null);
  const [completed, setCompleted] = useState(false);
  const [progress, setProgress] = useState(0);
  const upload = useRef<{ contacts: ImportedContact[]; workspaceId: string; batches: ReturnType<typeof contactImportBatches>; next: number; processed: number; report: ImportResult } | null>(null);
  const [page, setPage] = useState(1);
  const [encoding, setEncoding] = useState("auto");
  const request = useRef(0);
  const client = useQueryClient();
  const contacts = useQuery({ queryKey: ["contacts", workspaceId, page], enabled: !!workspaceId, queryFn: () => api<ContactPage>(`/contacts?page=${page}&page_size=25`, { workspaceId }) });
  const headers = rows[headerRow - 1] ?? [];
  const prepared = useMemo(() => {
    try { return { ...prepareContacts(rows.slice(headerRow), mapping, file?.name ?? "", headerRow + 1), problem: "" }; }
    catch (reason) { return { contacts: [], errors: [], duplicates: 0, expandedRows: 0, problem: reason instanceof Error ? reason.message : "Проверьте поля" }; }
  }, [rows, headerRow, mapping, file]);
  async function loadFile(nextFile: File, nextSheet = "", nextEncoding = encoding) {
    const ticket = ++request.current;
    setBusy(true); setError(""); setResult(null); setCompleted(false); setProgress(0); upload.current = null; setRows([]); setMapping([]); setFile(nextFile);
    try {
      validateContactFileSize(nextFile.size);
      let parsed: string[][];
      if (/\.xlsx$/i.test(nextFile.name)) {
        const { default: readXlsxFile } = await import("read-excel-file/browser");
        const workbook = await readXlsxFile(nextFile);
        const names = workbook.map(item => item.sheet);
        const selected = nextSheet || names[0];
        parsed = (workbook.find(item => item.sheet === selected)?.data ?? []).map(row => row.map(cellText));
        if (ticket !== request.current) return;
        setSheets(names); setSheet(selected);
      } else if (/\.csv$/i.test(nextFile.name)) {
        const bytes = await nextFile.arrayBuffer();
        let text: string;
        if (nextEncoding === "auto") {
          try { text = new TextDecoder("utf-8", { fatal: true }).decode(bytes); }
          catch { text = new TextDecoder("windows-1251").decode(bytes); }
        } else text = new TextDecoder(nextEncoding).decode(bytes);
        parsed = parseCsv(text);
        if (ticket !== request.current) return;
        setSheets([]); setSheet("");
      } else throw new Error("Поддерживаются .xlsx и .csv. Старый .xls сохраните в Excel как .xlsx.");
      while (parsed.length && parsed[parsed.length - 1].every(value => !value.trim())) parsed.pop();
      if (parsed.length > MAX_IMPORT_CONTACTS + 1 || parsed.some(row => row.length > 100)) throw new Error(`Лимит: ${MAX_IMPORT_CONTACTS} строк контактов и 100 колонок. Разделите файл.`);
      if (parsed.length < 2) throw new Error("Нужны строка заголовков и хотя бы одна строка данных.");
      setRows(parsed); setHeaderRow(1); setMapping(guessMapping(parsed[0]));
    } catch (reason) { if (ticket === request.current) setError(reason instanceof Error ? reason.message : "Не удалось прочитать файл"); }
    finally { if (ticket === request.current) setBusy(false); }
  }
  async function importContacts() {
    if (busy || !workspaceId || prepared.problem || !prepared.contacts.length || (completed && result)) return;
    setBusy(true); setError(""); setCompleted(false);
    try {
      if (upload.current?.contacts !== prepared.contacts || upload.current.workspaceId !== workspaceId) {
        upload.current = null; setResult(null); setProgress(0);
        upload.current = { contacts: prepared.contacts, workspaceId, batches: contactImportBatches(prepared.contacts), next: 0, processed: 0, report: { created: 0, skipped: 0, errors: [] } };
      }
      const run = upload.current;
      while (run.next < run.batches.length) {
        const batch = run.batches[run.next];
        const report = await api<ImportResult>("/contacts/bulk", { workspaceId, method: "POST", body: batch.body });
        run.report = { created: run.report.created + report.created, skipped: run.report.skipped + report.skipped, errors: [...run.report.errors, ...report.errors.map(message => `Порция ${run.next + 1}: ${message}`)] };
        run.next++; run.processed += batch.count;
        setProgress(run.processed); setResult(run.report);
      }
      setCompleted(true);
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : "Ошибка импорта.";
      const run = upload.current;
      setError(`${message} Подтверждено создано: ${run?.report.created ?? 0}. ${run ? "Нажмите импорт ещё раз, чтобы продолжить с прерванной порции. При потере ответа сервера часть этой порции могла сохраниться; существующие email будут пропущены." : "Контакты не отправлены."}`);
    } finally {
      await client.invalidateQueries({ queryKey: ["contacts", workspaceId] });
      setBusy(false);
    }
  }
  return <div className="space-y-5">
    <section className="panel space-y-4"><h2 className="font-display text-2xl font-bold">Загрузить базу контактов</h2>
      <p className="hint">Excel .xlsx или CSV · до {MAX_IMPORT_FILE_MB} МБ / {MAX_IMPORT_CONTACTS} контактов после разделения email. До {MAX_IMPORT_CONTACTS} строк данных и отдельная строка заголовков. В одной ячейке можно указать несколько адресов через запятую, точку с запятой, пробел или перенос строки. Каждый email станет отдельным контактом с данными исходной строки. Файл разбирается в браузере; сохранение — после подтверждения. Также действуют лимиты вашего тарифа.</p>
      <p className="hint">Большая база сохраняется порциями с показом прогресса. Не закрывайте вкладку до завершения. При прерывании уже сохранённые контакты остаются в базе; повторное нажатие импорта в этой вкладке продолжит обработку.</p>
      <label className="field">Файл контактов<input type="file" accept=".xlsx,.csv" disabled={busy} onChange={e => { const selected = e.target.files?.[0]; if (selected) void loadFile(selected); }} /></label>
      {error && <p role="alert" className="error-box">{error}</p>}
      {busy && <p role="status">{upload.current ? `Сохранение: ${progress} из ${prepared.contacts.length}. Не закрывайте вкладку.` : "Обрабатываем…"}</p>}
      {!!rows.length && <>
        <div className="flex flex-wrap gap-3">
          {!!sheets.length && <label className="field">Лист Excel<select disabled={busy} value={sheet} onChange={e => file && void loadFile(file, e.target.value)}>{sheets.map(name => <option key={name}>{name}</option>)}</select></label>}
          {!sheets.length && <label className="field">Кодировка CSV<select disabled={busy} value={encoding} onChange={e => { setEncoding(e.target.value); if (file) void loadFile(file, "", e.target.value); }}><option value="auto">Автоматически</option><option value="utf-8">UTF-8</option><option value="windows-1251">Windows-1251</option></select></label>}
          <label className="field">Строка заголовков<input type="number" min={1} max={rows.length - 1} value={headerRow} disabled={busy} onChange={e => { const index = Math.max(1, Math.min(rows.length - 1, Number(e.target.value))); setHeaderRow(index); setMapping(guessMapping(rows[index - 1])); setResult(null); }} /></label>
        </div>
        <p className="hint">Проверьте назначение колонок. Для других данных выберите «Дополнительное поле» и задайте имя переменной, например city или inn. «Не импортировать» не сохраняет колонку.</p>
        <div className="overflow-x-auto"><table className="data-table"><thead><tr><th>Колонка файла</th><th>Поле контакта</th><th>Пример</th></tr></thead><tbody>{headers.map((header, index) => <tr key={index}>
          <td>{header || `Колонка ${index + 1}`}</td><td><select aria-label={`Поле колонки ${index + 1}`} disabled={busy} value={mapping[index]?.startsWith("custom:") ? "custom" : mapping[index] ?? ""} onChange={e => { setMapping(current => current.map((item, i) => i === index ? e.target.value === "custom" ? `custom:field_${index + 1}` : e.target.value : item)); setResult(null); }}><option value="">Не импортировать</option>{Object.entries(importFields).map(([key, label]) => <option key={key} value={key}>{label}</option>)}<option value="custom">Дополнительное поле</option></select>
            {mapping[index]?.startsWith("custom:") && <label className="field mt-2">Имя переменной<input value={mapping[index].slice(7)} disabled={busy} onChange={e => { setMapping(current => current.map((item, i) => i === index ? `custom:${e.target.value}` : item)); setResult(null); }} /></label>}</td>
          <td className="max-w-sm break-words">{rows[headerRow]?.[index] || "—"}</td>
        </tr>)}</tbody></table></div>
        {prepared.problem && <p className="error-box">{prepared.problem}</p>}
        <p>Готово к импорту: <strong>{prepared.contacts.length}</strong> · Дубли в файле: {prepared.duplicates} · Строки с ошибками: {prepared.errors.length}</p>
        {!!prepared.expandedRows && <p className="hint">Строк с несколькими email: {prepared.expandedRows}. Каждый уникальный корректный адрес показан отдельным контактом; остальные данные строки сохранены. Для дублей используются данные первого корректного вхождения.</p>}
        {!!prepared.errors.length && <details><summary>Показать ошибки строк</summary><ul className="max-h-48 overflow-auto text-sm">{prepared.errors.map(message => <li key={message}>{message}</li>)}</ul></details>}
        {!!prepared.contacts.length && <div className="overflow-x-auto"><table className="data-table"><caption className="mb-2 text-left font-semibold">Предпросмотр — первые 5 контактов</caption><thead><tr><th>Email</th><th>Ф.И.О.</th><th>Организация</th><th>Должность</th><th>Доп. поля</th></tr></thead><tbody>{prepared.contacts.slice(0, 5).map(contact => <tr key={contact.email}><td>{contact.email}</td><td>{contact.full_name}</td><td>{contact.company}</td><td>{contact.position}</td><td>{Object.entries(contact.custom_fields).map(([key, value]) => `${key}: ${value}`).join(" · ")}</td></tr>)}</tbody></table></div>}
        <button className="button primary" onClick={importContacts} disabled={busy || !workspaceId || !prepared.contacts.length || !!prepared.problem || (completed && !!result)}>Импортировать {prepared.contacts.length} контактов</button>
        {!workspaceId && <p className="hint">Для сохранения войдите и выберите рабочее пространство выше.</p>}
        {result && <div role="status" className="success-box">Создано: {result.created}. Уже были в базе: {result.skipped}. Ошибки сервера: {result.errors.length}.{!!result.errors.length && <ul>{result.errors.map((message, index) => <li key={index}>{message}</li>)}</ul>}</div>}
      </>}
    </section>
    <section className="panel"><h2 className="mb-4 font-display text-2xl font-bold">База контактов {contacts.data ? `· ${contacts.data.total}` : ""}</h2>
      {contacts.error && <p role="alert" className="error-box">{contacts.error.message}</p>}
      {contacts.isFetching && <p>Загрузка…</p>}
      {contacts.data && <><div className="overflow-x-auto"><table className="data-table"><thead><tr><th>Email</th><th>Ф.И.О.</th><th>Организация</th><th>Телефон</th><th>Статус</th><th>Письмо</th></tr></thead><tbody>{contacts.data.items.map(contact => <tr key={contact.id}><td>{contact.email}</td><td>{contact.full_name || "—"}</td><td>{contact.company || "—"}</td><td>{contact.phone || "—"}</td><td>{contact.status}</td><td><button className="button" onClick={() => onPreview(contact)}>Подставить в письмо</button></td></tr>)}</tbody></table></div>
      {!contacts.data.total && <p className="hint">Контактов пока нет. Загрузите файл выше.</p>}
      <div className="mt-4 flex items-center gap-3"><button className="button" disabled={page === 1} onClick={() => setPage(page - 1)}>Назад</button><span>Страница {page} / {Math.max(1, Math.ceil(contacts.data.total / 25))}</span><button className="button" disabled={page * 25 >= contacts.data.total} onClick={() => setPage(page + 1)}>Далее</button></div></>}
    </section>
  </div>;
}
