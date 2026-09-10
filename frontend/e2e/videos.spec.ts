import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import type { MailTemplate } from "../src/lib/mailing";

let mediaServer: Server;
const video = readFileSync("e2e/fixtures/short-video.mp4");
const poster = readFileSync("e2e/fixtures/video-poster.png");
test.beforeEach(async () => {
  mediaServer = createServer((req, res) => {
    const data = req.url?.endsWith(".mp4") ? video : poster;
    const mime = req.url?.endsWith(".mp4") ? "video/mp4" : "image/png";
    const match = req.headers.range?.match(/bytes=(\d+)-(\d*)/);
    if (match) {
      const start = Number(match[1]), end = match[2] ? Math.min(Number(match[2]), data.length - 1) : data.length - 1;
      res.writeHead(206, { "Content-Type": mime, "Content-Range": `bytes ${start}-${end}/${data.length}`, "Accept-Ranges": "bytes" });
      res.end(data.subarray(start, end + 1));
    } else { res.writeHead(200, { "Content-Type": mime }); res.end(data); }
  });
  await new Promise<void>(resolve => mediaServer.listen(0, "127.0.0.1", resolve));
});
test.afterEach(async () => { mediaServer.closeAllConnections(); await new Promise<void>(resolve => mediaServer.close(() => resolve())); });

test("MP4 upload, player, linked poster, persistence and removal", async ({ page }) => {
  const base = `http://127.0.0.1:${(mediaServer.address() as AddressInfo).port}`;
  let templates: MailTemplate[] = [];
  let reject = true;
  await page.route("https://fonts.googleapis.com/**", route => route.abort());
  await page.route("https://fonts.gstatic.com/**", route => route.abort());
  await page.addInitScript(() => { localStorage.setItem("access_token", "test-token"); localStorage.setItem("workspace_id", "test-workspace"); });
  await page.route("**/api/v1/**", async route => {
    const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
    const method = route.request().method();
    const reply = (data: unknown, status = 200) => route.fulfill({ status, json: data });
    if (path === "/files/videos") {
      expect(route.request().headers()["content-type"]).toContain("multipart/form-data");
      if (reject) return reply({ error: { message: "Видео должно быть не длиннее 60 секунд." } }, 400);
      return reply({ url: base + "/video.mp4", poster_url: base + "/poster.png", duration: 2 }, 201);
    }
    const payload = ["POST", "PATCH"].includes(method) ? route.request().postDataJSON() : null;
    if (path === "/workspaces") return reply([{ id: "test-workspace", name: "Видео-тест" }]);
    if (path === "/contacts") return reply({ items: [], total: 0 });
    if (path === "/templates" && method === "GET") return reply(templates);
    if (path === "/templates" && method === "POST") {
      templates = [{ ...payload, id: "video-template", version: 1, variables: [] }];
      expect(payload.editor_state.content.some((n: { type: string }) => n.type === "emailVideo")).toBeTruthy();
      return reply(templates[0], 201);
    }
    if (path === "/editor/compile") return reply({ html: "", text: "Видео", variables: [], quality_score: 85, warnings: [] });
    if (path === "/quality/check") return reply({ score: 85, issues: [], warnings: [], suggestions: [], words_count: 50 });
    if (path === "/editor/preview") return reply({ html: `<a href="${base}/video.mp4" target="_blank" style="display:block;width:25%"><img src="${base}/poster.png" alt="Обзор продукта" style="width:100%">▶ Обзор продукта</a>` });
    return reply({ error: { message: `Unexpected ${path}` } }, 500);
  });
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.getByLabel("Название шаблона").fill("Видеообзор");
  await page.getByLabel("Тема письма").fill("Наш продукт");
  await page.getByRole("button", { name: "+ Фото / видео", exact: true }).click();
  await page.getByLabel("Файл изображения или видео").evaluate((input: HTMLInputElement) => {
    const file = new File(["x"], "too-large.mp4", { type: "video/mp4" });
    Object.defineProperty(file, "size", { value: 20 * 1024 * 1024 + 1 });
    const transfer = new DataTransfer(); transfer.items.add(file); input.files = transfer.files;
    input.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await expect(page.getByRole("alert")).toContainText("20 МБ");
  await page.getByLabel("Файл изображения или видео").setInputFiles("e2e/fixtures/short-video.mp4");
  await page.getByLabel("Описание изображения или видео").fill("Обзор продукта");
  await expect(page.getByLabel("Предпросмотр видео")).toHaveJSProperty("videoWidth", 320);
  await page.getByRole("button", { name: "Загрузить и вставить" }).click();
  await expect(page.getByRole("alert")).toContainText("60 секунд");
  reject = false;
  await page.getByRole("button", { name: "Загрузить и вставить" }).click();
  const block = page.locator(".tiptap [data-email-video]");
  await expect(block).toHaveCount(1);
  await expect(block.locator("img")).toHaveAttribute("src", base + "/poster.png");
  expect(await block.evaluate(el => el.getBoundingClientRect().width / el.parentElement!.getBoundingClientRect().width)).toBeCloseTo(.25, 2);
  await page.getByRole("button", { name: "Проверить письмо", exact: true }).click();
  const preview = page.frameLocator('iframe[title="HTML-предпросмотр письма"]');
  const popupEvent = page.waitForEvent("popup");
  await preview.getByRole("link").click();
  const popup = await popupEvent;
  await expect(popup).toHaveURL(base + "/video.mp4");
  await popup.close();
  await page.getByRole("button", { name: "Сохранить шаблон", exact: true }).click();
  await expect(page.getByText("Шаблон сохранён на сервере", { exact: false })).toBeVisible();
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: "Шаблоны писем", exact: true }).click();
  await page.getByRole("button", { name: "Открыть в редакторе" }).click();
  await expect(block).toHaveCount(1);
  await block.click();
  await page.getByRole("button", { name: "+ Фото / видео", exact: true }).click();
  const player = page.getByLabel("Предпросмотр видео");
  await expect(player).toHaveJSProperty("videoWidth", 320);
  await player.evaluate(async (el: HTMLVideoElement) => { el.muted = true; await el.play(); });
  await expect.poll(() => player.evaluate((el: HTMLVideoElement) => el.currentTime)).toBeGreaterThan(0);
  await page.screenshot({ path: test.info().outputPath("video-upload.png"), fullPage: true });
  await page.getByRole("button", { name: "Удалить файл", exact: true }).click();
  await expect(block).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
});
