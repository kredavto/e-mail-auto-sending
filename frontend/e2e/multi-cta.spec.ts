import { expect, test } from "@playwright/test";
import type { JSONContent } from "@tiptap/core";
import type { MailTemplate } from "../src/lib/mailing";

test("multiple CTA: independent links, edit, move, undo, drag, save and reopen", async ({ page }, info) => {
  let templates: MailTemplate[] = [];
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  const paragraph = (text: string): JSONContent => ({ type: "paragraph", content: [{ type: "text", text }] });
  const html = (state: JSONContent) => (state.content ?? []).map(node => node.type === "ctaButton" ? `<a href="${node.attrs?.url}" target="_blank">${node.attrs?.label}</a>` : `<p>${node.content?.map(child => child.text ?? "").join("") ?? ""}</p>`).join("");
  await page.route("https://fonts.googleapis.com/**", r => r.abort());
  await page.route("https://fonts.gstatic.com/**", r => r.abort());
  await page.route("**/api/v1/**", async route => {
    const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
    const method = route.request().method();
    const data = method === "POST" || method === "PATCH" ? route.request().postDataJSON() : null;
    const reply = (json: unknown) => route.fulfill({ json });
    if (path === "/auth/login") return reply({ access_token: "test", refresh_token: "refresh" });
    if (path === "/workspaces") return reply([{ id: "workspace", name: "Тест" }]);
    if (path === "/contacts") return reply({ items: [], total: 0 });
    if (path === "/templates" && method === "GET") return reply(templates);
    if (path === "/templates" && method === "POST") {
      templates = [{ ...data, id: "template", version: 1, variables: [] }];
      return reply(templates[0]);
    }
    if (path === "/editor/compile") return reply({ html: html(data.editor_state), text: "Текст", variables: [], quality_score: 100, warnings: [] });
    if (path === "/editor/preview") return reply({ html: html(data.editor_state) });
    if (path === "/quality/check") return reply({ score: 100, issues: [], warnings: [], suggestions: [], words_count: 30 });
    return route.fulfill({ status: 500, json: { error: { message: `Unexpected ${path}` } } });
  });
  // Open an existing-format template; no migration or new node attributes required.
  templates = [{ id: "initial", name: "Кнопки", subject_template: "Предложение", category: "first_contact", version: 1, variables: [], editor_state: { type: "doc", attrs: { letterType: "general" }, content: [paragraph("Первый абзац"), paragraph("Второй абзац"), paragraph("Третий абзац")] } }];
  await page.goto("/");
  await page.getByLabel("Email", { exact: true }).fill("test@example.com");
  await page.getByLabel("Пароль", { exact: true }).fill("Test-password1");
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await page.getByRole("combobox", { name: "Рабочее пространство", exact: true }).selectOption("workspace");
  await page.getByRole("button", { name: "Шаблоны писем", exact: true }).click();
  await page.getByRole("button", { name: "Открыть в редакторе" }).click();
  const editor = page.locator(".tiptap");
  const buttons = editor.locator("a[data-cta]");
  async function add(label: string, url: string) {
    await page.getByRole("button", { name: "+ CTA", exact: true }).click();
    await page.getByLabel("Текст кнопки", { exact: true }).fill(label);
    await page.getByLabel("Адрес ссылки", { exact: true }).fill(url);
    await page.getByRole("button", { name: "Вставить CTA", exact: true }).click();
  }
  await editor.locator("p").first().click();
  await page.keyboard.press("End");
  await add("Каталог", "https://example.com/catalog");
  await buttons.first().click();
  await add("Записаться", "https://example.com/meeting"); // Must add, not overwrite selected CTA.
  await expect(buttons).toHaveText(["Каталог", "Записаться"]);
  await buttons.first().click();
  await page.getByRole("button", { name: "Изменить кнопку", exact: true }).click();
  await page.getByLabel("Текст кнопки", { exact: true }).fill("Скачать каталог");
  await page.getByLabel("Адрес ссылки", { exact: true }).fill("https://example.com/catalog-new");
  await page.getByRole("button", { name: "Сохранить изменения кнопки", exact: true }).click();
  await expect(buttons.first()).toHaveAttribute("href", "https://example.com/catalog-new");
  await expect(buttons.nth(1)).toHaveAttribute("href", "https://example.com/meeting");
  await buttons.nth(1).click();
  await page.getByRole("button", { name: "↑ Выше", exact: true }).click();
  await expect(buttons).toHaveText(["Записаться", "Скачать каталог"]);
  await page.getByRole("button", { name: "Отменить действие", exact: true }).click();
  await expect(buttons).toHaveText(["Скачать каталог", "Записаться"]);
  await page.getByRole("button", { name: "Повторить действие", exact: true }).click();
  await expect(buttons).toHaveText(["Записаться", "Скачать каталог"]);
  await buttons.first().click();
  await page.getByRole("button", { name: "↑ Выше", exact: true }).click();
  await expect(page.getByRole("button", { name: "↑ Выше", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "↓ Ниже", exact: true }).click();
  await expect(editor.locator("p").first()).toHaveText("Первый абзац");
  if (info.project.name === "desktop") {
    const handle = editor.locator("[data-drag-handle]").nth(1);
    await handle.scrollIntoViewIfNeeded();
    const source = (await handle.boundingBox())!;
    const target = (await editor.locator("p").last().boundingBox())!;
    await page.mouse.move(source.x + source.width / 2, source.y + source.height / 2);
    await page.mouse.down();
    await page.mouse.move(source.x + 20, source.y + 10, { steps: 5 });
    await page.mouse.move(target.x + 10, target.y + target.height - 1, { steps: 15 });
    await page.mouse.up();
    await expect(buttons).toHaveCount(2); // Move, not copy.
    await expect(editor).toContainText("Третий абзац");
    expect(await editor.evaluate(el => el.innerText.indexOf("Скачать каталог") > el.innerText.indexOf("Второй абзац"))).toBeTruthy();
  }
  await page.getByRole("button", { name: "Проверить письмо", exact: true }).click();
  const preview = page.frameLocator('iframe[title="HTML-предпросмотр письма"]');
  for (const [label, url] of [["Скачать каталог", "https://example.com/catalog-new"], ["Записаться", "https://example.com/meeting"]]) {
    await expect(preview.getByRole("link", { name: label })).toHaveAttribute("href", url);
  }
  await page.getByRole("button", { name: "Сохранить копию", exact: true }).click();
  await expect(page.getByText("Шаблон сохранён на сервере", { exact: false })).toBeVisible();
  const stored = templates[0].editor_state as JSONContent;
  const storedButtons = stored.content?.filter(node => node.type === "ctaButton");
  expect(storedButtons).toHaveLength(2);
  expect(stored.content?.filter(node => node.type === "paragraph").map(node => node.content?.map(c => c.text ?? "").join(""))).toEqual(expect.arrayContaining(["Первый абзац", "Второй абзац", "Третий абзац"]));
  await page.reload();
  await page.getByRole("button", { name: "Шаблоны писем", exact: true }).click();
  await page.getByRole("button", { name: "Открыть в редакторе" }).click();
  await expect(buttons).toHaveText(storedButtons!.map(node => node.attrs!.label));
  await buttons.first().click();
  await page.getByRole("button", { name: "Удалить кнопку", exact: true }).click();
  await expect(buttons).toHaveCount(1);
  await page.getByRole("button", { name: "Отменить действие", exact: true }).click();
  await expect(buttons).toHaveCount(2);
  await editor.screenshot({ path: info.outputPath("multi-cta.png") });
  expect(errors).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
});
