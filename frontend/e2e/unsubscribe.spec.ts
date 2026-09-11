import { expect, test } from "@playwright/test";

test("automatic small unsubscribe footer remains visible for both letter types", async ({ page }) => {
  await page.route("https://fonts.googleapis.com/**", route => route.abort());
  await page.route("https://fonts.gstatic.com/**", route => route.abort());
  await page.context().route("**/api/v1/unsubscribe/preview", route => route.fulfill({ contentType: "text/plain; charset=utf-8", body: "Это предпросмотр. Сейчас никто не отписан от рассылки." }));
  await page.goto("/", { waitUntil: "domcontentloaded" });
  const footer = page.getByRole("link", { name: "Отписаться от рассылки", exact: true });
  await expect(footer).toHaveCount(1);
  await expect(footer).toHaveCSS("font-size", "12px");
  await expect(footer).toHaveAttribute("href", "/api/v1/unsubscribe/preview");
  await page.getByRole("button", { name: "Общее", exact: true }).click();
  await expect(footer).toHaveCount(1);
  await page.locator(".tiptap").fill("Новое предложение");
  await expect(footer).toBeVisible();
  const popupPromise = page.waitForEvent("popup");
  await footer.click();
  const popup = await popupPromise;
  await expect(popup.getByText("Сейчас никто не отписан", { exact: false })).toBeVisible();
  await popup.close();
  await expect(page.getByRole("button", { name: "Общее", exact: true })).toHaveAttribute("aria-pressed", "true");
});
