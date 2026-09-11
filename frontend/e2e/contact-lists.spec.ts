import { expect, test } from "@playwright/test";

test("named imports survive reload, can be renamed and selected, including existing contacts", async ({ page }) => {
  const lists: { id: string; name: string; emails: string[] }[] = [];
  const contacts = new Map<string, { id: string; email: string; full_name: string; company: string; status: string }>();
  await page.addInitScript(() => {
    localStorage.setItem("access_token", "test-token"); localStorage.setItem("workspace_id", "test-workspace");
  });
  await page.route("**/api/v1/**", route => {
    const url = new URL(route.request().url()), path = url.pathname;
    const method = route.request().method();
    const reply = (json: unknown) => route.fulfill({ json });
    if (path.endsWith("/workspaces")) return reply([{ id: "test-workspace", name: "Тест" }]);
    if (path.endsWith("/templates") || path.endsWith("/campaigns") || path.endsWith("/assistant/runs")) return reply([]);
    if (path.endsWith("/assistant/context")) return reply({ ai_configured: false, can_manage: true, delivery_mode: "test", daily_limit: 30, counts: { contacts: contacts.size, templates: 0, campaigns: 0 } });
    if (path.endsWith("/contacts/lists")) {
      if (method === "GET") return reply(lists);
      const body = route.request().postDataJSON();
      const list = { id: `list-${lists.length + 1}`, name: body.name, emails: body.include_existing ? [...contacts.keys()] : [] };
      lists.push(list); return reply(list);
    }
    if (path.includes("/contacts/lists/") && method === "PATCH") {
      const list = lists.find(item => item.id === path.split("/").at(-1))!;
      list.name = route.request().postDataJSON().name; return reply(list);
    }
    if (path.endsWith("/contacts/bulk")) {
      const body = route.request().postDataJSON(), list = lists.find(item => item.id === body.list_id)!;
      let created = 0;
      for (const item of body.contacts) {
        if (!contacts.has(item.email)) { contacts.set(item.email, { ...item, id: item.email, status: "new" }); created++; }
        if (!list.emails.includes(item.email)) list.emails.push(item.email);
      }
      return reply({ created, skipped: body.contacts.length - created, errors: [] });
    }
    if (path.endsWith("/contacts")) {
      const list = lists.find(item => item.id === url.searchParams.get("list_id"));
      const items = [...contacts.values()].filter(item => !list || list.emails.includes(item.email));
      return reply({ items, total: items.length });
    }
    throw new Error(`Unexpected ${method} ${path}`);
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Контакты и импорт", exact: true }).click();
  for (const [name, emails] of [["Москва", "a@example.com\nb@example.com"], ["Казань", "b@example.com\nc@example.com"]]) {
    await page.getByLabel("Файл контактов").setInputFiles({ name: "contacts.csv", mimeType: "text/csv", buffer: Buffer.from(`Email\n${emails}`) });
    await page.getByLabel("Название загружаемой базы", { exact: true }).fill(name);
    await page.getByRole("button", { name: "Импортировать 2 контактов", exact: true }).click();
    await expect(page.getByLabel("Файл контактов")).toBeEnabled();
    await expect(page.getByRole("combobox", { name: "Выбрать базу контактов", exact: true })).toHaveValue(lists.at(-1)!.id);
  }
  expect(contacts.size).toBe(3);
  await page.reload();
  await page.getByRole("button", { name: "Контакты и импорт", exact: true }).click();
  const selector = page.getByRole("combobox", { name: "Выбрать базу контактов", exact: true });
  await selector.selectOption({ label: "Москва" });
  await expect(page.getByRole("cell", { name: "a@example.com", exact: true })).toBeVisible();
  await expect(page.getByRole("cell", { name: "c@example.com", exact: true })).toHaveCount(0);
  await page.getByLabel("Название сохранённой базы", { exact: true }).fill("Москва — сентябрь");
  await page.getByRole("button", { name: "Сохранить название", exact: true }).click();
  await expect(selector.locator("option:checked")).toHaveText("Москва — сентябрь");
  await selector.selectOption("");
  await page.getByLabel("Название сохранённой базы", { exact: true }).fill("Общая база");
  await page.getByRole("button", { name: "Сохранить все контакты как базу", exact: true }).click();
  await expect(selector.locator("option:checked")).toHaveText("Общая база");
  expect(lists.at(-1)!.emails).toHaveLength(3);
  await page.getByRole("button", { name: "ИИ-помощник", exact: true }).click();
  await page.getByRole("button", { name: "Новая рассылка", exact: true }).click();
  const recipients = page.getByRole("combobox", { name: "База получателей", exact: true });
  await recipients.selectOption({ label: "Москва — сентябрь" });
  const form = page.getByRole("form", { name: "Новая рассылка" });
  await expect(form.getByText("a@example.com", { exact: false })).toBeVisible();
  await expect(form.getByText("c@example.com", { exact: false })).toHaveCount(0);
  await form.getByRole("checkbox").first().check();
  await expect(form.getByText("Выбрано получателей: 1 / 1000")).toBeVisible();
  await recipients.selectOption({ label: "Казань" });
  await expect(form.getByText("Выбрано получателей: 0 / 1000")).toBeVisible();
});
