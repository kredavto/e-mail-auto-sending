import { NodeViewWrapper, type NodeViewProps } from "@tiptap/react";
import { safeCtaUrl } from "../../lib/mailing";

export function CtaButtonView({ node, editor, getPos, selected }: NodeViewProps) {
  return <NodeViewWrapper className="my-4 flex items-center gap-2" contentEditable={false}>
    <span data-drag-handle draggable="true" title="Перетащить кнопку" aria-label="Перетащить кнопку" className="cursor-grab select-none rounded border border-ink/20 px-2 py-3 text-ink/60">⠿</span>
    <a data-cta="true" href={safeCtaUrl(node.attrs.url) ?? undefined} target="_blank" rel="noopener noreferrer" className={`min-w-0 break-words rounded-md bg-acid px-5 py-3 font-semibold no-underline ${selected ? "outline outline-2 outline-ink" : ""}`} onClick={event => {
      event.preventDefault();
      const pos = getPos();
      if (typeof pos === "number" && editor.isEditable) editor.chain().focus().setNodeSelection(pos).run();
    }}>{node.attrs.label}</a>
  </NodeViewWrapper>;
}
