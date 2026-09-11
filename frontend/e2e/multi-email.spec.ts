import { execFileSync } from "node:child_process";
import { expect, test } from "@playwright/test";
import type { Contact } from "../src/lib/mailing";

for (const extension of ["csv", "xlsx"]) {
  test(`${extension}: multi-email cell → separate contacts → reload → retry deduplicates`, async ({ page }) => {
    let contacts: Contact[] = [];
    const industry = "Производство и поставки оборудования; ".repeat(10).trim();
    const phone = "+7 900 123-45-67; ".repeat(10).trim();
    const errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.route("https://fonts.googleapis.com/**", route => route.abort());
    await page.route("https://fonts.gstatic.com/**", route => route.abort());
   await page.route("**/api/v1/**", async route => {
      if (new URL(route.request().url()).pathname.endsWith("/contacts/lists")) return route.fulfill({ json: route.request().method() === "POST" ? { id: "test-list", name: route.request().postDataJSON().name } : [{ id: "test-list", name: "Тестовая база" }] });
      const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
      const reply = (data: unknown) => route.fulfill({ json: data });
      if (path === "/auth/login") return reply({ access_token: "test-token", refresh_token: "test-refresh" });
      if (path === "/workspaces") return reply([{ id: "test-workspace", name: "Тест" }]);
      if (path === "/templates") return reply([]);
      if (path === "/contacts") return reply({ items: contacts, total: contacts.length, page: 1, page_size: 25 });
      if (path === "/contacts/bulk") {
        const items: Contact[] = route.request().postDataJSON().contacts;
        expect(items.map(c => c.email)).toEqual(["info@example.com", "sales@example.com", "office@example.com"]);
        expect(items.every(c => c.company === "Тест" && c.full_name === "Иванов Иван")).toBe(true);
        for (const item of items) expect(item).toMatchObject({ industry: industry.slice(0, 100), phone: phone.slice(0, 50), custom_fields: { import_original_industry: industry, import_original_phone: phone } });
        const created = contacts.length ? 0 : items.length;
        if (created) contacts = items.map((item, index) => ({ ...item, id: String(index), status: "new" }));
        return reply({ created, skipped: items.length - created, errors: [] });
      }
      return route.fulfill({ status: 500, json: { error: { message: `Unexpected ${path}` } } });
    });
    const cell = "INFO@example.com; sales@example.com,\noffice@example.com info@example.com";
    let buffer: Buffer;
    if (extension === "csv") buffer = Buffer.from(`Email,Компания,Ф.И.О.,Отрасль,Телефон\r\n"${cell}",Тест,Иванов Иван,${industry},${phone}\r\n,Без почты,,,`);
    else {
      const python = process.platform === "win32" ? "../.venv/Scripts/python.exe" : "../.venv/bin/python";
      buffer = execFileSync(python, ["-c", "import io,sys,json; from openpyxl import Workbook; b=Workbook(); b.active.append(['Email','Компания','Ф.И.О.','Отрасль','Телефон']); b.active.append(json.loads(sys.argv[1])); b.active.append(['','Без почты','','','']); s=io.BytesIO(); b.save(s); sys.stdout.buffer.write(s.getvalue())", JSON.stringify([cell, "Тест", "Иванов Иван", industry, phone])]);
    }
    const file = { name: `multi-email.${extension}`, mimeType: extension === "csv" ? "text/csv" : "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", buffer };
    await page.goto("/", { waitUntil: "domcontentloaded" });
    await page.getByLabel("Email", { exact: true }).fill("tester@example.com");
    await page.getByLabel("Пароль", { exact: true }).fill("Test-password1");
    await page.getByRole("button", { name: "Войти", exact: true }).click();
    await page.getByRole("combobox", { name: "Рабочее пространство", exact: true }).selectOption("test-workspace");
    await page.getByRole("button", { name: "Контакты и импорт", exact: true }).click();
    await page.getByLabel("Файл контактов").setInputFiles(file);
    await expect(page.getByText("Дубли в файле: 1", { exact: false })).toBeVisible();
    await expect(page.getByText("Строки с ошибками: 1", { exact: false })).toBeVisible();
    await expect(page.getByText("Предупреждения: 2 — не мешают импорту", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Импортировать 3 контактов" }).click();
    await expect(page.getByText("Создано: 3.", { exact: false })).toBeVisible();
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.getByRole("button", { name: "Контакты и импорт", exact: true }).click();
    for (const email of ["info@example.com", "sales@example.com", "office@example.com"]) await expect(page.getByRole("cell", { name: email, exact: true })).toBeVisible();
    await page.getByLabel("Файл контактов").setInputFiles(file);
    await page.getByRole("button", { name: "Импортировать 3 контактов" }).click();
    await expect(page.getByText("Создано: 0. Уже были в базе: 3.", { exact: false })).toBeVisible();
    expect(errors).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  });
}
