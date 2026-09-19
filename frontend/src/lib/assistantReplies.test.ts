import { expect, test } from "vitest";
import { splitAssistantReplies } from "./assistantReplies";
test("separates suggested replies from recommendations and rejects unusable labels", () => {
  expect(splitAssistantReplies(["[answer] Да", "Проверьте письмо", "[answer] Нет", "[answer] Да", "[answer] ", `[answer] ${"a".repeat(81)}`])).toEqual({ replies: ["Да", "Нет"], nextSteps: ["Проверьте письмо"] });
  expect(splitAssistantReplies()).toEqual({ replies: [], nextSteps: [] });
});
