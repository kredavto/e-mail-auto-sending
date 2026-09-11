import { expect, test } from "@playwright/test";

test("10000 data rows plus a header import intact; row and expanded-email overflow are rejected", async ({ page }) => {
  let imports = 0;
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
      expect(contacts).toHaveLength(10000);
      expect(new Set(contacts.map((contact: { email: string }) => contact.email)).size).toBe(10000);
      expect(contacts[0]).toMatchObject({ email: "c0@example.com", company: "Компания 0" });
      expect(contacts[9999]).toMatchObject({ email: "c9999@example.com", company: "Компания 9999" });
      return route.fulfill({ json: { created: 10000, skipped: 0, errors: [] } });
    }
    throw new Error(`Unexpected request: ${path}`);
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Контакты и импорт", exact: true }).click();
  const input = page.getByLabel("Файл контактов");
  const rows = Array.from({ length: 10000 }, (_, i) => `c${i}@example.com,Компания ${i}`);
  const upload = (data: string) => input.setInputFiles({ name: "contacts.csv", mimeType: "text/csv", buffer: Buffer.from(data) });
  await upload(["Email,Компания", ...rows].join("\r\n"));
  const confirm = page.getByRole("button", { name: "Импортировать 10000 контактов", exact: true });
  await expect(confirm).toBeEnabled();
  expect(imports).toBe(0);
  await confirm.click();
  await expect(page.getByRole("status").filter({ hasText: "Создано: 10000." })).toBeVisible();
  await expect(input).toBeEnabled();
  expect(imports).toBe(1);

  await upload(["Email,Компания", ...rows, "extra@example.com,Лишний"].join("\n"));
  await expect(page.getByRole("alert")).toContainText("Лимит: 10000 строк контактов и 100 колонок");
  await expect(confirm).toHaveCount(0);

  await upload(["Email,Компания", ...rows.slice(0, -1), "c9999@example.com;extra@example.com,Лишний"].join("\n"));
  await expect(page.getByText("После разделения email получилось больше 10000 контактов.", { exact: false })).toBeVisible();
  await expect(page.getByRole("button", { name: "Импортировать 0 контактов", exact: true })).toBeDisabled();
  expect(imports).toBe(1);
  expect(errors).toEqual([]);
});
