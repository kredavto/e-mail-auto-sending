// The existing next_steps wire field carries tagged answers as well as guidance.
// Untagged guidance must never become an answer sent on the user's behalf.
export function splitAssistantReplies(steps: string[] = []) {
  const replies: string[] = [];
  const nextSteps: string[] = [];
  for (const step of steps) {
    if (step.startsWith("[answer]")) {
      const label = step.slice(8).trim();
      if (label && label.length <= 80 && !replies.includes(label) && replies.length < 4) replies.push(label);
    } else nextSteps.push(step);
  }
  return { replies, nextSteps };
}
