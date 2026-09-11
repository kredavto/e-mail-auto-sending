import { expect, test } from "@playwright/test";

test("workspace typography is readable without changing email typography", async ({ page }, info) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.route("https://fonts.googleapis.com/**", route => route.abort());
  await page.route("https://fonts.gstatic.com/**", route => route.abort());
  await page.addInitScript(() => {
    localStorage.setItem("access_token", "test-token");
    localStorage.setItem("workspace_id", "test-workspace");
  });
 await page.route("**/api/v1/**", route => {
      if (new URL(route.request().url()).pathname.endsWith("/contacts/lists")) return route.fulfill({ json: route.request().method() === "POST" ? { id: "test-list", name: route.request().postDataJSON().name } : [{ id: "test-list", name: "Тестовая база" }] });
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/workspaces")) return route.fulfill({ json: [{ id: "test-workspace", name: "Тест" }] });
    if (path.endsWith("/contacts")) return route.fulfill({ json: { items: [], total: 0 } });
    if (path.endsWith("/templates") || path.endsWith("/campaigns")) return route.fulfill({ json: [] });
    throw new Error(`Unexpected request: ${path}`);
  });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  await page.getByRole("link", { name: "Перейти в студию", exact: true }).click();
  await expect(page.locator(".studio-content .field").first()).toHaveCSS("font-size", "15px");
  const hint = page.locator(".studio-content .hint").filter({ visible: true }).first();
  await expect(hint).toHaveCSS("font-size", "15px");
  await expect(hint).toHaveCSS("color", "rgb(86, 97, 112)");
  await expect(page.getByRole("button", { name: "Общее", exact: true })).toHaveCSS("font-size", "15px");
  await expect(page.getByText("Контроль качества", { exact: true })).toHaveCSS("font-size", "14px");
  // Both small and large authored fonts, including the small unsubscribe link, stay intact.
  await page.getByRole("button", { name: "Белый на синем", exact: true }).click();
  for (const size of ["14", "20"]) {
    await page.getByRole("combobox", { name: "Размер текста", exact: true }).selectOption(size);
    await expect(page.locator(".tiptap")).toHaveCSS("font-size", `${size}px`);
    await expect(page.locator(".email-canvas")).toHaveCSS("color", "rgb(255, 255, 255)");
    await expect(page.locator(".email-canvas a")).toHaveCSS("font-size", "12px");
  }
  await page.locator(".studio-content").screenshot({ path: info.outputPath("workspace-typography.png") });
  await page.getByRole("button", { name: "Контакты и импорт", exact: true }).click();
  await expect(page.locator(".data-table th").first()).toHaveCSS("font-size", "14px");
  await expect(page.locator(".data-table th").first()).toHaveCSS("color", "rgb(70, 82, 100)");
  for (const width of [1440, 1024, 768, 390, 320]) {
    await page.setViewportSize({ width, height: 850 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  }
  await page.getByRole("button", { name: /^Редактор письма/ }).click();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  expect(errors).toEqual([]);
});
