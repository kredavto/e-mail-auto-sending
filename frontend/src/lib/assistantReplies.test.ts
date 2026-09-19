import { expect, test } from "vitest";
import { splitAssistantReplies } from "./assistantReplies";
test("separates suggested replies from recommendations and rejects unusable labels", () => {
  expect(splitAssistantReplies(["[answer] Да", "Проверьте письмо", "[answer] Нет", "[answer] Да", "[answer] ", `[answer] ${"a".repeat(81)}`])).toEqual({ replies: ["Да", "Нет"], nextSteps: ["Проверьте письмо"] });
  expect(splitAssistantReplies()).toEqual({ replies: [], nextSteps: [] });
});

test("audience selection includes both B2C options without changing other questions", () => {
  const steps = ["[answer] Услуга для руководителей отделов продаж", "[answer] B2B-сервис для малого бизнеса", "[answer] Консультация по увеличению продаж"];
  const question = "Уточните, что вы предлагаете и какую аудиторию хотите заинтересовать.";
  expect(splitAssistantReplies(steps, question).replies).toEqual([...steps.map(s => s.slice(8).trim()), "B2C-набор персонала", "B2C-сервис для клиентов"]);
  expect(splitAssistantReplies([...steps, "[answer] B2C-набор персонала"], question).replies).toHaveLength(5);
  expect(splitAssistantReplies(["[answer] Завтра", "[answer] Через неделю"], "Когда отправить письмо?").replies).toEqual(["Завтра", "Через неделю"]);
});
