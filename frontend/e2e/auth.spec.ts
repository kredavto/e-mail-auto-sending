import { expect, test } from "@playwright/test";

test("expired refresh token opens sign-in, removes stale credentials and supports signing in again", async ({ page }) => {
  let refreshes = 0;
  await page.addInitScript(() => {
    localStorage.setItem("access_token", "expired"); localStorage.setItem("refresh_token", "expired-refresh"); localStorage.setItem("workspace_id", "workspace");
  });
  await page.route("**/api/v1/**", route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/assistant/context")) return route.fulfill({ json: { ai_configured: false, counts: { contacts: 0, templates: 0, campaigns: 0 } } });
    if (path.endsWith("/auth/refresh")) { refreshes++; return route.fulfill({ status: 401, json: { detail: "expired" } }); }
    if (path.endsWith("/auth/login")) return route.fulfill({ json: { access_token: "new", refresh_token: "new-refresh", mfa_required: false } });
    if (route.request().headers().authorization !== "Bearer new") return route.fulfill({ status: 401, json: {} });
    if (path.endsWith("/workspaces")) return route.fulfill({ json: [{ id: "workspace", name: "Компания" }] });
    if (path.endsWith("/contacts")) return route.fulfill({ json: { items: [], total: 0 } });
    return route.fulfill({ json: [] });
  });
  await page.goto("/");
  const form = page.getByRole("form", { name: "Вход", exact: true });
  await expect(form).toBeVisible();
  await expect(page.getByRole("status")).toContainText("Сессия завершена");
  expect(await page.evaluate(() => localStorage.getItem("refresh_token"))).toBeNull();
  expect(refreshes).toBe(1);
  await form.getByLabel("Email", { exact: true }).fill("user@example.com");
  await form.getByLabel("Пароль", { exact: true }).fill("SecurePass123");
  await form.getByRole("button", { name: "Войти", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Ваше рабочее пространство" })).toBeVisible();
  await expect(page.getByLabel("Рабочее пространство", { exact: true })).toHaveValue("workspace");
});

test("registration validates matching passwords, signs in and creates a workspace", async ({ page }) => {
  const calls: string[] = [];
  await page.route("**/api/v1/**", route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/assistant/context")) return route.fulfill({ json: { ai_configured: false, counts: { contacts: 0, templates: 0, campaigns: 0 } } });
    if (path.endsWith("/auth/register")) {
      calls.push("register");
      expect(route.request().postDataJSON()).toMatchObject({ email: "user@example.com", full_name: "Иван Петров" });
      return route.fulfill({ status: 201, json: { id: "user" } });
    }
    if (path.endsWith("/auth/login")) { calls.push("login"); return route.fulfill({ json: { access_token: "new", refresh_token: "refresh", mfa_required: false } }); }
    if (path.endsWith("/workspaces")) {
      if (route.request().method() === "POST") { calls.push("workspace"); expect(route.request().postDataJSON().name).toBe("Компания"); return route.fulfill({ status: 201, json: { id: "workspace", name: "Компания" } }); }
      return route.fulfill({ json: [{ id: "workspace", name: "Компания" }] });
    }
    if (path.endsWith("/contacts")) return route.fulfill({ json: { items: [], total: 0 } });
    return route.fulfill({ json: [] });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Создать аккаунт", exact: true }).click();
  const form = page.getByRole("form", { name: "Регистрация", exact: true });
  await form.getByLabel("Ваше имя").fill("Иван Петров");
  await form.getByLabel("Название компании или пространства").fill("Компания");
  await form.getByLabel("Email", { exact: true }).fill("user@example.com");
  await form.getByLabel("Пароль", { exact: true }).fill("SecurePass123");
  await form.getByLabel("Повторите пароль").fill("Different123");
  await form.getByRole("button", { name: "Зарегистрироваться" }).click();
  await expect(page.getByRole("alert")).toContainText("Пароли не совпадают");
  expect(calls).toEqual([]);
  await form.getByLabel("Повторите пароль").fill("SecurePass123");
  await form.getByRole("button", { name: "Зарегистрироваться" }).click();
  await expect(page.getByRole("status")).toContainText("Аккаунт создан");
  await expect(page.getByLabel("Рабочее пространство", { exact: true })).toHaveValue("workspace");
  expect(calls).toEqual(["register", "login", "workspace"]);
  expect(await page.evaluate(() => localStorage.getItem("workspace_id"))).toBe("workspace");
});

for (const status of [200, 503]) test(`refresh ${status} preserves the session without forcing sign-in`, async ({ page }) => {
  let refreshes = 0;
  await page.addInitScript(() => {
    localStorage.setItem("access_token", "old"); localStorage.setItem("refresh_token", "refresh"); localStorage.setItem("workspace_id", "workspace");
  });
  await page.route("**/api/v1/**", route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/assistant/context")) return route.fulfill({ json: { ai_configured: false, counts: { contacts: 0, templates: 0, campaigns: 0 } } });
    if (path.endsWith("/auth/refresh")) { refreshes++; return route.fulfill({ status, json: status === 200 ? { access_token: "new", refresh_token: "rotated" } : {} }); }
    if (route.request().headers().authorization === "Bearer old") return route.fulfill({ status: 401, json: {} });
    if (path.endsWith("/workspaces")) return route.fulfill({ json: [{ id: "workspace", name: "Компания" }] });
    if (path.endsWith("/contacts")) return route.fulfill({ json: { items: [], total: 0 } });
    return route.fulfill({ json: [] });
  });
  await page.goto("/");
  if (status === 200) {
    await expect(page.getByLabel("Рабочее пространство", { exact: true })).toHaveValue("workspace");
    await expect.poll(() => page.evaluate(() => localStorage.getItem("refresh_token"))).toBe("rotated");
    expect(refreshes).toBe(1);
  } else {
    await expect(page.getByRole("alert").first()).toContainText("Не удалось восстановить соединение");
    expect(await page.evaluate(() => localStorage.getItem("refresh_token"))).toBe("refresh");
  }
  await expect(page.getByRole("form", { name: "Вход", exact: true })).toHaveCount(0);
});
