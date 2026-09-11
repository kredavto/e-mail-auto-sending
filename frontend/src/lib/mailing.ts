import type { JSONContent } from "@tiptap/core";

export const stages = { first_contact: "Первое обращение", second: "Повторное обращение", warmup: "Прогрев", cta: "Предложение / CTA", reminder: "Напоминание" } as const;
export type Stage = keyof typeof stages;
export const letterTypes = { personalized: "Персонализированное", general: "Общее" } as const;
export type LetterType = keyof typeof letterTypes;
export function getLetterType(state?: JSONContent): LetterType {
  return state?.attrs?.letterType === "general" ? "general" : "personalized";
}
export function withLetterType(state: JSONContent, letterType: LetterType): JSONContent {
  return { ...state, attrs: { ...state.attrs, letterType } };
}
// General letters support only a shared product name, never recipient data or expressions.
export function generalLetterIssue(state: JSONContent, subject: string): string {
  const values: string[] = [subject];
  function collect(node: JSONContent) {
    if (node.text) values.push(node.text);
    if (node.type === "variable") values.push(`{{${node.attrs?.name ?? ""}}}`);
    else values.push(...Object.values(node.attrs ?? {}).filter((v): v is string => typeof v === "string"));
    node.content?.forEach(collect);
  }
  collect(state);
  const remaining = values.join("\n").replace(/{{\s*product_name\s*}}/g, "");
  const variables = [...new Set(Array.from(remaining.matchAll(/{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*}}/g), m => m[1]))];
  return /{{|{%|{#/.test(remaining)
    ? `Общее письмо не использует данные получателя. Замените ${variables.length ? variables.map(v => `{{${v}}}`).join(", ") : "персональные переменные и выражения"} обычным текстом в теме и письме или выберите «Персонализированное». Доступна только общая переменная {{product_name}}.`
    : "";
}
export type MailTemplate = { id: string; name: string; category: Stage; subject_template: string; editor_state: JSONContent; version: number; variables: string[] };
export type Contact = { id: string; email: string; full_name: string; first_name: string; last_name: string; patronymic: string | null; company: string; position: string; phone?: string; industry?: string; current_site_url?: string; company_size?: string; annual_revenue_tier?: string; status: string; custom_fields: Record<string, unknown> };
export type ContactPage = { items: Contact[]; total: number; page: number; page_size: number };
export const initialDocument: JSONContent = { type: "doc", content: [{ type: "paragraph", content: [{ type: "text", text: "Здравствуйте, " }, { type: "variable", attrs: { name: "first_name" } }, { type: "text", text: "!" }] }] };
export const baseVariables = ["first_name", "full_name", "last_name", "patronymic", "company", "position", "email", "phone", "industry", "current_site_url", "company_size", "annual_revenue_tier", "product_name"];
export function safeCtaUrl(value: string): string | null {
  try {
    const url = new URL(value.trim());
    return ["https:", "http:"].includes(url.protocol) && !url.username && !url.password ? url.href : null;
  } catch { return null; }
}
export function contactVariables(contact: Contact, productName: string): Record<string, string> {
  const result: Record<string, string> = {};
  for (const [key, value] of Object.entries(contact.custom_fields ?? {})) {
    if (/^[a-zA-Z][a-zA-Z0-9_]*$/.test(key) && !baseVariables.includes(key)) result[key] = String(value ?? "");
  }
  for (const key of baseVariables) result[key] = String(contact[key as keyof Contact] ?? "");
  result.product_name = productName;
  return result;
}
export function interpolate(value: string, variables: Record<string, string>): string {
  return value.replace(/{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*}}/g, (original, key) => variables[key] || original);
}
