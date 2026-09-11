import { expect, test } from "@playwright/test";

test("sender selector: choose, type, save draft, reload and reuse new address", async ({ page }) => {
  const campaigns = [{ id: "old", name: "Прежняя", sender_email: "sales@example.com", status: "draft", schedule_start: "2028-01-01T10:00:00Z" }, { id: "duplicate", name: "Другая", sender_email: "SALES@example.com", status: "draft", schedule_start: "2028-01-01T10:00:00Z" }];
  let created = 0;
  await page.route("https://fonts.googleapis.com/**", r => r.abort());
  await page.route("https://fonts.gstatic.com/**", r => r.abort());
  await page.route("**/api/v1/**", async route => {
    const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
    const reply = (json: unknown) => route.fulfill({ json });
    if (path === "/auth/login") return reply({ access_token: "test", refresh_token: "refresh" });
    if (path === "/workspaces") return reply([{ id: "workspace", name: "Тест" }]);
    if (path === "/contacts") return reply({ items: [], total: 0 });
    if (path === "/campaigns") return reply(campaigns);
    if (path === "/templates") return reply([{ id: "template", name: "Предложение", subject_template: "Тема", category: "first_contact", editor_state: {}, version: 1, variables: [] }]);
    if (path === "/assistant/context") return reply({ ai_configured: false, can_manage: true, delivery_mode: "test", daily_limit: 30, counts: { contacts: 1, templates: 1, campaigns: campaigns.length } });
    if (path === "/assistant/runs") return reply([]);
    if (path === "/assistant/contacts") return reply({ items: [{ id: "contact", email: "lead@example.com", full_name: "", company: "Тест" }], total: 1 });
    if (path === "/assistant/campaigns") {
      const data = route.request().postDataJSON();
      expect(data.sender_email).toBe("new@example.com");
      expect(data.sender_name).toBe("Компания");
      created++;
      campaigns.push({ id: "new", name: data.name, sender_email: data.sender_email, schedule_start: data.schedule_start, status: "draft" });
      return reply({ id: "new" });
    }
    return route.fulfill({ status: 500, json: { error: { message: `Unexpected ${path}` } } });
  });
  await page.goto("/");
  await page.getByLabel("Email", { exact: true }).fill("test@example.com");
  await page.getByLabel("Пароль", { exact: true }).fill("Test-password1");
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await page.getByRole("combobox", { name: "Рабочее пространство", exact: true }).selectOption("workspace");
  await page.getByRole("button", { name: "ИИ-помощник", exact: true }).click();
  await page.getByRole("button", { name: "Новая рассылка", exact: true }).click();
  const sender = page.getByRole("combobox", { name: "Email отправителя", exact: true });
  await page.getByRole("button", { name: "Выбрать адрес отправителя" }).click();
  await expect(page.getByRole("option", { name: "sales@example.com", exact: true })).toHaveCount(1);
  await page.getByRole("option", { name: "sales@example.com", exact: true }).click();
  await expect(sender).toHaveValue("sales@example.com");
  await sender.fill("NEW@example.com");
  await page.getByLabel("Название рассылки", { exact: true }).fill("Новая кампания");
  await page.getByLabel("Продукт / услуга", { exact: true }).fill("Продукт");
  await page.getByLabel("Имя отправителя", { exact: true }).fill("Компания");
  await page.getByLabel("Первое письмо (МСК)", { exact: true }).fill("2028-01-01T10:00");
  await page.getByRole("combobox", { name: "Письмо 1", exact: true }).selectOption("template");
  await page.getByRole("checkbox", { name: "lead@example.com", exact: false }).check();
  await page.getByRole("checkbox", { name: "Проверил получателей", exact: false }).check();
  await page.getByRole("button", { name: "Создать черновик рассылки", exact: true }).click();
  await expect(page.getByRole("form", { name: "Новая рассылка" })).not.toBeVisible();
  expect(created).toBe(1);
  await page.reload();
  await page.getByRole("button", { name: "ИИ-помощник", exact: true }).click();
  await page.getByRole("button", { name: "Новая рассылка", exact: true }).click();
  await sender.focus();
  await sender.press("ArrowDown");
  await sender.press("Enter");
  await expect(sender).toHaveValue("new@example.com");
  expect(created).toBe(1); // Choosing an address must never submit or start a campaign.
  await sender.press("ArrowUp");
  await sender.press("Escape");
  await expect(sender).toHaveAttribute("aria-expanded", "false");
  const formBounds = await page.getByRole("form", { name: "Новая рассылка" }).boundingBox();
  const inputBounds = await sender.boundingBox();
  expect(inputBounds!.x + inputBounds!.width).toBeLessThan(formBounds!.x + formBounds!.width);
  await page.getByRole("button", { name: "Выбрать адрес отправителя" }).click();
  await page.screenshot({ path: test.info().outputPath("sender-selector.png"), fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
});
