// The existing next_steps wire field carries tagged answers as well as guidance.
// Untagged guidance must never become an answer sent on the user's behalf.
export function splitAssistantReplies(steps: string[] = [], message = "") {
  const replies: string[] = [];
  const nextSteps: string[] = [];
  for (const step of steps) {
    if (step.startsWith("[answer]")) {
      const label = step.slice(8).trim();
      if (label && label.length <= 80 && !replies.includes(label) && replies.length < 6) replies.push(label);
    } else nextSteps.push(step);
  }
  const choosingAudience = /аудитори/iu.test(message) && /предлага|услуг|продукт/iu.test(message);
  if (choosingAudience && replies.length) {
    const additions = ["B2C-набор персонала", "B2C-сервис для клиентов"];
    const otherReplies = replies.filter(reply => !additions.includes(reply)).slice(0, 4);
    return { replies: [...otherReplies, ...additions], nextSteps };
  }
  return { replies, nextSteps };
}
