import { expect, test } from "@playwright/test";
import type { MailTemplate } from "../src/lib/mailing";
import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";

const png = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAADAAAAAgCAIAAADbtmxLAAAAUElEQVR4nM3OQQEAIBCAMKSLIcxg/z7+r4Aswda+hxKJkRiJkRiJkRiJkRiJkRiJkRiJkRiJkRiJkRiJkRiJkRiJkRiJkRiJkRiJkRh/B6YHTKwA6cDAHmkAAAAASUVORK5CYII=", "base64");
let imageServer: Server;
test.beforeEach(async () => {
  // A real HTTP fixture also exercises image loading in the sandboxed preview.
  imageServer = createServer((_req, res) => { res.writeHead(200, { "Content-Type": "image/png" }); res.end(png); });
  await new Promise<void>(resolve => imageServer.listen(0, "127.0.0.1", resolve));
});
test.afterEach(async () => { await new Promise<void>(resolve => imageServer.close(() => resolve())); });

test("upload → quarter-width image → preview → saved template → replace and remove", async ({ page }) => {
  const imageUrl = `http://127.0.0.1:${(imageServer.address() as AddressInfo).port}/${"a".repeat(32)}.png`;
  let templates: MailTemplate[] = [];
  let failUpload = true;
  let uploads = 0;
  await page.route("https://fonts.googleapis.com/**", route => route.abort());
  await page.route("https://fonts.gstatic.com/**", route => route.abort());
 await page.route("**/api/v1/**", async route => {
      if (new URL(route.request().url()).pathname.endsWith("/contacts/lists")) return route.fulfill({ json: route.request().method() === "POST" ? { id: "test-list", name: route.request().postDataJSON().name } : [{ id: "test-list", name: "Тестовая база" }] });
    const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
    const method = route.request().method();
    const reply = (data: unknown, status = 200) => route.fulfill({ status, json: data });
    if (path === "/files/images") {
      expect(route.request().headers()["content-type"]).toContain("multipart/form-data; boundary=");
      expect(route.request().headers()["x-workspace-id"]).toBe("test-workspace");
      if (failUpload) return reply({ error: { message: "Тестовая ошибка загрузки" } }, 400);
      uploads++;
      return reply({ url: imageUrl, width: 480, height: 320 }, 201);
    }
    const payload = ["POST", "PATCH"].includes(method) ? route.request().postDataJSON() : null;
    if (path === "/auth/login") return reply({ access_token: "test-token", refresh_token: "test-refresh", mfa_required: false });
    if (path === "/workspaces") return reply([{ id: "test-workspace", name: "Тестовая компания" }]);
    if (path === "/contacts") return reply({ items: [], total: 0 });
    if (path === "/templates" && method === "GET") return reply(templates);
    if (path === "/templates" && method === "POST") {
      templates = [{ ...payload, id: "image-template", version: 1, variables: [] }];
      return reply(templates[0], 201);
    }
    if (path === "/editor/compile") return reply({ html: "", text: "Фото", variables: [], quality_score: 85, warnings: [] });
    if (path === "/quality/check") return reply({ score: 85, issues: [], warnings: [], suggestions: [], words_count: 50 });
    if (path === "/editor/preview") {
      const image = payload.editor_state.content.find((node: { type: string }) => node.type === "emailImage");
      expect(image.attrs).toEqual({ src: imageUrl, alt: "Фотография продукта" });
      return reply({ html: `<div style="width:100%;max-width:576px"><p>Текст письма</p><img alt="Фотография продукта" src="${imageUrl}" width="144" style="width:25%;max-width:144px;height:auto"></div>` });
    }
    return reply({ error: { message: `Unexpected ${method} ${path}` } }, 500);
  });
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.getByLabel("Email", { exact: true }).fill("tester@example.com");
  await page.getByLabel("Пароль", { exact: true }).fill("Test-password1");
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await page.getByRole("combobox", { name: "Рабочее пространство", exact: true }).selectOption("test-workspace");
  await page.getByLabel("Название шаблона").fill("Шаблон с фотографией");
  await page.getByLabel("Тема письма").fill("Наш продукт");
  await page.getByRole("button", { name: "+ Фото / видео", exact: true }).click();
  await page.getByLabel("Файл изображения или видео").setInputFiles({ name: "huge.png", mimeType: "image/png", buffer: Buffer.alloc(5 * 1024 * 1024 + 1) });
  await expect(page.getByRole("alert")).toContainText("5 МБ");
  await page.getByLabel("Файл изображения или видео").setInputFiles({ name: "image.svg", mimeType: "image/svg+xml", buffer: Buffer.from("<svg></svg>") });
  await expect(page.getByRole("alert")).toContainText("JPEG, PNG или WebP");
  await page.getByLabel("Файл изображения или видео").setInputFiles({ name: "photo.png", mimeType: "image/png", buffer: png });
  await page.getByLabel("Описание изображения или видео").fill("Фотография продукта");
  await page.getByRole("button", { name: "Загрузить и вставить" }).click();
  await expect(page.getByRole("alert")).toContainText("Тестовая ошибка загрузки");
  expect(uploads).toBe(0);
  failUpload = false;
  await page.getByRole("button", { name: "Загрузить и вставить" }).click();
  const image = page.locator(".tiptap img[data-email-image]");
  await expect(image).toHaveAttribute("src", imageUrl);
  await expect(image).toHaveJSProperty("naturalWidth", 48);
  const ratio = await image.evaluate(element => element.getBoundingClientRect().width / element.parentElement!.getBoundingClientRect().width);
  expect(ratio).toBeCloseTo(0.25, 2);
  await page.getByRole("button", { name: "Проверить письмо", exact: true }).click();
  const preview = page.frameLocator('iframe[title="HTML-предпросмотр письма"]');
  await expect(preview.getByAltText("Фотография продукта")).toBeVisible();
  await expect(preview.getByAltText("Фотография продукта")).toHaveJSProperty("naturalWidth", 48);
  await page.screenshot({ path: test.info().outputPath("image-preview.png"), fullPage: true });
  await page.getByRole("button", { name: "Сохранить шаблон", exact: true }).click();
  await expect(page.getByText("Шаблон сохранён на сервере", { exact: false })).toBeVisible();
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: "Шаблоны писем", exact: true }).click();
  await page.getByRole("button", { name: "Открыть в редакторе" }).click();
  await expect(image).toHaveAttribute("src", imageUrl);
  await image.click();
  await page.getByRole("button", { name: "+ Фото / видео", exact: true }).click();
  await page.getByLabel("Описание изображения или видео").fill("Новое описание");
  await page.getByLabel("Файл изображения или видео").setInputFiles({ name: "replacement.png", mimeType: "image/png", buffer: png });
  await page.getByRole("button", { name: "Обновить файл" }).click();
  await expect(image).toHaveCount(1);
  await expect(image).toHaveAttribute("alt", "Новое описание");
  expect(uploads).toBe(2);
  await image.click();
  await page.getByRole("button", { name: "+ Фото / видео", exact: true }).click();
  await page.getByRole("button", { name: "Удалить файл", exact: true }).click();
  await expect(image).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
});
