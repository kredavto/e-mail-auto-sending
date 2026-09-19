import { expect, test } from "@playwright/test";

test("schedule whole contact list, preserve Moscow time and show persistent scheduled status", async ({ page }) => {
  let created: Record<string, unknown> | undefined;
  const campaigns: Record<string, unknown>[] = [];
  await page.route("https://fonts.googleapis.com/**", r => r.abort());
  await page.route("https://fonts.gstatic.com/**", r => r.abort());
  await page.route("**/api/v1/**", async route => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace("/api/v1", "");
    const reply = (json: unknown) => route.fulfill({ json });
    if (path === "/auth/login") return reply({ access_token: "test", refresh_token: "refresh" });
    if (path === "/workspaces") return reply([{ id: "workspace", name: "Тест" }]);
    if (path === "/contacts/lists") return reply([{ id: "list", name: "Загруженная база" }]);
    if (path === "/contacts") return reply({ items: [], total: 0 });
    if (path === "/campaigns") return reply(campaigns);
    if (path === "/templates") return reply([{ id: "template", name: "Предложение", subject_template: "Тема", category: "first_contact", editor_state: {}, version: 1, variables: [] }]);
    if (path === "/assistant/context") return reply({ ai_configured: false, can_manage: true, delivery_mode: "test", daily_limit: 30, counts: { contacts: 50000, templates: 1, campaigns: campaigns.length } });
    if (path === "/assistant/runs") return reply([]);
    if (path === "/assistant/contacts") return reply({ items: [{ id: "contact-0", email: "lead@example.com", full_name: "", company: "Тест" }], total: 50000 });
    if (path === "/assistant/contacts/selection") {
      expect(url.searchParams.get("list_id")).toBe("list");
      return reply({ contact_ids: Array.from({ length: 50000 }, (_, i) => `contact-${i}`), total: 50000 });
    }
    if (path === "/assistant/campaigns") {
      created = route.request().postDataJSON();
      expect(created!.launch_mode).toBe("scheduled");
      expect(created!.schedule_start).toBe("2028-10-20T14:35:00+03:00");
      expect(created!.contact_ids).toHaveLength(50000);
      campaigns.push({ ...created, id: "campaign", status: "scheduled" });
      return reply(campaigns[0]);
    }
    return route.fulfill({ status: 500, json: { error: { message: `Unexpected ${path}` } } });
  });
  await page.goto("/");
  await page.getByLabel("Email", { exact: true }).fill("test@example.com");
  await page.getByLabel("Пароль", { exact: true }).fill("Test-password1");
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await page.getByRole("combobox", { name: "Рабочее пространство", exact: true }).selectOption("workspace");
  await page.getByRole("button", { name: "Рассылки по расписанию", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Массовые рассылки по расписанию" })).toBeVisible();
  await page.getByRole("button", { name: "Новая рассылка", exact: true }).click();
  const form = page.getByRole("form", { name: "Новая рассылка" });
  await form.getByLabel("Название рассылки", { exact: true }).fill("Октябрьская кампания");
  await form.getByLabel("Продукт / услуга", { exact: true }).fill("Продукт");
  await form.getByRole("combobox", { name: "Email отправителя", exact: true }).fill("sales@example.com");
  await form.getByLabel("Имя отправителя", { exact: true }).fill("Компания");
  await form.getByLabel("Первое письмо (МСК)", { exact: true }).fill("2028-10-20T14:35");
  await form.getByRole("combobox", { name: "Письмо 1", exact: true }).selectOption("template");
  await form.getByRole("combobox", { name: "База получателей", exact: true }).selectOption("list");
  await form.getByRole("button", { name: "Выбрать всю выборку (50000)" }).click();
  await expect(form.getByRole("button", { name: "Запланировать рассылку" })).toBeDisabled();
  await form.getByRole("checkbox", { name: "Проверил получателей", exact: false }).check();
  await form.getByRole("button", { name: "Запланировать рассылку" }).click();
  await expect(form).not.toBeVisible();
  const view = page.locator(".workspace-view:visible");
  await expect(view.getByLabel("Кампания для управления")).toHaveValue("campaign");
  await expect(view).toContainText("Запланирована · Начало: 20.10.2028, 14:35:00 МСК");
  expect(created).toBeDefined();
  await page.screenshot({ path: "test-results/scheduled-bulk.png", fullPage: true });
});
