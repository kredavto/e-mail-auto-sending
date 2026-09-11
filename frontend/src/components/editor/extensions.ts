import { Node, mergeAttributes } from "@tiptap/core";
import { ReactNodeViewRenderer } from "@tiptap/react";
import { CtaButtonView } from "./CtaButtonView";
import { safeCtaUrl } from "../../lib/mailing";

export const Variable = Node.create({
  name: "variable",
  group: "inline",
  inline: true,
  atom: true,
  addAttributes: () => ({ name: { default: "first_name" } }),
  parseHTML: () => [{ tag: "span[data-variable]", getAttrs: (element) => ({ name: (element as HTMLElement).dataset.variable }) }],
  renderHTML: ({ HTMLAttributes }) => ["span", mergeAttributes({ class: "variable-chip", "data-variable": HTMLAttributes.name }, HTMLAttributes), `{{${HTMLAttributes.name}}}`],
});

function blockNode(name: string, tag: string, className: string) {
  return Node.create({
    name,
    group: "block",
    content: "block+",
    defining: true,
    parseHTML: () => [{ tag: `${tag}[data-block='${name}']` }],
    renderHTML: ({ HTMLAttributes }) => [tag, mergeAttributes({ "data-block": name, class: className }, HTMLAttributes), 0],
  });
}

export const SignatureBlock = blockNode("signatureBlock", "section", "border-t border-stone-200 pt-4 mt-6 text-sm").extend({
  addAttributes: () => ({ signatureId: { default: null, parseHTML: element => element.getAttribute("data-signature-id"), renderHTML: attrs => attrs.signatureId ? { "data-signature-id": attrs.signatureId } : {} } }),
});
export const CaseStudyBlock = blockNode("caseStudyBlock", "aside", "border-l-4 border-acid bg-stone-50 p-4 my-5");
export const UnsubscribeBlock = blockNode("unsubscribeBlock", "footer", "text-xs text-stone-500 mt-8");

export const CTAButton = Node.create({
  name: "ctaButton",
  group: "block",
  atom: true,
  draggable: true,
  addNodeView: () => ReactNodeViewRenderer(CtaButtonView),
  addAttributes: () => ({ label: { default: "Подробнее", parseHTML: element => element.textContent, rendered: false }, url: { default: "", parseHTML: element => element.getAttribute("href"), rendered: false } }),
  parseHTML: () => [{ tag: "a[data-cta]" }],
  renderHTML: ({ node, HTMLAttributes }) => ["a", mergeAttributes(HTMLAttributes, { "data-cta": "true", href: safeCtaUrl(node.attrs.url) ?? undefined, target: "_blank", rel: "noopener noreferrer", class: "inline-block rounded-md bg-acid px-5 py-3 font-semibold no-underline my-4" }), node.attrs.label],
});

export const EmailImage = Node.create({
  name: "emailImage",
  group: "block",
  atom: true,
  draggable: true,
  addAttributes: () => ({ src: { default: "" }, alt: { default: "" } }),
  parseHTML: () => [{ tag: "img[data-email-image]" }],
  renderHTML: ({ HTMLAttributes }) => ["img", mergeAttributes(HTMLAttributes, {
    src: safeCtaUrl(HTMLAttributes.src) ?? undefined,
    "data-email-image": "true",
    style: "display:block;width:25%;height:auto;margin:16px 0;",
  })],
});

export const EmailVideo = Node.create({
  name: "emailVideo",
  group: "block",
  atom: true,
  draggable: true,
  addAttributes: () => ({
    src: { default: "", rendered: false, parseHTML: element => element.getAttribute("data-video-src") },
    poster: { default: "", rendered: false, parseHTML: element => element.querySelector("img")?.getAttribute("src") },
    alt: { default: "", rendered: false, parseHTML: element => element.querySelector("img")?.getAttribute("alt") },
  }),
  parseHTML: () => [{ tag: "div[data-email-video]" }],
  renderHTML: ({ node }) => ["div", { "data-email-video": "true", "data-video-src": safeCtaUrl(node.attrs.src) ?? undefined, style: "width:25%;margin:16px 0;" },
    ["img", { src: safeCtaUrl(node.attrs.poster) ?? undefined, alt: node.attrs.alt || "Смотреть видео", style: "display:block;width:100%;height:auto;" }],
    ["span", { style: "font-size:12px;" }, `▶ ${node.attrs.alt || "Смотреть видео"}`],
  ],
});

