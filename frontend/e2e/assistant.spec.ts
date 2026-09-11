import { expect, test } from "@playwright/test";
import type { AssistantRun } from "../src/components/AssistantPanel";

test("AI draft → saved editor template; schedule stays unchanged until confirmation", async ({ page }) => {
  let confirms = 0;
  let proposals = 0;
  let saved = false;
  const campaign = { id: "campaign-1", name: "Тестовая рассылка", status: "draft", sender_email: "sender@example.com", schedule_start: "2028-01-01T10:00:00+03:00" };
  let history: AssistantRun[] = [];
  const makeRun = (result: AssistantRun["result"]): AssistantRun => ({ id: "run-1", prompt: "Тестовый запрос", model: "test-model", status: "complete", created_at: "2026-09-11T10:00:00Z", applied_at: null, input_tokens: 100, output_tokens: 70, result });
  const draft = { name: "ИИ-черновик", category: "first_contact" as const, subject: "Идея для вашей компании", paragraphs: ["Здравствуйте! Предлагаем обсудить внедрение CRM."], editor_state: { type: "doc", content: [{ type: "paragraph", content: [{ type: "text", text: "Здравствуйте! Предлагаем обсудить внедрение CRM." }] }] } };
  await page.route("https://fonts.googleapis.com/**", r => r.abort());
  await page.route("https://fonts.gstatic.com/**", r => r.abort());
 await page.route("**/api/v1/**", async route => {
      if (new URL(route.request().url()).pathname.endsWith("/contacts/lists")) return route.fulfill({ json: route.request().method() === "POST" ? { id: "test-list", name: route.request().postDataJSON().name } : [{ id: "test-list", name: "Тестовая база" }] });
    const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
    const method = route.request().method();
    const reply = (json: unknown, status = 200) => route.fulfill({ status, json });
    if (path === "/auth/login") return reply({ access_token: "test", refresh_token: "refresh" });
    if (path === "/workspaces") return reply([{ id: "workspace", name: "Тест" }]);
    if (path === "/contacts") return reply({ items: [], total: 0 });
    if (path === "/campaigns") return reply([campaign]);
    if (path === "/templates" && method === "GET") return reply([]);
    if (path === "/templates" && method === "POST") { saved = true; return reply({ ...route.request().postDataJSON(), id: "saved-template", version: 1, variables: [] }); }
    if (path === "/assistant/context") return reply({ ai_configured: true, can_manage: true, delivery_mode: "test", daily_limit: 30, counts: { contacts: 1, templates: 0, campaigns: 1 } });
    if (path === "/assistant/runs" && method === "GET") return reply(history);
    if (path === "/assistant/runs" && method === "POST") { history = [makeRun({ message: "Черновик готов. Проверьте его в редакторе.", draft, next_steps: ["Проверить письмо"], action: null })]; return reply(history[0]); }
    if (path === "/assistant/campaigns/campaign-1/propose") {
      proposals++; expect(confirms).toBe(0); expect(campaign.status).toBe("draft");
      history = [makeRun({ message: "Требуется подтверждение", action: { kind: "start", campaign_id: campaign.id, campaign_name: campaign.name, send_at: campaign.schedule_start, recipients: 1, sender_email: campaign.sender_email, warning: "Пауза не отзывает уже переданные письма." } })]; return reply(history[0]);
    }
    if (path === "/assistant/runs/run-1/confirm") { confirms++; expect(route.request().postDataJSON()).toEqual({ confirmed: true }); campaign.status = "running"; history[0].applied_at = "2026-09-11T10:05:00Z"; return reply(history[0]); }
    return reply({ error: { message: `Unexpected ${method} ${path}` } }, 500);
  });
  await page.goto("/");
  await page.getByLabel("Email", { exact: true }).fill("test@example.com");
  await page.getByLabel("Пароль", { exact: true }).fill("Test-password1");
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await page.getByRole("combobox", { name: "Рабочее пространство", exact: true }).selectOption("workspace");
  await page.getByRole("button", { name: "ИИ-помощник", exact: true }).click();
  await expect(page.getByText("Тестовая доставка:", { exact: false })).toBeVisible();
  await page.getByLabel("Задание для ИИ").fill("Создай первое письмо директору компании о CRM");
  await page.getByRole("button", { name: "Спросить ИИ" }).click();
  await expect(page.getByRole("region", { name: "Ответ помощника" })).toContainText("Черновик готов");
  expect(saved).toBe(false);
  await page.getByRole("button", { name: "Сохранить как новый шаблон и открыть" }).click();
  await expect(page.getByLabel("Название шаблона")).toHaveValue("ИИ-черновик");
  expect(saved).toBe(true);
  await page.getByRole("button", { name: "ИИ-помощник", exact: true }).click();
  await page.getByLabel("Кампания для управления").selectOption("campaign-1");
  await page.getByRole("button", { name: "Подготовить запуск" }).click();
  await expect(page.getByRole("button", { name: "Подтвердить действие" })).toBeDisabled();
  expect(proposals).toBe(1); expect(confirms).toBe(0);
  await page.getByLabel("Параметры проверены.", { exact: false }).check();
  await page.getByRole("button", { name: "Подтвердить действие" }).click();
  await expect(page.getByRole("status")).toContainText("Действие выполнено");
  expect(confirms).toBe(1);
  await expect(page.getByRole("button", { name: "Подтвердить действие" })).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole("region", { name: "Ответ помощника" })).toContainText("Действие выполнено");
  expect(confirms).toBe(1);
});
