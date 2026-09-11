import { expect, test } from "@playwright/test";
import type { MailTemplate } from "../src/lib/mailing";
import { getEmailStyle, readableText } from "../src/lib/email-style";

test("themes and local reference → preview → saved style → reopen, reset without losing text", async ({ page }, info) => {
  let templates: MailTemplate[] = [];
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.route("https://fonts.googleapis.com/**", r => r.abort());
  await page.route("https://fonts.gstatic.com/**", r => r.abort());
  await page.route("**/api/v1/**", async route => {
    const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
    const method = route.request().method();
    const data = method === "POST" ? route.request().postDataJSON() : null;
    const reply = (json: unknown) => route.fulfill({ json });
    if (path === "/auth/login") return reply({ access_token: "test", refresh_token: "refresh" });
    if (path === "/workspaces") return reply([{ id: "workspace", name: "Тест" }]);
    if (path === "/contacts") return reply({ items: [], total: 0 });
    if (path === "/templates" && method === "GET") return reply(templates);
    if (path === "/templates" && method === "POST") { templates = [{ ...data, id: "template", version: 1, variables: [] }]; return reply(templates[0]); }
    if (path === "/editor/compile") return reply({ html: "Письмо", text: "Письмо", variables: [], quality_score: 100, warnings: [] });
    if (path === "/editor/preview") { const style = getEmailStyle(data.editor_state); return reply({ html: `<div style="background:${style.background};color:${readableText(style.background)}">Письмо в выбранном стиле</div>` }); }
    if (path === "/quality/check") return reply({ score: 100, issues: [], warnings: [], suggestions: [], words_count: 30 });
    throw new Error(`Unexpected request (reference must stay local): ${path}`);
  });
  await page.goto("/");
  await page.getByLabel("Email", { exact: true }).fill("test@example.com");
  await page.getByLabel("Пароль", { exact: true }).fill("Test-password1");
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await page.getByRole("combobox", { name: "Рабочее пространство", exact: true }).selectOption("workspace");
  await page.getByRole("button", { name: "Общее", exact: true }).click();
  await page.getByLabel("Название шаблона", { exact: true }).fill("Стиль из референса");
  await page.getByLabel("Тема письма", { exact: true }).fill("Предложение");
  await page.locator(".tiptap").fill("Сохранить этот текст письма");
  for (const name of ["Белый на чёрном", "Белый на синем", "Белый на красном"]) {
    await page.getByRole("button", { name, exact: false }).click();
    await expect(page.locator(".email-canvas")).toHaveCSS("color", "rgb(255, 255, 255)");
  }
  await page.getByRole("button", { name: "Мятный", exact: false }).click();
  await expect(page.locator(".email-canvas")).toHaveCSS("background-color", "rgb(234, 247, 239)");
  const png = await page.evaluate(() => { const c = document.createElement("canvas"); c.width = 100; c.height = 100; const ctx = c.getContext("2d")!; ctx.fillStyle = "#1746a2"; ctx.fillRect(0, 0, 100, 100); ctx.fillStyle = "#ffffff"; ctx.fillRect(0, 80, 100, 20); return c.toDataURL("image/png").split(",")[1]; });
  await page.getByLabel("Загрузить референс", { exact: true }).setInputFiles({ name: "reference.png", mimeType: "image/png", buffer: Buffer.from(png, "base64") });
  await expect(page.getByAltText("Референс оформления письма")).toBeVisible();
  await page.getByRole("button", { name: "Применить палитру референса", exact: true }).click();
  await expect(page.locator(".email-canvas")).toHaveCSS("background-color", "rgb(23, 70, 162)");
  await page.getByRole("combobox", { name: "Шрифт письма", exact: true }).selectOption("serif");
  await page.getByRole("combobox", { name: "Размер текста", exact: true }).selectOption("18");
  await page.getByRole("combobox", { name: "Скругление кнопок", exact: true }).selectOption("12");
  await page.getByRole("button", { name: "Проверить письмо", exact: true }).click();
  await expect(page.frameLocator('iframe[title="HTML-предпросмотр письма"]').locator("div")).toHaveCSS("background-color", "rgb(23, 70, 162)");
  await page.getByRole("region", { name: "Оформление письма" }).screenshot({ path: info.outputPath("style-panel.png") });
  await page.getByRole("button", { name: "Сохранить шаблон", exact: true }).click();
  await expect(page.getByText("Шаблон сохранён на сервере", { exact: false })).toBeVisible();
  expect(templates[0].editor_state.attrs?.emailStyle).toMatchObject({ background: "#1746a2", buttonBackground: "#ffffff", font: "serif", fontSize: 18, radius: 12 });
  expect(JSON.stringify(templates[0])).not.toMatch(/blob:|data:image|reference.png/);
  await page.reload();
  await page.getByRole("button", { name: "Шаблоны писем", exact: true }).click();
  await page.getByRole("button", { name: "Открыть в редакторе" }).click();
  await expect(page.locator(".email-canvas")).toHaveCSS("background-color", "rgb(23, 70, 162)");
  await expect(page.locator(".tiptap")).toContainText("Сохранить этот текст письма");
  await expect(page.getByAltText("Референс оформления письма")).toHaveCount(0);
  await page.getByLabel("Загрузить референс", { exact: true }).setInputFiles({ name: "bad.svg", mimeType: "image/svg+xml", buffer: Buffer.from("<svg/>") });
  await expect(page.getByRole("alert")).toContainText("Выберите PNG");
  await page.getByRole("button", { name: "Сбросить оформление", exact: true }).click();
  await expect(page.locator(".email-canvas")).toHaveCSS("background-color", "rgb(255, 255, 255)");
  await expect(page.locator(".tiptap")).toContainText("Сохранить этот текст письма");
  expect(errors).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
});
