import { expect, test } from "@playwright/test";
import type { Contact, MailTemplate } from "../src/lib/mailing";

test.beforeEach(async ({ page }) => {
  await page.route("https://fonts.googleapis.com/**", route => route.abort());
  await page.route("https://fonts.gstatic.com/**", route => route.abort());
});

test("CSV → server import → stage template → personalized HTML and clickable CTA", async ({ page }) => {
  let contacts: Contact[] = [];
  let templates: MailTemplate[] = [];
  let savedPayload: Record<string, unknown> | null = null;
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.route("**/api/v1/**", async route => {
    const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
    const method = route.request().method();
    const payload = method === "POST" || method === "PATCH" ? route.request().postDataJSON() : null;
    const reply = (data: unknown, status = 200) => route.fulfill({ status, json: data });
    if (path === "/auth/login") return reply({ access_token: "test-token", refresh_token: "test-refresh", mfa_required: false });
    if (path === "/workspaces") return reply([{ id: "test-workspace", name: "Тестовая компания" }]);
    if (path === "/contacts/bulk") {
      expect(payload.contacts).toHaveLength(1);
      expect(payload.contacts[0]).toMatchObject({ email: "ivan@example.com", full_name: "Иванов Иван Иванович", custom_fields: { city: "Москва" } });
      contacts = payload.contacts.map((item: Contact, index: number) => ({ ...item, id: String(index), first_name: "Иван", status: "new" }));
      return reply({ created: 1, skipped: 0, errors: [] });
    }
    if (path === "/contacts") return reply({ items: contacts, total: contacts.length, page: 1, page_size: 25 });
    if (path === "/templates" && method === "GET") return reply(templates);
    if (path === "/templates" && method === "POST") {
      savedPayload = payload;
      templates = [{ ...payload, id: "template-1", version: 1, variables: ["first_name", "company", "city"] }];
      return reply(templates[0], 201);
    }
    if (path === "/templates/template-1" && method === "PATCH") {
      templates = [{ ...templates[0], ...payload, version: templates[0].version + 1 }];
      return reply(templates[0]);
    }
    if (path === "/editor/compile") return reply({ html: "<p>{{first_name}}</p>", text: "{{first_name}}", variables: ["first_name", "city"], quality_score: 85, warnings: [] });
    if (path === "/quality/check") return reply({ score: 85, issues: [], warnings: [], suggestions: [], words_count: 55 });
    if (path === "/editor/preview") {
      expect(payload.variables).toMatchObject({ first_name: "Иван", city: "Москва", company: "Тест" });
      const cta = payload.editor_state.content.find((node: { type: string }) => node.type === "ctaButton");
      expect(cta.attrs).toEqual({ label: "Обсудить проект", url: "https://example.com/meeting" });
      return reply({ html: `<p>Здравствуйте, Иван! Москва</p><a href="${cta.attrs.url}" target="_blank" rel="noopener noreferrer">${cta.attrs.label}</a>` });
    }
    return reply({ error: { message: `Unexpected ${method} ${path}` } }, 500);
  });
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.getByLabel("Email", { exact: true }).fill("tester@example.com");
  await page.getByLabel("Пароль", { exact: true }).fill("Test-password1");
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await page.getByRole("combobox", { name: "Рабочее пространство", exact: true }).selectOption("test-workspace");
  await page.getByRole("button", { name: "Контакты и импорт", exact: true }).click();
  await page.getByLabel("Файл контактов").setInputFiles({ name: "contacts.csv", mimeType: "text/csv", buffer: Buffer.from('\uFEFFEmail;Ф.И.О.;Компания;Город\r\nivan@example.com;Иванов Иван Иванович;Тест;Москва\r\nIVAN@example.com;Дубль;Тест;Москва\r\nbad;Ошибка;Тест;Москва', "utf8") });
  await page.getByLabel("Поле колонки 4").selectOption("custom");
  await page.getByLabel("Имя переменной", { exact: true }).fill("city");
  await expect(page.getByText("Дубли в файле: 1", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "Импортировать 1 контактов" }).click();
  await expect(page.getByText("Создано: 1.", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "Подставить в письмо" }).click();
  await page.getByLabel("Название шаблона").fill("Первое письмо директору");
  await page.getByLabel("Стадия применения").selectOption("reminder");
  await page.getByRole("button", { name: "+ CTA", exact: true }).click();
  await page.getByLabel("Текст кнопки", { exact: true }).fill("Обсудить проект");
  await page.getByLabel("Адрес ссылки", { exact: true }).fill("https://example.com/meeting");
  await page.getByRole("button", { name: "Вставить / обновить CTA" }).click();
  await expect(page.locator(".tiptap a[data-cta]")).toHaveAttribute("href", "https://example.com/meeting");
  await expect(page.locator(".tiptap a[data-cta]")).toHaveText("Обсудить проект");
  await page.getByRole("button", { name: "Проверить письмо", exact: true }).click();
  const preview = page.frameLocator('iframe[title="HTML-предпросмотр письма"]');
  await expect(preview.getByText("Здравствуйте, Иван! Москва")).toBeVisible();
  await expect(preview.getByRole("link", { name: "Обсудить проект" })).toHaveAttribute("href", "https://example.com/meeting");
  await page.context().route("https://example.com/meeting", route => route.fulfill({ body: "CTA destination" }));
  const popupPromise = page.waitForEvent("popup");
  await preview.getByRole("link", { name: "Обсудить проект" }).click();
  const popup = await popupPromise;
  await expect(popup).toHaveURL("https://example.com/meeting"); await popup.close();
  await page.getByRole("button", { name: "Сохранить шаблон", exact: true }).click();
  await expect(page.getByText("Шаблон сохранён на сервере", { exact: false })).toBeVisible();
  expect(savedPayload).toMatchObject({ category: "reminder", name: "Первое письмо директору" });
  await page.getByRole("button", { name: "Шаблоны писем", exact: true }).click();
  await page.getByRole("combobox", { name: "Стадия рассылки", exact: true }).selectOption("reminder");
  await expect(page.getByRole("heading", { name: "Первое письмо директору" })).toBeVisible();
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: "Шаблоны писем", exact: true }).click();
  await page.getByRole("button", { name: "Открыть в редакторе" }).click();
  await expect(page.getByLabel("Название шаблона")).toHaveValue("Первое письмо директору");
  await expect(page.getByLabel("Стадия применения")).toHaveValue("reminder");
  await expect(page.locator(".tiptap a[data-cta]")).toHaveText("Обсудить проект");
  await page.getByLabel("Стадия применения").selectOption("second");
  await page.getByRole("button", { name: "Сохранить шаблон", exact: true }).click();
  await expect(page.getByText("Шаблон сохранён на сервере · версия 2")).toBeVisible();
  expect(templates[0].category).toBe("second");
  expect(errors).toEqual([]);
  await page.screenshot({ path: test.info().outputPath("studio.png"), fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
});

test("XLSX can select a sheet and preserve custom values", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: "Контакты и импорт", exact: true }).click();
  await page.getByLabel("Файл контактов").setInputFiles("e2e/fixtures/contacts.xlsx");
  await page.getByLabel("Лист Excel").selectOption("Контакты");
  await expect(page.getByText("Иванов Иван", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Импортировать 1 контактов" })).toBeDisabled();
  await expect(page.getByText("001234", { exact: true })).toBeVisible();
});
