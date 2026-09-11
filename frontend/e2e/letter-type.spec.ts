import { expect, test } from "@playwright/test";
import type { MailTemplate } from "../src/lib/mailing";

test("general letter: thematic heading, no name, save/reopen/copy, safe switching", async ({ page }) => {
  let templates: MailTemplate[] = [];
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.route("https://fonts.googleapis.com/**", route => route.abort());
  await page.route("https://fonts.gstatic.com/**", route => route.abort());
  await page.route("**/api/v1/**", async route => {
    const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
    const method = route.request().method();
    const payload = ["POST", "PATCH"].includes(method) ? route.request().postDataJSON() : null;
    const reply = (data: unknown, status = 200) => route.fulfill({ status, json: data });
    if (path === "/auth/login") return reply({ access_token: "test-token", refresh_token: "test-refresh" });
    if (path === "/workspaces") return reply([{ id: "test-workspace", name: "Тест" }]);
    if (path === "/contacts") return reply({ items: [], total: 0, page: 1, page_size: 25 });
    if (path === "/templates" && method === "GET") return reply(templates);
    if (path === "/templates" && method === "POST") {
      expect(payload.editor_state.attrs.letterType).toBe("general");
      templates.push({ ...payload, id: `template-${templates.length + 1}`, version: 1, variables: [] });
      return reply(templates.at(-1), 201);
    }
    if (path.startsWith("/templates/") && method === "PATCH") {
      const index = templates.findIndex(t => path.endsWith(t.id));
      templates[index] = { ...templates[index], ...payload, version: templates[index].version + 1 };
      return reply(templates[index]);
    }
    if (path === "/editor/compile") {
      expect(payload.editor_state.attrs.letterType).toBe("general");
      expect(JSON.stringify(payload)).not.toContain("Здравствуйте");
      return reply({ html: "<p>Автоматизация учёта</p>", text: "Автоматизация учёта", variables: [], quality_score: 85, warnings: [] });
    }
    if (path === "/editor/preview") {
      expect(payload.variables).toEqual({ product_name: "" });
      expect(payload.editor_state.attrs.letterType).toBe("general");
      return reply({ html: '<p>Автоматизация учёта</p><a href="https://example.com/demo">Подробнее</a>' });
    }
    if (path === "/quality/check") return reply({ score: 85, issues: [], warnings: [], suggestions: [], words_count: 5 });
    return reply({ error: { message: `Unexpected ${method} ${path}` } }, 500);
  });
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.getByLabel("Email", { exact: true }).fill("tester@example.com");
  await page.getByLabel("Пароль", { exact: true }).fill("Test-password1");
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await page.getByRole("combobox", { name: "Рабочее пространство", exact: true }).selectOption("test-workspace");
  await expect(page.getByRole("button", { name: "Персонализированное", exact: true })).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "Общее", exact: true }).click();
  await expect(page.getByRole("button", { name: "Общее", exact: true })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByLabel("Тема письма", { exact: true })).toHaveValue("");
  await expect(page.locator(".tiptap")).not.toContainText("Здравствуйте");
  await expect(page.locator(".tiptap h2")).toHaveAttribute("data-placeholder", "Заголовок по тематике письма");
  await expect(page.getByRole("button", { name: "Выбрать контакт из базы" })).not.toBeVisible();
  await page.getByLabel("Название шаблона").fill("Предложение на корпоративную почту");
  await page.getByLabel("Тема письма", { exact: true }).fill("Автоматизация учёта");
  await page.locator(".tiptap h2").click();
  await page.keyboard.type("Автоматизация учёта");
  await page.keyboard.press("End");
  await page.keyboard.press("ArrowDown");
  await page.getByRole("button", { name: "+ CTA", exact: true }).click();
  await page.getByLabel("Текст кнопки", { exact: true }).fill("Подробнее");
  await page.getByLabel("Адрес ссылки", { exact: true }).fill("https://example.com/demo");
  await page.getByRole("button", { name: "Вставить CTA" }).click();
  await page.getByRole("button", { name: "Проверить письмо", exact: true }).click();
  await expect(page.frameLocator("iframe").getByText("Автоматизация учёта")).toBeVisible();
  await page.getByRole("button", { name: "Сохранить шаблон", exact: true }).click();
  await expect(page.getByText("Шаблон сохранён на сервере · версия 1")).toBeVisible();
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: "Шаблоны писем", exact: true }).click();
  await expect(page.locator("article").getByText("Общее", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Открыть в редакторе" }).click();
  await expect(page.getByRole("button", { name: "Общее", exact: true })).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator(".tiptap h2")).toContainText("Автоматизация учёта");
  await expect(page.locator(".tiptap a[data-cta]")).toHaveAttribute("href", "https://example.com/demo");
  await page.getByRole("button", { name: "Персонализированное", exact: true }).click();
  await page.getByLabel("Тема письма", { exact: true }).fill("{{first_name}}, предложение");
  const before = await page.locator(".tiptap").innerHTML();
  await page.getByRole("button", { name: "Общее", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("{{first_name}}");
  await expect(page.getByRole("button", { name: "Сохранить шаблон", exact: true })).toBeDisabled();
  expect(await page.locator(".tiptap").innerHTML()).toBe(before);
  await page.getByLabel("Тема письма", { exact: true }).fill("Автоматизация учёта");
  await page.getByRole("button", { name: "Сохранить копию", exact: true }).click();
  await expect(page.getByText("Шаблон сохранён на сервере · версия 1")).toBeVisible();
  expect(templates).toHaveLength(2);
  expect(templates.every(t => t.editor_state.attrs?.letterType === "general")).toBeTruthy();
  expect(errors).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.screenshot({ path: test.info().outputPath("general-letter.png"), fullPage: true });
});
