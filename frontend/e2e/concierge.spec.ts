import { expect, test } from "@playwright/test";

test("onboarding greets once, navigates, carries conversation and clears on logout", async ({ page }) => {
  let calls = 0;
  let lastPrompt = "";
  await page.addInitScript(() => {
    localStorage.setItem("access_token", "test");
    localStorage.setItem("workspace_id", "space");
  });
  await page.route("**/api/v1/**", route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/workspaces")) return route.fulfill({ json: [{ id: "space", name: "Компания" }] });
    if (path.endsWith("/assistant/context")) return route.fulfill({ json: { ai_configured: true, delivery_mode: "smtp", counts: { contacts: 0, templates: 0, campaigns: 0 } } });
    if (path.endsWith("/assistant/runs") && route.request().method() === "POST") {
      calls++;
      const body = route.request().postDataJSON();
      expect(body.mode).toBe("advice"); expect(body.prompt.length).toBeLessThanOrEqual(6000);
      expect(route.request().headers()["x-workspace-id"]).toBe("space");
      lastPrompt = body.prompt;
      return route.fulfill({ json: { id: "run", status: "completed", result: { message: "Какую услугу вы предлагаете?", next_steps: ["Откройте редактор письма."] } } });
    }
    if (path.endsWith("/auth/logout")) return route.fulfill({ status: 204 });
    if (path.endsWith("/contacts")) return route.fulfill({ json: { items: [], total: 0 } });
    return route.fulfill({ json: [] });
  });
  await page.goto("/");
  const dialog = page.getByRole("dialog", { name: "Ваш ИИ-помощник" });
  await expect(dialog).toBeVisible({ timeout: 8000 });
  await expect(dialog).toContainText("У вас уже есть база CSV или Excel?");
  expect(calls).toBe(0);
  await dialog.getByRole("button", { name: "Следующий шаг: Контакты и импорт" }).click();
  await expect(dialog).not.toBeVisible();
  await expect(page.getByRole("button", { name: "Контакты и импорт", exact: true })).toHaveAttribute("aria-current", "page");
  await page.getByRole("button", { name: "✧ ИИ-помощник", exact: true }).click();
  await expect(dialog).toContainText("сопоставьте столбцы");
  await dialog.getByLabel("Сообщение помощнику").fill("Я предлагаю CRM для автосалонов");
  await dialog.getByRole("button", { name: "Отправить", exact: true }).click();
  await expect(dialog).toContainText("Какую услугу вы предлагаете?");
  await dialog.getByLabel("Сообщение помощнику").fill("Нужна встреча с директором");
  await dialog.getByRole("button", { name: "Отправить", exact: true }).click();
  await expect.poll(() => calls).toBe(2);
  expect(lastPrompt).toContain("CRM для автосалонов");
  expect(lastPrompt).toContain("Какую услугу вы предлагаете?");
  const box = await dialog.boundingBox();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(page.viewportSize()!.width);
  await dialog.getByRole("button", { name: "Свернуть помощника" }).click();
  await page.reload();
  await expect(page.getByRole("button", { name: "✧ ИИ-помощник", exact: true })).toBeVisible();
  await page.waitForTimeout(2800);
  await expect(dialog).not.toBeVisible();
  await page.getByRole("button", { name: "Выйти", exact: true }).click();
  await expect(page.getByRole("button", { name: "✧ ИИ-помощник", exact: true })).not.toBeVisible();
});

test("guests get no popup or assistant API requests", async ({ page }) => {
  let requests = 0;
  await page.route("**/api/v1/assistant/**", route => { requests++; return route.fulfill({ json: {} }); });
  await page.goto("/");
  await page.waitForTimeout(2800);
  await expect(page.getByRole("dialog", { name: "Ваш ИИ-помощник" })).not.toBeVisible();
  expect(requests).toBe(0);
});

test("without AI configuration the guide still offers navigation", async ({ page }) => {
  let posts = 0;
  await page.addInitScript(() => { localStorage.setItem("access_token", "test"); localStorage.setItem("workspace_id", "space"); });
  await page.route("**/api/v1/**", route => {
    const path = new URL(route.request().url()).pathname;
    if (route.request().method() === "POST") posts++;
    if (path.endsWith("/contacts")) return route.fulfill({ json: { items: [], total: 0 } });
    if (path.endsWith("/workspaces")) return route.fulfill({ json: [{ id: "space", name: "Компания" }] });
    if (path.endsWith("/assistant/context")) return route.fulfill({ json: { ai_configured: false, counts: { contacts: 5, templates: 1, campaigns: 0 } } });
    return route.fulfill({ json: [] });
  });
  await page.goto("/");
  const dialog = page.getByRole("dialog", { name: "Ваш ИИ-помощник" });
  await expect(dialog).toBeVisible({ timeout: 8000 });
  await expect(dialog).toContainText("База и шаблоны уже есть");
  await dialog.getByLabel("Сообщение помощнику").fill("Помоги подготовить рассылку");
  await dialog.getByRole("button", { name: "Отправить", exact: true }).click();
  await expect(dialog).toContainText("Свободный диалог с ИИ пока недоступен");
  expect(posts).toBe(0);
});
