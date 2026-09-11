import { expect, test } from "@playwright/test";

test("signature library: create, reload, choose, replace, edit and save in letter", async ({ page }) => {
  const signatures: { id: string; name: string; html_template: string }[] = [];
  let saved: any;
  await page.route("https://fonts.googleapis.com/**", route => route.abort());
  await page.route("https://fonts.gstatic.com/**", route => route.abort());
  await page.addInitScript(() => { localStorage.setItem("access_token", "test"); localStorage.setItem("workspace_id", "workspace"); });
  await page.route("**/api/v1/**", async route => {
    const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
    const method = route.request().method();
    const reply = (json: unknown) => route.fulfill({ json });
    if (path === "/workspaces") return reply([{ id: "workspace", name: "Тест" }]);
    if (path === "/signatures" && method === "POST") {
      const item = { ...route.request().postDataJSON(), id: `s${signatures.length + 1}` };
      signatures.push(item); return reply(item);
    }
    if (path === "/signatures") return reply(signatures);
    if (path.startsWith("/signatures/") && method === "PATCH") {
      const item = signatures.find(s => path.endsWith(s.id))!;
      Object.assign(item, route.request().postDataJSON()); return reply(item);
    }
    if (path === "/templates" && method === "POST") { saved = { ...route.request().postDataJSON(), id: "t1", version: 1, variables: [] }; return reply(saved); }
    if (path === "/templates") return reply(saved ? [saved] : []);
    if (path === "/contacts") return reply({ items: [], total: 0 });
    return reply([]);
  });
  await page.goto("/");
  for (const [name, text] of [["Рабочая", "Юрий\nКомпания"], ["Личная", "Иван\nТелефон"]]) {
    await page.getByRole("button", { name: "Создать подпись", exact: true }).click();
    await page.getByLabel("Название подписи", { exact: true }).fill(name);
    await page.getByLabel("Текст подписи", { exact: true }).fill(text);
    await page.getByRole("button", { name: "Сохранить и вставить подпись" }).click();
    await expect(page.locator('[data-block="signatureBlock"]')).toHaveCount(1);
    await expect(page.locator('[data-block="signatureBlock"]')).toContainText(text.split("\n")[0]);
  }
  await page.reload();
  const select = page.getByRole("combobox", { name: "Выбрать подпись", exact: true });
  await select.selectOption("s1");
  await expect(page.locator('[data-block="signatureBlock"]')).toContainText("Юрий");
  await select.selectOption("s2");
  await expect(page.locator('[data-block="signatureBlock"]')).toHaveCount(1);
  await expect(page.locator('[data-block="signatureBlock"]')).not.toContainText("Юрий");
  await page.getByRole("button", { name: "Изменить подпись" }).click();
  await page.getByLabel("Текст подписи", { exact: true }).fill("Иван Петров\nОтдел продаж");
  await page.getByRole("button", { name: "Сохранить и вставить подпись" }).click();
  await expect(page.locator('[data-block="signatureBlock"]')).toContainText("Иван Петров");
  await page.getByLabel("Название шаблона", { exact: true }).fill("Письмо с подписью");
  await page.getByRole("button", { name: "Сохранить шаблон", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("Шаблон сохранён");
  const block = saved.editor_state.content.find((node: any) => node.type === "signatureBlock");
  expect(block.attrs.signatureId).toBe("s2");
  expect(JSON.stringify(block)).toContain("Иван Петров");
  await select.selectOption("");
  await expect(page.locator('[data-block="signatureBlock"]')).toHaveCount(0);
  await expect(page.locator(".tiptap")).toContainText("Здравствуйте");
});
