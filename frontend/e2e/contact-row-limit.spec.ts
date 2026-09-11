import { expect, test } from "@playwright/test";

test("70000 data rows plus a header import intact in batches; row and expanded-email overflow are rejected", async ({ page }) => {
  test.setTimeout(120000);
  let imports = 0;
  const received: { email: string; company: string }[] = [];
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.route("https://fonts.googleapis.com/**", route => route.abort());
  await page.route("https://fonts.gstatic.com/**", route => route.abort());
  await page.addInitScript(() => {
    localStorage.setItem("access_token", "test-token");
    localStorage.setItem("workspace_id", "test-workspace");
  });
  await page.route("**/api/v1/**", route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/workspaces")) return route.fulfill({ json: [{ id: "test-workspace", name: "Тест" }] });
    if (path.endsWith("/templates")) return route.fulfill({ json: [] });
    if (path.endsWith("/contacts")) return route.fulfill({ json: { items: [], total: 0 } });
    if (path.endsWith("/contacts/bulk")) {
      imports++;
      const contacts = route.request().postDataJSON().contacts;
      expect(contacts).toHaveLength(500);
      expect(Buffer.byteLength(route.request().postData()!)).toBeLessThanOrEqual(512 * 1024);
      received.push(...contacts);
      return route.fulfill({ json: { created: contacts.length, skipped: 0, errors: [] } });
    }
    throw new Error(`Unexpected request: ${path}`);
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Контакты и импорт", exact: true }).click();
  const input = page.getByLabel("Файл контактов");
  const rows = Array.from({ length: 70000 }, (_, i) => `c${i}@example.com,Компания ${i}`);
  const upload = (data: string) => input.setInputFiles({ name: "contacts.csv", mimeType: "text/csv", buffer: Buffer.from(data) });
  await upload(["Email,Компания", ...rows, ""].join("\r\n"));
  const confirm = page.getByRole("button", { name: "Импортировать 70000 контактов", exact: true });
  await expect(confirm).toBeEnabled();
  expect(imports).toBe(0);
  await confirm.click();
  await expect(page.getByRole("status").filter({ hasText: "Создано: 70000." })).toBeVisible({ timeout: 90000 });
  await expect(input).toBeEnabled();
  expect(imports).toBe(140);
  expect(received).toHaveLength(70000);
  expect(new Set(received.map(contact => contact.email)).size).toBe(70000);
  expect(received[0]).toMatchObject({ email: "c0@example.com", company: "Компания 0" });
  expect(received[69999]).toMatchObject({ email: "c69999@example.com", company: "Компания 69999" });

  await upload(["Email,Компания", ...rows, "extra@example.com,Лишний"].join("\n"));
  await expect(page.getByRole("alert")).toContainText("Лимит: 70000 строк контактов и 100 колонок");
  await expect(confirm).toHaveCount(0);

  await upload(["Email,Компания", ...rows.slice(0, -1), "c69999@example.com;extra@example.com,Лишний"].join("\n"));
  await expect(page.getByText("После разделения email получилось больше 70000 контактов.", { exact: false })).toBeVisible();
  await expect(page.getByRole("button", { name: "Импортировать 0 контактов", exact: true })).toBeDisabled();
  expect(imports).toBe(140);
  expect(errors).toEqual([]);
});

test("interrupted import reports saved contacts and resumes without repeating confirmed batches", async ({ page }) => {
  const starts: string[] = [];
  await page.addInitScript(() => {
    localStorage.setItem("access_token", "test-token");
    localStorage.setItem("workspace_id", "test-workspace");
  });
  await page.route("**/api/v1/**", route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/workspaces")) return route.fulfill({ json: [{ id: "test-workspace", name: "Тест" }] });
    if (path.endsWith("/templates")) return route.fulfill({ json: [] });
    if (path.endsWith("/contacts")) return route.fulfill({ json: { items: [], total: 0 } });
    if (path.endsWith("/contacts/bulk")) {
      const contacts = route.request().postDataJSON().contacts;
      starts.push(contacts[0].email);
      if (starts.length === 2) return route.fulfill({ status: 503, json: { detail: "Временный сбой" } });
      return route.fulfill({ json: { created: contacts.length, skipped: 0, errors: [] } });
    }
    throw new Error(`Unexpected request: ${path}`);
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Контакты и импорт", exact: true }).click();
  await page.getByLabel("Файл контактов").setInputFiles({ name: "resume.csv", mimeType: "text/csv", buffer: Buffer.from(["Email", ...Array.from({ length: 1001 }, (_, i) => `c${i}@example.com`)].join("\n")) });
  const confirm = page.getByRole("button", { name: "Импортировать 1001 контактов", exact: true });
  await confirm.click();
  await expect(page.getByRole("alert")).toContainText("Подтверждено создано: 500");
  await expect(confirm).toBeEnabled();
  expect(starts).toEqual(["c0@example.com", "c500@example.com"]);
  await confirm.click();
  await expect(page.getByRole("status").filter({ hasText: "Создано: 1001." })).toBeVisible();
  expect(starts).toEqual(["c0@example.com", "c500@example.com", "c500@example.com", "c1000@example.com"]);
  await expect(confirm).toBeDisabled();
});
