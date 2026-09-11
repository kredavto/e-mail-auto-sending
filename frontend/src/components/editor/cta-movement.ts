import type { Editor } from "@tiptap/core";
import { closeHistory } from "@tiptap/pm/history";

// Move the selected button past one sibling, preserving its parent and all attributes.
// A single transaction makes each move undoable and keeps the button selected.
export function ctaDestination(editor: Editor, direction: -1 | 1): number | null {
  const { from, to, $from } = editor.state.selection;
  const node = editor.state.doc.nodeAt(from);
  if (node?.type.name !== "ctaButton" || to !== from + node.nodeSize) return null;
  const index = $from.index();
  const sibling = $from.parent.maybeChild(index + direction);
  return sibling ? from + direction * sibling.nodeSize : null;
}

export function moveCta(editor: Editor, direction: -1 | 1) {
  const destination = ctaDestination(editor, direction);
  if (destination === null || !editor.isEditable) return;
  const { from, to } = editor.state.selection;
  const node = editor.state.doc.nodeAt(from)!;
  editor.chain().focus().command(({ tr }) => {
    closeHistory(tr);
    tr.delete(from, to).insert(destination, node);
    return true;
  }).setNodeSelection(destination).run();
}
