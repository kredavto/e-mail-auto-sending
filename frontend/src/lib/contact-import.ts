import Papa from "papaparse";

export const MAX_IMPORT_FILE_MB = 50;
export const MAX_IMPORT_FILE_BYTES = MAX_IMPORT_FILE_MB * 1024 * 1024;
export function validateContactFileSize(size: number): void {
  if (size > MAX_IMPORT_FILE_BYTES) throw new Error(`Файл больше ${MAX_IMPORT_FILE_MB} МБ. Разделите базу на несколько файлов.`);
}

export const importFields: Record<string, string> = {
  email: "Email (обязательно)", full_name: "Ф.И.О. руководителя", last_name: "Фамилия", first_name: "Имя", patronymic: "Отчество",
  company: "Организация", position: "Должность", phone: "Телефон", industry: "Отрасль", current_site_url: "Сайт",
  company_size: "Размер компании", annual_revenue_tier: "Выручка", tags: "Теги",
};
const aliases: Record<string, string[]> = {
  email: ["email", "e-mail", "e mail", "e-mal", "почта", "электронная почта", "email адрес", "email address"],
  full_name: ["full name", "full_name", "фио", "ф.и.о.", "руководитель", "фио руководителя", "ф.и.о. руководителя", "директор", "генеральный директор", "contact name"],
  first_name: ["first_name", "first name", "имя"], last_name: ["last_name", "last name", "фамилия"], patronymic: ["отчество", "patronymic", "middle name"],
  company: ["company", "company name", "компания", "организация", "наименование организации", "наименование компании"],
  position: ["position", "job title", "должность"], phone: ["phone", "телефон", "телефон руководителя"],
  current_site_url: ["website", "site", "сайт", "current_site_url"], industry: ["industry", "отрасль"],
  company_size: ["company_size", "размер компании", "сотрудников"], annual_revenue_tier: ["annual_revenue_tier", "выручка"], tags: ["tags", "теги"],
};
const normalized = (value: string) => value.toLowerCase().replace(/[\s._-]+/g, "");
export function guessMapping(headers: string[]): string[] {
  const used = new Set<string>();
  return headers.map(header => {
    const field = Object.keys(aliases).find(key => !used.has(key) && aliases[key].some(alias => normalized(alias) === normalized(header)));
    if (field) { used.add(field); return field; }
    return "";
  });
}
export function cellText(value: unknown): string {
  return value instanceof Date ? value.toISOString().slice(0, 10) : String(value ?? "").trim();
}
export function parseCsv(text: string): string[][] {
  const input = text.replace(/^\uFEFF/, "").replace(/^sep=([^\r\n])\r?\n/i, "");
  const declared = text.replace(/^\uFEFF/, "").match(/^sep=([^\r\n])\r?\n/i)?.[1];
  const result = Papa.parse<string[]>(input, { delimiter: declared ?? "", skipEmptyLines: false });
  const errors = result.errors.filter(error => error.code !== "UndetectableDelimiter");
  if (errors.length) throw new Error(`Ошибка CSV: ${errors[0].message}`);
  return result.data.map(row => row.map(cellText));
}
export type ImportedContact = { email: string; full_name: string; company: string; position: string; source: string; tags: string[]; custom_fields: Record<string, string>; [key: string]: unknown };
export const MAX_IMPORT_CONTACTS = 10000;
export function splitEmailCell(value: string): string[] {
  return value.split(/[,;\s]+/u).map(email => email.trim().toLowerCase()).filter(Boolean);
}
function validEmail(email: string): boolean {
  const parts = email.split("@");
  if (parts.length !== 2 || email.length > 254) return false;
  const [local, domain] = parts;
  return !!local && local.length <= 64 && !local.startsWith(".") && !local.endsWith(".") && !local.includes("..")
    && /^[\p{L}\p{N}.!#$%&'*+/=?^_`{|}~-]+$/u.test(local)
    && domain.includes(".") && domain.split(".").every(label => label.length <= 63 && /^[\p{L}\p{N}](?:[\p{L}\p{N}-]*[\p{L}\p{N}])?$/u.test(label));
}
export function prepareContacts(rows: string[][], mapping: string[], filename: string, firstDataRow: number) {
  const targets = mapping.filter(Boolean);
  if (!targets.includes("email")) throw new Error("Укажите колонку с email.");
  if (new Set(targets).size !== targets.length) throw new Error("Одно поле нельзя назначать нескольким колонкам.");
  for (const field of targets) {
    if (!importFields[field] && !/^custom:[a-zA-Z][a-zA-Z0-9_]*$/.test(field)) throw new Error("Имя дополнительного поля: латинские буквы, цифры и подчёркивание; начните с буквы.");
    if (field.startsWith("custom:") && (importFields[field.slice(7)] || ["product_name", "constructor", "prototype"].includes(field.slice(7)))) throw new Error("Имя дополнительного поля совпадает со встроенной переменной. Выберите другое имя.");
  }
  const seen = new Set<string>();
  const contacts: ImportedContact[] = [];
  const errors: string[] = [];
  let duplicates = 0;
  let expandedRows = 0;
  rows.forEach((row, index) => {
    if (!row.some(value => value.trim())) return;
    const values: Record<string, string> = {};
    const custom: Record<string, string> = {};
    mapping.forEach((field, column) => {
      if (field.startsWith("custom:")) custom[field.slice(7)] = cellText(row[column]);
      else if (field) values[field] = cellText(row[column]);
    });
    const emails = splitEmailCell(values.email ?? "");
    if (!emails.length) { errors.push(`Строка ${firstDataRow + index}: отсутствует email.`); return; }
    if (emails.length > 1) expandedRows++;
    const { first_name, last_name, patronymic, tags, ...rest } = values;
    const fullName = values.full_name || [last_name, first_name, patronymic].filter(Boolean).join(" ");
    const limits: Record<string, number> = { full_name: 255, first_name: 100, last_name: 100, patronymic: 100, company: 255, position: 100, phone: 50, current_site_url: 255, industry: 100, company_size: 50, annual_revenue_tier: 50 };
    const longField = Object.keys(limits).find(key => (key === "full_name" ? fullName : values[key] ?? "").length > limits[key]);
    if (longField) { errors.push(`Строка ${firstDataRow + index}: поле «${importFields[longField]}» длиннее ${limits[longField]} символов.`); return; }
    const invalid = emails.filter(email => !validEmail(email));
    if (invalid.length) errors.push(`Строка ${firstDataRow + index}: некорректные email пропущены: ${invalid.join(", ")}. Корректные адреса этой строки будут импортированы.`);
    for (const email of emails.filter(validEmail)) {
      if (seen.has(email)) { duplicates++; continue; }
      if (contacts.length >= MAX_IMPORT_CONTACTS) throw new Error(`После разделения email получилось больше ${MAX_IMPORT_CONTACTS} контактов. Разделите файл; адреса не были обрезаны или отправлены на сервер.`);
      seen.add(email);
      contacts.push({ ...rest, ...(first_name ? { first_name } : {}), ...(last_name ? { last_name } : {}), ...(patronymic ? { patronymic } : {}), email, full_name: fullName, company: values.company || "", position: values.position || "", source: `import:${filename}`.slice(0, 50), tags: tags ? tags.split(/[,;]/).map(x => x.trim()).filter(Boolean) : [], custom_fields: { ...custom } });
    }
  });
  return { contacts, errors, duplicates, expandedRows };
}
