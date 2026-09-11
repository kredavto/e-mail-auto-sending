import { describe, expect, it } from "vitest";
import { contactImportBatches, guessMapping, IMPORT_BATCH_BYTES, MAX_IMPORT_CONTACTS, MAX_IMPORT_FILE_BYTES, parseCsv, prepareContacts, splitEmailCell, validateContactFileSize } from "./contact-import";
import { contactVariables, safeCtaUrl, type Contact } from "./mailing";

describe("contact import", () => {
  it.each([10 * 1024 * 1024 + 1, 50 * 1024 * 1024 - 1, 50 * 1024 * 1024])("accepts file size %i up to 50 MiB inclusive", size => {
    expect(MAX_IMPORT_FILE_BYTES).toBe(50 * 1024 * 1024);
    expect(() => validateContactFileSize(size)).not.toThrow();
  });
  it("rejects files above 50 MiB", () => {
    expect(() => validateContactFileSize(50 * 1024 * 1024 + 1)).toThrow("Файл больше 50 МБ");
  });
  it.each([",", ";", " ", "\n", "\r\n", "\t", "\u00a0"])("splits multiple addresses separated by %j", separator => {
    const result = prepareContacts([[`INFO@example.com${separator}sales@example.com${separator}office@example.com`, "Иванов Иван", "Компания", "Москва", "vip;crm"]], ["email", "full_name", "company", "custom:city", "tags"], "база.xlsx", 2);
    expect(result.contacts.map(c => c.email)).toEqual(["info@example.com", "sales@example.com", "office@example.com"]);
    expect(result.errors).toEqual([]);
    expect(result.expandedRows).toBe(1);
    for (const contact of result.contacts) expect(contact).toMatchObject({ full_name: "Иванов Иван", company: "Компания", custom_fields: { city: "Москва" }, tags: ["vip", "crm"] });
  });
  it("skips duplicates within and across cells and keeps good addresses beside invalid ones", () => {
    const result = prepareContacts([["a@example.com;bad;A@example.com;b@example.com", "Первая"], ["B@example.com, c@example.com", "Вторая"]], ["email", "company"], "", 2);
    expect(result.contacts.map(c => c.email)).toEqual(["a@example.com", "b@example.com", "c@example.com"]);
    expect(result.contacts.map(c => c.company)).toEqual(["Первая", "Первая", "Вторая"]);
    expect(result.duplicates).toBe(2);
    expect(result.errors).toHaveLength(1);
    expect(result.errors[0]).toContain("Строка 2");
    expect(splitEmailCell(" ; , \n")).toEqual([]);
    expect(splitEmailCell("a+b@example.com;name/department@example.com")).toEqual(["a+b@example.com", "name/department@example.com"]);
  });
  it("reads quoted multi-address CSV cells without shifting other columns", () => {
    const rows = parseCsv('Email,Компания\r\n"a@example.com,b@example.com;\nc@example.com",Тест');
    const result = prepareContacts(rows.slice(1), guessMapping(rows[0]), "база.csv", 2);
    expect(result.contacts).toHaveLength(3);
    expect(result.contacts.every(c => c.company === "Тест")).toBe(true);
  });
  it("enforces the contact limit after expansion without silently truncating", () => {
    const emails = Array.from({ length: MAX_IMPORT_CONTACTS }, (_, i) => `c${i}@example.com`);
    expect(prepareContacts([[emails.join(";")]], ["email"], "", 2).contacts).toHaveLength(70000);
    expect(() => prepareContacts([[`${emails.join(";")};extra@example.com`]], ["email"], "", 2)).toThrow("70000");
  });
  it("splits 70000 contacts into bounded batches without losing order or data", () => {
    const { contacts } = prepareContacts(Array.from({ length: 70000 }, (_, i) => [`c${i}@example.com`]), ["email"], "", 2);
    const batches = contactImportBatches(contacts);
    expect(batches).toHaveLength(140);
    expect(batches.every(batch => batch.count === 500 && new TextEncoder().encode(batch.body).length <= IMPORT_BATCH_BYTES)).toBe(true);
    expect(batches.flatMap(batch => JSON.parse(batch.body).contacts)).toEqual(contacts);
  });
  it("bounds UTF-8 request bytes including custom fields and rejects an oversized contact upfront", () => {
    const { contacts } = prepareContacts([["a@example.com;b@example.com;c@example.com", "Я".repeat(150000)]], ["email", "custom:notes"], "", 2);
    const batches = contactImportBatches(contacts);
    expect(batches).toHaveLength(3);
    expect(batches.every(batch => new TextEncoder().encode(batch.body).length <= IMPORT_BATCH_BYTES)).toBe(true);
    expect(() => contactImportBatches([...contacts, { ...contacts[0], custom_fields: { notes: "Я".repeat(IMPORT_BATCH_BYTES) } }])).toThrow("импорт не начат");
    expect(contactImportBatches([])).toEqual([]);
  });
  it("rejects invalid individual addresses but preserves Unicode domains", () => {
    const result = prepareContacts([["a..b@example.com;.name@example.com;a@-example.com;info@пример.рф"]], ["email"], "", 2);
    expect(result.contacts.map(c => c.email)).toEqual(["info@пример.рф"]);
    expect(result.errors).toHaveLength(1);
  });
  it("reads Excel CSV with BOM, sep, quotes, semicolon and multiline cells", () => {
    const rows = parseCsv('\uFEFFsep=;\r\nEmail;Ф.И.О.;Компания\r\na@example.com;Иванов Иван;"ООО ""Тест"";\nМосква"\r\n');
    expect(rows[1]).toEqual(["a@example.com", "Иванов Иван", 'ООО "Тест";\nМосква']);
    expect(guessMapping(rows[0])).toEqual(["email", "full_name", "company"]);
  });
  it("retains custom values and names; skips invalid rows and case-insensitive duplicates", () => {
    const parsed = prepareContacts([
      [" A@example.com ", "Иван", "Иванов", "Москва", "001234"],
      ["a@example.com", "Дубль", "", "", ""], ["broken", "", "", "", ""], ["", "", "", "", ""],
    ], ["email", "first_name", "last_name", "custom:city", "custom:inn"], "база.csv", 3);
    expect(parsed.contacts[0]).toMatchObject({ email: "a@example.com", first_name: "Иван", last_name: "Иванов", full_name: "Иванов Иван", custom_fields: { city: "Москва", inn: "001234" } });
    expect(parsed.duplicates).toBe(1); expect(parsed.errors).toHaveLength(1); expect(parsed.errors[0]).toContain("Строка 5");
  });
  it("requires email and unique mappings and prevents custom-field collisions", () => {
    expect(() => prepareContacts([], ["company"], "", 2)).toThrow("email");
    expect(() => prepareContacts([], ["email", "email"], "", 2)).toThrow("нескольким");
    expect(() => prepareContacts([], ["email", "custom:email"], "", 2)).toThrow("встроенной");
    expect(() => prepareContacts([], ["email", "custom:город"], "", 2)).toThrow("латинские");
  });
  it("reports oversized fields before sending a batch", () => {
    const result = prepareContacts([["a@example.com", "x".repeat(260)]], ["email", "company"], "", 2);
    expect(result.contacts).toHaveLength(0); expect(result.errors[0]).toContain("255");
  });
  it("rejects malformed CSV and accepts comma and tab delimiters", () => {
    expect(() => parseCsv('email,name\na@example.com,"unclosed')).toThrow("Ошибка CSV");
    expect(parseCsv("email\tname\na@example.com\tИван")[1]).toEqual(["a@example.com", "Иван"]);
    expect(parseCsv("email,name\na@example.com,Иван")[1]).toEqual(["a@example.com", "Иван"]);
  });
});
describe("CTA and personalization", () => {
  it.each(["javascript:alert(1)", "data:text/html,x", "//example.com", "ftp://example.com", "https://user:password@example.com", "bad"])("rejects unsafe address %s", value => expect(safeCtaUrl(value)).toBeNull());
  it("uses visible label with a valid destination", () => expect(safeCtaUrl(" https://example.com/meeting?a=1&b=2 ")).toBe("https://example.com/meeting?a=1&b=2"));
  it("does not allow custom values to override built-in recipient data", () => {
    const contact = { email: "a@example.com", first_name: "Иван", custom_fields: { city: "Москва", email: "other@example.com", product_name: "bad" } } as unknown as Contact;
    expect(contactVariables(contact, "Сайт")).toMatchObject({ city: "Москва", email: "a@example.com", first_name: "Иван", product_name: "Сайт" });
  });
});
