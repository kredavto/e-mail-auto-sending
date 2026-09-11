import { expect, test } from "@playwright/test";

test("50 MiB CSV is parsed and imported; larger CSV and XLSX are rejected before reading", async ({ page }) => {
  test.setTimeout(60000);
  let saved = false;
  let imports = 0;
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.route("https://fonts.googleapis.com/**", route => route.abort());
  await page.route("https://fonts.gstatic.com/**", route => route.abort());
  await page.addInitScript(() => {
    localStorage.setItem("access_token", "test-token");
    localStorage.setItem("workspace_id", "test-workspace");
  });
  const contact = { id: "test-contact", email: "large@example.com", company: "Тест", full_name: "", status: "new" };
  await page.route("**/api/v1/**", route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/workspaces")) return route.fulfill({ json: [{ id: "test-workspace", name: "Тест" }] });
    if (path.endsWith("/templates")) return route.fulfill({ json: [] });
    if (path.endsWith("/contacts")) return route.fulfill({ json: { items: saved ? [contact] : [], total: saved ? 1 : 0 } });
    if (path.endsWith("/contacts/bulk")) {
      imports++;
      const data = route.request().postDataJSON();
      expect(data.contacts).toHaveLength(1);
      expect(data.contacts[0]).toMatchObject({ email: contact.email, company: contact.company });
      expect((route.request().postData() ?? "").length).toBeLessThan(1000);
      saved = true;
      return route.fulfill({ json: { created: 1, skipped: 0, errors: [] } });
    }
    throw new Error(`Unexpected request: ${path}`);
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Контакты и импорт", exact: true }).click();
  await expect(page.getByText("Excel .xlsx или CSV", { exact: false })).toContainText("до 50 МБ / 70000 контактов");
  const input = page.getByLabel("Файл контактов");
  // A real 50 MiB File, not a mocked size: whitespace represents non-contact data.
  // Construct in-browser to avoid Playwright's buffer-upload transport limit.
  await input.evaluate((element) => {
    const csv = "Email,Компания\nlarge@example.com,Тест";
    const file = new File([csv, " ".repeat(50 * 1024 * 1024 - new TextEncoder().encode(csv).length)], "large.csv", { type: "text/csv" });
    const transfer = new DataTransfer(); transfer.items.add(file);
    (element as HTMLInputElement).files = transfer.files;
    element.dispatchEvent(new Event("change", { bubbles: true }));
  });
  const confirm = page.getByRole("button", { name: "Импортировать 1 контактов", exact: true });
  await expect(confirm).toBeEnabled({ timeout: 30000 });
  expect(imports).toBe(0);
  await confirm.click();
  await expect(page.getByText("Создано: 1.", { exact: false })).toBeVisible();
  expect(imports).toBe(1);
  for (const extension of ["csv", "xlsx"]) {
    await input.evaluate((element, extension) => {
      const file = new File([new Uint8Array(50 * 1024 * 1024 + 1)], `oversized.${extension}`);
      file.arrayBuffer = () => { throw new Error("Oversized file must not be read"); };
      const transfer = new DataTransfer(); transfer.items.add(file);
      (element as HTMLInputElement).files = transfer.files;
      element.dispatchEvent(new Event("change", { bubbles: true }));
    }, extension);
    await expect(page.getByRole("alert")).toContainText("Файл больше 50 МБ");
    await expect(confirm).toHaveCount(0);
  }
  expect(imports).toBe(1);
  expect(errors).toEqual([]);
});
