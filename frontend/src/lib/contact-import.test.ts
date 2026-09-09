import { describe, expect, it } from "vitest";
import { guessMapping, parseCsv, prepareContacts } from "./contact-import";
import { contactVariables, safeCtaUrl, type Contact } from "./mailing";

describe("contact import", () => {
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
